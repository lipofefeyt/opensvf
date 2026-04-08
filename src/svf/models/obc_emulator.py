"""
OBC Emulator Adapter
Drop-in replacement for ObcStub using the openobsw host sim (obsw_sim).

Extended pipe protocol with type-prefixed frames:
  Type 0x01 — TC uplink:       [0x01][uint16 BE length][TC frame bytes]
  Type 0x02 — Sensor injection: [0x02][uint16 BE length][obsw_sensor_frame_t]

obsw_sensor_frame_t (packed, little-endian floats):
  float mag_x, mag_y, mag_z; uint8_t mag_valid;
  float st_q_w, st_q_x, st_q_y, st_q_z; uint8_t st_valid;
  float gyro_x, gyro_y, gyro_z; uint8_t gyro_valid;
  float sim_time;

obsw_sim stdout (unchanged):
  [uint16 BE length][TM packet bytes] ... [0xFF sync]

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
from svf.pus.tm import PusTmPacket

logger = logging.getLogger(__name__)

SYNC_BYTE       = 0xFF
FRAME_TC        = 0x01
FRAME_SENSOR    = 0x02

# obsw_sensor_frame_t: 3f+B + 4f+B + 3f+B + f = 47 bytes (little-endian, packed)
_SENSOR_FMT = "<3fB4fB3fBf"
_SENSOR_LEN = struct.calcsize(_SENSOR_FMT)


class OBCEmulatorAdapter(Equipment):
    """
    OBC Emulator Adapter — wraps obsw_sim as an Equipment.

    Each SVF tick:
      1. Read sensor values from ParameterStore
      2. Send type-0x02 sensor frame to obsw_sim
      3. Send type-0x01 TC frames (heartbeat ping or queued TCs)
      4. Wait for 0xFF sync byte
      5. Parse TM packets → update OUT ports
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
        self._sim_path     = Path(sim_path)
        self._sync_timeout = sync_timeout
        self._apid         = apid

        self._obt:    float = 0.0
        self._mode:   int   = MODE_SAFE
        self._tm_seq: int   = 0

        self._proc:   Optional[subprocess.Popen[bytes]] = None
        self._reader: Optional[threading.Thread]        = None
        self._rx_q:   queue.Queue[Optional[bytes]]      = queue.Queue()
        self._alive   = False

        super().__init__(
            equipment_id="obc",
            sync_protocol=sync_protocol,
            store=store,
            command_store=command_store,
        )
        self._port_values["dhs.obc.mode_cmd"] = -1.0

    # ------------------------------------------------------------------ #
    # Equipment interface                                                  #
    # ------------------------------------------------------------------ #

    def _declare_ports(self) -> list[PortDefinition]:
        return [
            PortDefinition("obc.tc_input",            PortDirection.IN),
            PortDefinition("dhs.obc.mode_cmd",        PortDirection.IN),
            PortDefinition("dhs.obc.watchdog_kick",   PortDirection.IN),
            PortDefinition("dhs.obc.memory_dump_cmd", PortDirection.IN),
            PortDefinition("dhs.obc.mode",            PortDirection.OUT),
            PortDefinition("dhs.obc.obt",             PortDirection.OUT, unit="s"),
            PortDefinition("dhs.obc.watchdog_status", PortDirection.OUT),
            PortDefinition("dhs.obc.memory_used_pct", PortDirection.OUT, unit="%"),
            PortDefinition("dhs.obc.health",          PortDirection.OUT),
            PortDefinition("dhs.obc.reset_count",     PortDirection.OUT),
            PortDefinition("dhs.obc.cpu_load",        PortDirection.OUT, unit="%"),
            PortDefinition("obc.tm_output",           PortDirection.OUT),
        ]

    def initialise(self, start_time: float = 0.0) -> None:
        if not self._sim_path.exists():
            raise FileNotFoundError(
                f"obsw_sim not found at {self._sim_path}."
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
        logger.info(f"[obc-emu] obsw_sim PID={self._proc.pid}")

    def teardown(self) -> None:
        self._alive = False
        if self._proc is not None:
            try:
                if self._proc.stdin is not None:
                    self._proc.stdin.close()
            except Exception:
                pass
            try:
                self._proc.terminate()
                self._proc.wait(timeout=2.0)
            except Exception:
                self._proc.kill()
            self._proc = None
        self._rx_q.put(None)
        if self._reader is not None:
            self._reader.join(timeout=2.0)
            self._reader = None
        logger.info("[obc-emu] Terminated")

    def do_step(self, t: float, dt: float) -> None:
        self._obt += dt

        # Send sensor frame first (AOCS needs fresh data each cycle)
        self._send_sensor_frame(t)

        # Send TC frames (heartbeat + any queued TCs)
        self._send_tcs(t)

        tm_packets, synced = self._collect_until_sync(self._sync_timeout)
        if not synced:
            logger.warning(f"[obc-emu] No sync at t={t:.3f}")

        for pkt in tm_packets:
            self._parse_tm(pkt, t)

        self.write_port("dhs.obc.mode",           float(self._mode))
        self.write_port("dhs.obc.obt",            self._obt)
        self.write_port("dhs.obc.watchdog_status", 0.0)
        self.write_port("dhs.obc.memory_used_pct", 0.0)
        self.write_port("dhs.obc.health",          0.0)
        self.write_port("dhs.obc.reset_count",     0.0)
        self.write_port("dhs.obc.cpu_load",        0.0)
        self.write_port("obc.tm_output",           float(self._tm_seq))

    # ------------------------------------------------------------------ #
    # Sensor frame (type 0x02)                                            #
    # ------------------------------------------------------------------ #

    def _send_sensor_frame(self, t: float) -> None:
        """Pack obsw_sensor_frame_t from ParameterStore and send to obsw_sim."""
        def _read(key: str, default: float = 0.0) -> float:
            e = self._store.read(key)
            return e.value if e is not None else default

        mag_x = _read("aocs.mag.field_x")
        mag_y = _read("aocs.mag.field_y")
        mag_z = _read("aocs.mag.field_z")
        mag_valid = 1 if self._store.read("aocs.mag.status") is not None and \
            (self._store.read("aocs.mag.status").value or 0) > 0.5 else 0  # type: ignore[union-attr]

        st_w = _read("aocs.str1.quaternion_w", 1.0)
        st_x = _read("aocs.str1.quaternion_x")
        st_y = _read("aocs.str1.quaternion_y")
        st_z = _read("aocs.str1.quaternion_z")
        st_valid_entry = self._store.read("aocs.str1.validity")
        st_valid = 1 if st_valid_entry is not None and st_valid_entry.value > 0.5 else 0

        gyro_x = _read("aocs.gyro.rate_x")
        gyro_y = _read("aocs.gyro.rate_y")
        gyro_z = _read("aocs.gyro.rate_z")
        gyro_status = self._store.read("aocs.gyro.status")
        gyro_valid = 1 if gyro_status is not None and gyro_status.value > 0.5 else 0

        frame = struct.pack(
            _SENSOR_FMT,
            mag_x, mag_y, mag_z, mag_valid,
            st_w, st_x, st_y, st_z, st_valid,
            gyro_x, gyro_y, gyro_z, gyro_valid,
            float(t),
        )
        self._write_typed_frame(FRAME_SENSOR, frame)

    # ------------------------------------------------------------------ #
    # TC building (type 0x01)                                             #
    # ------------------------------------------------------------------ #

    def _send_tcs(self, t: float) -> None:
        frames: list[bytes] = []

        mode_cmd = self.read_port("dhs.obc.mode_cmd")
        if mode_cmd >= 0.0:
            if int(round(mode_cmd)) == MODE_NOMINAL:
                frames.append(self._build_s8_recover_nominal())
            self._port_values["dhs.obc.mode_cmd"] = -1.0

        wdg_kick = self.read_port("dhs.obc.watchdog_kick")
        if wdg_kick > 0.5:
            frames.append(self._build_s17_ping())
            self._port_values["dhs.obc.watchdog_kick"] = 0.0

        if not frames:
            frames.append(self._build_s17_ping())

        for frame in frames:
            self._write_typed_frame(FRAME_TC, frame)

    def _build_s17_ping(self) -> bytes:
        return bytes.fromhex("1801c0000003201101" + "00")

    def _build_s8_recover_nominal(self) -> bytes:
        user_data = bytes([0x00, 0x01, 0x00])
        data_len  = 3 + len(user_data) - 1
        hdr = struct.pack(">HHHBBB",
            0x1801, 0xC000, data_len, 0x20, 8, 1,
        )
        return hdr + user_data

    def _write_typed_frame(self, frame_type: int, frame: bytes) -> None:
        """Send [type_byte][uint16 BE length][frame bytes] to obsw_sim stdin."""
        if self._proc is None or self._proc.stdin is None:
            return
        try:
            self._proc.stdin.write(
                bytes([frame_type]) +
                struct.pack(">H", len(frame)) +
                frame
            )
            self._proc.stdin.flush()
        except Exception as e:
            logger.error(f"[obc-emu] stdin write failed: {e}")

    # ------------------------------------------------------------------ #
    # Stdout reader                                                        #
    # ------------------------------------------------------------------ #

    def _stdout_reader(self) -> None:
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
            logger.info(f"[obc-emu] TM(17,2) pong t={t:.3f}")

    def _on_s1(self, subsvc: int, pkt: bytes, t: float) -> None:
        labels = {1: "accepted", 2: "accept_failed",
                  7: "completed", 8: "completion_failed"}
        logger.debug(f"[obc-emu] TM(1,{subsvc}) {labels.get(subsvc,'?')} t={t:.3f}")

    def _on_s5(self, subsvc: int, pkt: bytes, t: float) -> None:
        if len(pkt) < 19:
            return
        event_id = struct.unpack(">H", pkt[17:19])[0]
        logger.info(f"[obc-emu] TM(5,{subsvc}) event=0x{event_id:04X} t={t:.3f}")
        if event_id == 0x0002:
            self._mode = MODE_SAFE
        elif event_id == 0x0003:
            self._mode = MODE_NOMINAL

    # ------------------------------------------------------------------ #
    # ObcInterface compatibility                                           #
    # ------------------------------------------------------------------ #

    def receive_tc(self, raw_tc: bytes, t: float = 0.0) -> list[PusTmPacket]:
        self._write_typed_frame(FRAME_TC, raw_tc)
        return []

    def get_tm_queue(self) -> list[PusTmPacket]:
        return []

    def get_tm_by_service(self, service: int, subservice: int) -> list[PusTmPacket]:
        return []
