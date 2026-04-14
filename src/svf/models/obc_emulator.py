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
import importlib.metadata
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
def _detect_qemu_prefix(sim_path: Path) -> list[str]:
    """
    Auto-detect if sim_path needs QEMU to run on this host.
    Returns [] for native binaries, ['qemu-aarch64', '-L', glibc] for aarch64.
    """
    import shutil
    import subprocess

    try:
        result = subprocess.run(
            ["file", str(sim_path)],
            capture_output=True, text=True, timeout=5
        )
        output = result.stdout
    except Exception:
        return []

    if "ARM aarch64" in output:
        qemu = shutil.which("qemu-aarch64")
        if not qemu:
            raise RuntimeError(
                f"aarch64 binary detected but qemu-aarch64 not found. "
                f"Install with: nix-env -iA nixpkgs.qemu"
            )
        # Find glibc from environment or search
        import os
        glibc = os.environ.get("AARCH64_GLIBC", "")
        if not glibc:
            import re
            match = re.search(r"interpreter (/nix/store/[^/]+)", output)
            if match:
                glibc = str(Path(match.group(1)).parent.parent)
        if not glibc:
            raise RuntimeError(
                "aarch64 glibc not found. Set AARCH64_GLIBC environment variable."
            )
        logger.info(f"[obc-emu] aarch64 binary detected — using QEMU: {qemu}")
        return [qemu, "-L", glibc]

    return []


FRAME_TC        = 0x01
FRAME_SENSOR    = 0x02
FRAME_ACTUATOR  = 0x03
FRAME_TM        = 0x04

# obsw_sensor_frame_t: 3f+B + 4f+B + 3f+B + f = 47 bytes (little-endian, packed)
# obsw_actuator_frame_t: 3f + 3f + B + f = 29 bytes (little-endian, packed)
_SENSOR_FMT   = "<3fB4fB3fBf"
_SENSOR_LEN   = struct.calcsize(_SENSOR_FMT)
_ACTUATOR_FMT = "<6fBf"
_ACTUATOR_LEN = struct.calcsize(_ACTUATOR_FMT)


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
        qemu_prefix: Optional[list[str]] = None,
        apid: int = 0x010,
    ) -> None:
        self._sim_path     = Path(sim_path)
        self._qemu_prefix  = qemu_prefix or []
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


    def _check_srdb_version(self, srdb_version: str) -> None:
        """Compare obsw_sim SRDB version against installed obsw-srdb package."""
        try:
            pkg_version = importlib.metadata.version("obsw-srdb")
        except importlib.metadata.PackageNotFoundError:
            logger.warning(
                "[obc-emu] obsw-srdb package not installed — "
                "cannot verify SRDB version handshake"
            )
            return

        if srdb_version != pkg_version:
            logger.warning(
                f"[obc-emu] SRDB VERSION MISMATCH: "
                f"obsw_sim={srdb_version} vs opensvf={pkg_version} — "
                f"parameter names may be inconsistent"
            )
        else:
            logger.info(
                f"[obc-emu] SRDB version handshake OK: {srdb_version}"
            )

    def _stderr_reader(self) -> None:
        """Read obsw_sim stderr, parse SRDB version, forward to logger."""
        proc = self._proc
        if proc is None or proc.stderr is None:
            return
        while True:
            raw = proc.stderr.readline()
            if not raw:
                break
            line = raw.decode(errors="replace").rstrip()
            logger.debug(f"[obsw] {line}")
            if "SRDB version:" in line:
                srdb_version = line.split("SRDB version:")[-1].strip()
                self._check_srdb_version(srdb_version)

    def initialise(self, start_time: float = 0.0) -> None:
        # Auto-detect QEMU prefix if not explicitly set
        if not self._qemu_prefix:
            self._qemu_prefix = _detect_qemu_prefix(self._sim_path)

        if not self._sim_path.exists():
            raise FileNotFoundError(
                f"obsw_sim not found at {self._sim_path}."
            )
        self._proc = subprocess.Popen(
            self._qemu_prefix + [str(self._sim_path)],
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

        # Read startup lines synchronously — version handshake
        import time as _time
        _time.sleep(0.1)  # give obsw_sim time to write startup lines
        import select as _select, os as _os
        if self._proc.stderr:
            for _ in range(5):  # read up to 5 startup lines
                ready = _select.select([self._proc.stderr], [], [], 0.2)
                if not ready[0]:
                    break
                raw = _os.read(self._proc.stderr.fileno(), 256)
                if not raw:
                    break
                for line in raw.decode(errors="replace").splitlines():
                    logger.debug(f"[obsw] {line}")
                    if "SRDB version:" in line:
                        srdb_version = line.split("SRDB version:")[-1].strip()
                        self._check_srdb_version(srdb_version)

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

    def _parse_actuator(self, body: bytes) -> None:
        """Parse type-0x03 actuator frame and inject into ParameterStore."""
        if len(body) < _ACTUATOR_LEN:
            logger.warning(f"[obc-emu] Actuator frame too short: {len(body)}")
            return
        (mtq_x, mtq_y, mtq_z,
         rw_x,  rw_y,  rw_z,
         controller, sim_time) = struct.unpack_from(_ACTUATOR_FMT, body)

        if self._command_store is None:
            return

        # Inject MTQ dipole commands (b-dot output) into CommandStore
        # so wiring picks them up → MTQ.read_port() → torque = m×B
        self._command_store.inject("aocs.mtq.dipole_x", mtq_x,
                                   t=sim_time, source_id="obc-emu")
        self._command_store.inject("aocs.mtq.dipole_y", mtq_y,
                                   t=sim_time, source_id="obc-emu")
        self._command_store.inject("aocs.mtq.dipole_z", mtq_z,
                                   t=sim_time, source_id="obc-emu")

        # Inject RW torque commands (ADCS output) into CommandStore
        self._command_store.inject("aocs.rw1.torque_cmd", rw_x,
                                   t=sim_time, source_id="obc-emu")
        self._command_store.inject("aocs.rw2.torque_cmd", rw_y,
                                   t=sim_time, source_id="obc-emu")
        self._command_store.inject("aocs.rw3.torque_cmd", rw_z,
                                   t=sim_time, source_id="obc-emu")

        ctrl_name = "bdot" if controller == 0 else "adcs"
        logger.debug(
            f"[obc-emu] actuator [{ctrl_name}] "
            f"mtq=[{mtq_x:.3e},{mtq_y:.3e},{mtq_z:.3e}] "
            f"rw=[{rw_x:.3e},{rw_y:.3e},{rw_z:.3e}]"
        )

    def _collect_until_sync(
        self, timeout: float
    ) -> tuple[list[bytes], bool]:
        """
        Read type-prefixed frames until 0xFF sync byte.

        Protocol v3 stdout:
          [0x04][uint16 BE len][TM bytes]       — PUS TM packet
          [0x03][uint16 BE len][actuator bytes] — actuator frame
          [0xFF]                                — end of tick
        """
        packets: list[bytes] = []
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return packets, False

            frame_type = self._read_byte(remaining)
            if frame_type is None:
                return packets, False
            if frame_type == SYNC_BYTE:
                return packets, True

            # Read 2-byte BE length
            b1 = self._read_byte(deadline - time.monotonic())
            b2 = self._read_byte(deadline - time.monotonic())
            if b1 is None or b2 is None:
                return packets, False
            length = (b1 << 8) | b2

            if length == 0 or length > 4096:
                logger.warning(
                    f"[obc-emu] Bad length {length} type=0x{frame_type:02X}"
                )
                continue

            body = bytearray()
            while len(body) < length:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return packets, False
                b = self._read_byte(remaining)
                if b is None:
                    return packets, False
                body.append(b)

            if frame_type == FRAME_TM:
                packets.append(bytes(body))
            elif frame_type == FRAME_ACTUATOR:
                self._parse_actuator(bytes(body))
            else:
                logger.warning(
                    f"[obc-emu] Unknown frame type 0x{frame_type:02X}"
                )
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
