"""
OBC Emulator Adapter
Drop-in replacement for ObcStub using the openobsw host sim (obsw_sim).

Extends Equipment directly — same port interface as ObcEquipment and
ObcStub. Swap at the composition root:

    # Before (simulated OBC):
    obc = ObcStub(config, sync, store, cmd_store, rules=[...])

    # After (real OBSW under test):
    obc = OBCEmulatorAdapter(
        sim_path="build/sim/obsw_sim",
        sync_protocol=sync,
        store=store,
        command_store=cmd_store,
    )

do_step() protocol (called by Equipment.on_tick() each tick):
  1. Map IN port values → TC frames and send to obsw_sim stdin
  2. Wait for 0xFF sync byte on stdout (one OBC control cycle)
  3. Parse TM packets received before sync byte
  4. Update OUT port values from parsed TM

stdin:  [uint16 BE length][TC frame bytes]
stdout: [uint16 BE length][TM packet bytes]  (zero or more per cycle)
        [0xFF]                               (sync byte — end of cycle)

Implements: SVF-DEV-029, SVF-DEV-034, SVF-DEV-037
"""

from __future__ import annotations

import logging
import queue
import struct
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional

from svf.abstractions import SyncProtocol
from svf.command_store import CommandStore
from svf.equipment import Equipment, PortDefinition, PortDirection
from svf.models.obc import MODE_NOMINAL, MODE_SAFE
from svf.parameter_store import ParameterStore

logger = logging.getLogger(__name__)

SYNC_BYTE = 0xFF


class OBCEmulatorAdapter(Equipment):
    """
    OBC Emulator Adapter — wraps obsw_sim as an Equipment.

    Args:
        sim_path:       Path to obsw_sim executable.
        sync_protocol:  SyncProtocol passed to Equipment.
        store:          ParameterStore passed to Equipment.
        command_store:  CommandStore passed to Equipment.
        sync_timeout:   Seconds to wait for 0xFF sync byte per tick.
        apid:           OBC APID expected in TM packets (default 0x010).
    """

    def __init__(
        self,
        sim_path: str | Path,
        sync_protocol: SyncProtocol,
        store: ParameterStore,
        command_store: Optional[CommandStore] = None,
        sync_timeout: float = 5.0,
        apid: int = 0x010,
    ) -> None:
        self._sim_path    = Path(sim_path)
        self._sync_timeout = sync_timeout
        self._apid        = apid

        # OBC state mirrored from parsed TM
        self._obt:          float = 0.0
        self._mode:         int   = MODE_SAFE
        self._tm_seq:       int   = 0

        # Subprocess + reader thread
        self._proc:   Optional[subprocess.Popen] = None
        self._reader: Optional[threading.Thread] = None
        self._rx_q:   queue.Queue[Optional[bytes]] = queue.Queue()
        self._alive   = False

        super().__init__(
            equipment_id="obc",
            sync_protocol=sync_protocol,
            store=store,
            command_store=command_store,
        )

        # Sentinel for mode_cmd: -1.0 = no command (allows MODE_SAFE=0)
        self._port_values["dhs.obc.mode_cmd"] = -1.0

    # ------------------------------------------------------------------ #
    # Equipment interface                                                  #
    # ------------------------------------------------------------------ #

    def _declare_ports(self) -> list[PortDefinition]:
        """Identical to ObcEquipment — drop-in port compatibility."""
        return [
            PortDefinition("obc.tc_input",           PortDirection.IN,
                           description="TC arrival signal"),
            PortDefinition("dhs.obc.mode_cmd",       PortDirection.IN,
                           description="Mode transition command (-1=none)"),
            PortDefinition("dhs.obc.watchdog_kick",  PortDirection.IN,
                           description="Watchdog kick (write 1)"),
            PortDefinition("dhs.obc.memory_dump_cmd",PortDirection.IN,
                           description="Memory dump command"),
            PortDefinition("dhs.obc.mode",           PortDirection.OUT,
                           description="Current OBC mode"),
            PortDefinition("dhs.obc.obt",            PortDirection.OUT,
                           unit="s", description="On-board time"),
            PortDefinition("dhs.obc.watchdog_status",PortDirection.OUT,
                           description="Watchdog status"),
            PortDefinition("dhs.obc.memory_used_pct",PortDirection.OUT,
                           unit="%", description="Mass memory used"),
            PortDefinition("dhs.obc.health",         PortDirection.OUT,
                           description="OBC health status"),
            PortDefinition("dhs.obc.reset_count",    PortDirection.OUT,
                           description="Reset counter"),
            PortDefinition("dhs.obc.cpu_load",       PortDirection.OUT,
                           unit="%", description="CPU load"),
            PortDefinition("obc.tm_output",          PortDirection.OUT,
                           description="Latest TM sequence count"),
        ]

    def initialise(self, start_time: float = 0.0) -> None:
        """Spawn obsw_sim and start stdout reader thread."""
        if not self._sim_path.exists():
            raise FileNotFoundError(
                f"obsw_sim not found at {self._sim_path}. "
                f"Build openobsw first: cmake --build build"
            )
        self._proc = subprocess.Popen(
            [str(self._sim_path)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self._alive = True
        self._reader = threading.Thread(
            target=self._stdout_reader,
            name="obc-emulator-reader",
            daemon=True,
        )
        self._reader.start()
        logger.info(
            f"[obc-emu] obsw_sim started PID={self._proc.pid} "
            f"path={self._sim_path}"
        )

    def teardown(self) -> None:
        """Terminate obsw_sim and join reader thread."""
        self._alive = False
        if self._proc is not None:
            try:
                self._proc.stdin.close()
            except Exception:
                pass
            try:
                self._proc.terminate()
                self._proc.wait(timeout=2.0)
            except Exception:
                self._proc.kill()
            self._proc = None
        self._rx_q.put(None)   # unblock reader
        if self._reader is not None:
            self._reader.join(timeout=2.0)
            self._reader = None
        logger.info("[obc-emu] Terminated")

    def do_step(self, t: float, dt: float) -> None:
        """
        One OBC control cycle:
          1. Build TC frames from IN ports and send to obsw_sim
          2. Wait for 0xFF sync byte
          3. Parse TM packets → update OUT ports
        """
        self._obt += dt
        self._send_tcs(t)
        tm_packets, synced = self._collect_until_sync(self._sync_timeout)

        if not synced:
            logger.warning(f"[obc-emu] No sync byte within {self._sync_timeout}s at t={t:.3f}")

        for pkt in tm_packets:
            self._parse_tm(pkt, t)

        # Write OBC state to OUT ports
        self.write_port("dhs.obc.mode",          float(self._mode))
        self.write_port("dhs.obc.obt",           self._obt)
        self.write_port("dhs.obc.watchdog_status", 0.0)
        self.write_port("dhs.obc.memory_used_pct", 0.0)
        self.write_port("dhs.obc.health",         0.0)
        self.write_port("dhs.obc.reset_count",    0.0)
        self.write_port("dhs.obc.cpu_load",       0.0)
        self.write_port("obc.tm_output",          float(self._tm_seq))

    # ------------------------------------------------------------------ #
    # TC building                                                          #
    # ------------------------------------------------------------------ #

    def _send_tcs(self, t: float) -> None:
        """Map IN port values to TC frames and send them."""
        frames: list[bytes] = []

        # mode_cmd: -1.0 = no command
        mode_cmd = self.read_port("dhs.obc.mode_cmd")
        if mode_cmd >= 0.0:
            mode = int(round(mode_cmd))
            if mode == MODE_NOMINAL:
                frames.append(self._build_s8_recover_nominal())
            self._port_values["dhs.obc.mode_cmd"] = -1.0   # consume

        # watchdog_kick: send S17 ping as keep-alive when kicked
        wdg_kick = self.read_port("dhs.obc.watchdog_kick")
        if wdg_kick > 0.5:
            frames.append(self._build_s17_ping())
            self._port_values["dhs.obc.watchdog_kick"] = 0.0

        # Raw TC bytes from CommandStore via obc.tc_input port
        # (tc_input port value encodes whether a TC is pending)
        if self.read_port("obc.tc_input") > 0.5 and self._command_store is not None:
            try:
                raw = self._command_store.take("obc.tc_uplink")
                if raw is not None and isinstance(raw.value, (bytes, bytearray)):
                    frames.append(bytes(raw.value))
            except (ValueError, KeyError, AttributeError):
                pass
            self._port_values["obc.tc_input"] = 0.0

        # Heartbeat — always send at least one ping so obsw_sim never
        # blocks on fread() and can emit the sync byte on schedule
        if not frames:
            frames.append(self._build_s17_ping())

        for frame in frames:
            self._write_frame(frame)

    def _build_s17_ping(self) -> bytes:
        """TC(17,1) are-you-alive space packet."""
        return bytes.fromhex("1801c0000003201101" + "00")

    def _build_s8_recover_nominal(self) -> bytes:
        """TC(8,1) function_id=1 (recover to NOMINAL)."""
        # Space packet: APID=0x010, S8/1, user_data = [0x00, 0x01, 0x00]
        user_data = bytes([0x00, 0x01, 0x00])   # fn_id=1, args_len=0
        data_len  = 3 + len(user_data) - 1       # PUS secondary hdr (3B) + data - 1
        hdr = struct.pack(">HHHBBB",
            0x1801,          # version=0, TC, sec_hdr=1, APID=0x001
            0xC000,          # unsegmented, seq=0
            data_len,        # data field length - 1
            0x20,            # PUS version + ack flags
            8,               # service
            1,               # subservice
        )
        return hdr + user_data

    def _write_frame(self, frame: bytes) -> None:
        """Send a length-prefixed frame to obsw_sim stdin."""
        if self._proc is None or self._proc.stdin is None:
            return
        try:
            self._proc.stdin.write(struct.pack(">H", len(frame)) + frame)
            self._proc.stdin.flush()
        except Exception as e:
            logger.error(f"[obc-emu] stdin write failed: {e}")

    # ------------------------------------------------------------------ #
    # Stdout reader                                                        #
    # ------------------------------------------------------------------ #

    def _stdout_reader(self) -> None:
        """Background thread — reads bytes from obsw_sim stdout into queue."""
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        try:
            while self._alive:
                b = proc.stdout.read(1)
                if not b:
                    break
                self._rx_q.put(b)
        except Exception as e:
            logger.debug(f"[obc-emu] reader: {e}")
        finally:
            self._rx_q.put(None)

    def _read_byte(self, timeout: float) -> Optional[int]:
        """Read one byte from queue with timeout. Returns None on timeout/EOF."""
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            try:
                chunk = self._rx_q.get(timeout=min(remaining, 0.05))
            except queue.Empty:
                continue
            if chunk is None:
                return None
            return chunk[0]

    def _collect_until_sync(
        self, timeout: float
    ) -> tuple[list[bytes], bool]:
        """Read stdout until 0xFF sync byte or timeout."""
        packets: list[bytes] = []
        deadline = time.monotonic() + timeout

        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return packets, False

            b = self._read_byte(remaining)
            if b is None:
                return packets, False

            if b == SYNC_BYTE:
                return packets, True

            # Length-prefixed TM packet
            b2 = self._read_byte(remaining)
            if b2 is None:
                return packets, False

            length = (b << 8) | b2
            if length == 0 or length > 1024:
                logger.warning(f"[obc-emu] Bad frame length {length}")
                continue

            body = bytearray()
            while len(body) < length:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return packets, False
                b3 = self._read_byte(remaining)
                if b3 is None:
                    return packets, False
                body.append(b3)

            packets.append(bytes(body))

    # ------------------------------------------------------------------ #
    # TM parsing                                                           #
    # ------------------------------------------------------------------ #

    def _parse_tm(self, pkt: bytes, t: float) -> None:
        """Parse a PUS-C TM packet and update internal state."""
        if len(pkt) < 10:
            return

        svc    = pkt[7]
        subsvc = pkt[8]
        self._tm_seq += 1

        if svc == 1:
            self._on_s1(subsvc, pkt, t)
        elif svc == 5:
            self._on_s5(subsvc, pkt, t)
        elif svc == 17 and subsvc == 2:
            logger.info(f"[obc-emu] TM(17,2) pong at t={t:.3f}")

    def _on_s1(self, subsvc: int, pkt: bytes, t: float) -> None:
        labels = {1:"accepted", 2:"accept_failed", 7:"completed", 8:"completion_failed"}
        logger.debug(f"[obc-emu] TM(1,{subsvc}) {labels.get(subsvc,'?')} t={t:.3f}")

    def _on_s5(self, subsvc: int, pkt: bytes, t: float) -> None:
        """S5 event — detect safe mode entry/exit from event ID."""
        if len(pkt) < 19:
            return
        event_id = struct.unpack(">H", pkt[17:19])[0]
        logger.info(f"[obc-emu] TM(5,{subsvc}) event=0x{event_id:04X} t={t:.3f}")
        # SRDB event IDs for mode transitions (from srdb/data/events.yaml)
        # boot_complete=0x0001, safe_mode_entry=0x0002, safe_mode_exit=0x0003
        if event_id == 0x0002:
            self._mode = MODE_SAFE
        elif event_id == 0x0003:
            self._mode = MODE_NOMINAL