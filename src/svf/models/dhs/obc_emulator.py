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

Implements: SVF-DEV-029, SVF-DEV-034, SVF-DEV-037, SVF-DEV-169
"""

from __future__ import annotations

import logging
import queue
import socket
import struct
import subprocess
import importlib.metadata
import threading
import time
from pathlib import Path
from typing import Optional, Any

try:
    import serial as _pyserial
    _HAS_PYSERIAL = True
except ImportError:
    _pyserial = None
    _HAS_PYSERIAL = False

from svf.core.abstractions import SyncProtocol
from svf.stores.command_store import CommandStore
from svf.core.equipment import PortDefinition, PortDirection
from svf.models.dhs.hil_adapter import HilAdapter
from svf.models.dhs.obc import MODE_NOMINAL, MODE_SAFE
from svf.stores.parameter_store import ParameterStore
from svf.pus.tc import PusTcBuilder
from svf.pus.tm import PusTmPacket, PusTmParser
from svf.pus.services import PusService9

logger = logging.getLogger(__name__)

SYNC_BYTE = 0xFF

_APP_DATA_OFFSET = 17          # bytes: 6 primary + 11 secondary header
_DHS_OBC_HK_SID = 3
_DHS_OBC_HK_FMT = ">BIBBBHB"  # mode, obt, wd, mem, health, reset, cpu
_DHS_OBC_HK_MIN_PKT_LEN = (
    _APP_DATA_OFFSET + 1 + struct.calcsize(_DHS_OBC_HK_FMT) + 2  # +2 CRC
)
MAX_DESYNC = 3

# openobsw FreeRTOS TMTC task queue depth (obsw/task/tmtc.h, capacity 4).
# Exceeding this per-tick causes the OBSW to drop excess TCs silently.
_FREERTOS_TC_QUEUE_DEPTH = 4


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


FRAME_TC = 0x01
FRAME_SENSOR = 0x02
FRAME_ACTUATOR = 0x03
FRAME_TM = 0x04

# obsw_sensor_frame_t: 3f+B + 4f+B + 3f+B + f = 47 bytes (little-endian, packed)
# obsw_actuator_frame_t: 3f + 3f + B + f = 29 bytes (little-endian, packed)
_SENSOR_FMT = "<3fB4fB3fBf"
_SENSOR_LEN = struct.calcsize(_SENSOR_FMT)
_ACTUATOR_FMT = "<6fBf"
_ACTUATOR_LEN = struct.calcsize(_ACTUATOR_FMT)


class OBCEmulatorAdapter(HilAdapter):
    """
    Drop-in replacement for ``ObcStub`` using a real openobsw binary.

    Connects to ``obsw_sim`` (or a Renode ZynqMP emulation) and drives it
    through the SVF wire protocol v3. Each simulation tick:

    1. Packs sensor values from ``ParameterStore`` into ``obsw_sensor_frame_t``
       and sends it as a type-0x02 frame.
    2. Sends any queued TC frames (type-0x01) — at minimum a TC(17,1) heartbeat.
    3. Reads response frames until the 0xFF sync byte, parsing TM packets and
       actuator commands.
    4. Injects actuator values into ``CommandStore`` for downstream equipment.

    **Transport modes:**

    - *Pipe mode* (default): spawns ``obsw_sim`` as a subprocess and
      communicates via ``stdin``/``stdout``.
    - *Socket mode*: connects to a Renode UART terminal over TCP. Set
      ``socket_addr=(host, port)`` and leave ``sim_path=None``.

    **aarch64 support:** If ``sim_path`` points to an AArch64 binary, QEMU
    user-mode emulation is detected automatically and applied transparently.

    Implements: SVF-DEV-029, SVF-DEV-034, SVF-DEV-037
    """

    def __init__(
        self,
        sim_path: Optional[str | Path],
        sync_protocol: SyncProtocol,
        store: ParameterStore,
        command_store: Optional[CommandStore] = None,
        sync_timeout: float = 5.0,
        qemu_prefix: Optional[list[str]] = None,
        socket_addr: Optional[tuple[str, int]] = None,
        serial_port: Optional[str] = None,
        baud_rate: int = 115200,
        apid: int = 0x010,
    ) -> None:
        self._sim_path = Path(sim_path) if sim_path is not None else None
        self._qemu_prefix = qemu_prefix or []
        self._socket_addr = socket_addr
        self._serial_port = serial_port
        self._baud_rate = baud_rate
        self._sock: Optional[socket.socket] = None
        self._serial_dev: Optional[Any] = None
        self._sync_timeout = sync_timeout
        self._apid = apid

        self._obt:    float = 0.0
        self._mode:   int = MODE_SAFE
        self._tm_seq: int = 0
        self._yamcs_bridge: "Optional[Any]" = None  # set externally

        self._obc_watchdog_status: int = 0
        self._obc_memory_used_pct: int = 0
        self._obc_health:          int = 0
        self._obc_reset_count:     int = 0
        self._obc_cpu_load:        int = 0

        # FreeRTOS diagnostic counters (parsed from stderr / UART console)
        self._freertos_stack_overflow_count: int = 0
        self._freertos_iwdg_reset_count:     int = 0

        self._tm_queue:   list[PusTmPacket] = []
        self._tm_lock     = threading.Lock()
        self._tm_parser   = PusTmParser()
        self._consecutive_desync: int = 0

        self._proc:   Optional[subprocess.Popen[bytes]] = None
        self._reader: Optional[threading.Thread] = None
        self._rx_q:   queue.Queue[Optional[bytes]] = queue.Queue()
        self._alive = False

        super().__init__(
            equipment_id="obc",
            sync_protocol=sync_protocol,
            store=store,
            command_store=command_store,
        )
        self._port_values["dhs.obc.mode_cmd"]     = -1.0
        self._port_values["dhs.obc.time_sync_cmd"] = -1.0

    # ------------------------------------------------------------------ #
    # Equipment interface                                                  #
    # ------------------------------------------------------------------ #

    def _declare_ports(self) -> list[PortDefinition]:
        return [
            PortDefinition("obc.tc_input",             PortDirection.IN),
            PortDefinition("dhs.obc.mode_cmd",         PortDirection.IN),
            PortDefinition("dhs.obc.watchdog_kick",    PortDirection.IN),
            PortDefinition("dhs.obc.memory_dump_cmd",  PortDirection.IN),
            PortDefinition("dhs.obc.time_sync_cmd",
                           PortDirection.IN, unit="s"),
            PortDefinition("dhs.obc.mode",             PortDirection.OUT),
            PortDefinition("dhs.obc.obt",
                           PortDirection.OUT, unit="s"),
            PortDefinition("dhs.obc.watchdog_status",  PortDirection.OUT),
            PortDefinition("dhs.obc.memory_used_pct",
                           PortDirection.OUT, unit="%"),
            PortDefinition("dhs.obc.health",           PortDirection.OUT),
            PortDefinition("dhs.obc.reset_count",      PortDirection.OUT),
            PortDefinition("dhs.obc.cpu_load",
                           PortDirection.OUT, unit="%"),
            PortDefinition("obc.tm_output",            PortDirection.OUT),
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
        """Read obsw_sim stderr, parse SRDB version and FreeRTOS diagnostics."""
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
            self._on_obsw_freertos_diagnostic(line)

    def _on_obsw_freertos_diagnostic(self, line: str) -> None:
        """
        Detect FreeRTOS runtime fault messages in a console output line.

        Recognised patterns (from FreeRTOS hooks in openobsw):
          - Stack overflow: ``vApplicationStackOverflowHook`` or
            ``Stack overflow`` (case-insensitive)
          - IWDG reset:     ``IWDG reset`` or ``watchdog reset`` in the
            boot banner (case-insensitive)

        Increments SVF-internal ParameterStore counters:
          ``svf.obc.freertos.stack_overflow_count``
          ``svf.obc.freertos.iwdg_reset_count``

        Implements: SVF-DEV-179
        """
        lower = line.lower()
        if "stackoverflow" in lower or "stack overflow" in lower:
            self._freertos_stack_overflow_count += 1
            logger.critical(
                "[obc-emu][freertos] Stack overflow detected: %s", line.strip()
            )
            if self._store is not None:
                self._store.write(
                    name="svf.obc.freertos.stack_overflow_count",
                    value=float(self._freertos_stack_overflow_count),
                    t=self._obt,
                    model_id=self.equipment_id,
                )
        elif "iwdg reset" in lower or "watchdog reset" in lower:
            self._freertos_iwdg_reset_count += 1
            logger.error(
                "[obc-emu][freertos] IWDG/watchdog reset detected: %s", line.strip()
            )
            if self._store is not None:
                self._store.write(
                    name="svf.obc.freertos.iwdg_reset_count",
                    value=float(self._freertos_iwdg_reset_count),
                    t=self._obt,
                    model_id=self.equipment_id,
                )

    # ------------------------------------------------------------------ #
    # Serial reader (UART mode — MSP430, STM32H750)                       #
    # ------------------------------------------------------------------ #

    def _start_serial_reader(self) -> None:
        """Start background thread reading bytes from UART into _rx_q."""
        self._alive = True
        self._reader = threading.Thread(
            target=self._serial_reader_thread,
            name="obc-emulator-serial-reader",
            daemon=True,
        )
        self._reader.start()

    def _serial_reader_thread(self) -> None:
        dev = self._serial_dev
        if dev is None:
            return
        try:
            while self._alive:
                try:
                    chunk = dev.read(4096)
                except Exception as e:
                    logger.debug(f"[obc-emu] serial read: {e}")
                    break
                if not chunk:
                    continue
                for byte in chunk:
                    self._rx_q.put(bytes([byte]))
        finally:
            self._rx_q.put(None)
            logger.debug("[obc-emu] serial reader exited")

    # ------------------------------------------------------------------ #
    # Socket reader (Renode mode)                                          #
    # ------------------------------------------------------------------ #

    def _start_socket_reader(self) -> None:
        """Start background thread reading bytes from Renode socket into _rx_q."""
        self._alive = True
        self._reader = threading.Thread(
            target=self._socket_reader_thread,
            name="obc-emulator-socket-reader",
            daemon=True,
        )
        self._reader.start()

    def _socket_reader_thread(self) -> None:
        sock = self._sock
        if sock is None:
            return
        try:
            while self._alive:
                try:
                    chunk = sock.recv(4096)
                except Exception as e:
                    logger.debug(f"[obc-emu] socket recv: {e}")
                    break
                if not chunk:
                    break
                for byte in chunk:
                    self._rx_q.put(bytes([byte]))
        finally:
            self._rx_q.put(None)
            logger.debug("[obc-emu] socket reader exited")

    def initialise(self, start_time: float = 0.0) -> None:
        if self._serial_port is not None:
            # Serial mode — connect to hardware UART (MSP430, STM32H750)
            if not _HAS_PYSERIAL:
                raise ImportError(
                    "pyserial is required for UART transport. "
                    "Install with: pip install 'opensvf[uart]'"
                )
            self._serial_dev = _pyserial.Serial(
                port=self._serial_port,
                baudrate=self._baud_rate,
                timeout=0,  # non-blocking reads; reader thread polls
            )
            logger.info(
                f"[obc-emu] Serial mode: {self._serial_port} @ {self._baud_rate} baud"
            )
            self._start_serial_reader()
            return

        if self._socket_addr is not None:
            # Socket mode — connect to Renode UART TCP terminal
            self._sock = socket.create_connection(
                self._socket_addr, timeout=self._sync_timeout
            )
            self._sock.settimeout(None)
            logger.info(
                f"[obc-emu] Socket mode: connected to "
                f"{self._socket_addr[0]}:{self._socket_addr[1]}"
            )
            self._start_socket_reader()
            return

        # Auto-detect QEMU prefix if not explicitly set
        if not self._qemu_prefix and self._sim_path is not None:
            self._qemu_prefix = _detect_qemu_prefix(self._sim_path)

        if self._sim_path is None or not self._sim_path.exists():
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
        _time.sleep(0.1)
        import select as _select
        import os as _os
        if self._proc.stderr:
            for _ in range(5):
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
        if self._serial_dev is not None:
            try:
                self._serial_dev.close()
            except Exception:
                pass
            self._serial_dev = None
        if self._sock is not None:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None
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

        self._send_sensor_frame(t)
        n_tcs = self._send_tcs(t)

        # Each frame sent to the binary produces exactly one 0xFF sync byte.
        # Drain the sensor-frame sync first (primary — governs desync counter),
        # then drain one sync per TC frame so the buffer never accumulates.
        tm_packets, synced = self._collect_until_sync(self._sync_timeout)
        if not synced:
            self._consecutive_desync += 1
            logger.warning(
                f"[obc-emu] No sync at t={t:.3f} "
                f"(missed={self._consecutive_desync})"
            )
            if self._consecutive_desync >= MAX_DESYNC:
                raise RuntimeError(
                    f"Lost sync: {self._consecutive_desync} consecutive "
                    "ticks without 0xFF"
                )
        else:
            self._consecutive_desync = 0

        for _ in range(n_tcs):
            extra, _ = self._collect_until_sync(timeout=1.0)
            tm_packets.extend(extra)

        for pkt in tm_packets:
            self._parse_tm(pkt, t)

        self.write_port("dhs.obc.mode",            float(self._mode))
        self.write_port("dhs.obc.obt",             self._obt)
        self.write_port("dhs.obc.watchdog_status", float(self._obc_watchdog_status))
        self.write_port("dhs.obc.memory_used_pct", float(self._obc_memory_used_pct))
        self.write_port("dhs.obc.health",          float(self._obc_health))
        self.write_port("dhs.obc.reset_count",     float(self._obc_reset_count))
        self.write_port("dhs.obc.cpu_load",        float(self._obc_cpu_load))
        self.write_port("obc.tm_output",           float(self._tm_seq))

    # ------------------------------------------------------------------ #
    # Sensor frame (type 0x02)                                            #
    # ------------------------------------------------------------------ #

    def _send_sensor_frame(self, t: float) -> None:
        """
        Pack ``obsw_sensor_frame_t`` from ``ParameterStore`` and send to OBSW.

        Reads MAG, ST, and GYRO values from ``ParameterStore``. Status ports
        are thresholded at 0.5 to produce the ``uint8_t valid`` flags in the
        C struct. The packed frame is sent as a type-0x02 typed frame.

        Frame layout (47 bytes, little-endian, ``#pragma pack(1)``)::

            float mag_x, mag_y, mag_z;   uint8_t mag_valid;
            float st_q_w, x, y, z;       uint8_t st_valid;
            float gyro_x, y, z;          uint8_t gyro_valid;
            float sim_time;
        """
        def _read(key: str, default: float = 0.0) -> float:
            e = self._store.read(key)
            return e.value if e is not None else default

        mag_x = _read("aocs.mag.field_x")
        mag_y = _read("aocs.mag.field_y")
        mag_z = _read("aocs.mag.field_z")
        mag_status = self._store.read("aocs.mag.status")
        mag_valid = 1 if mag_status is not None and mag_status.value > 0.5 else 0

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

    def _send_tcs(self, t: float) -> int:
        """Send queued TC frames to the binary. Returns the number of frames sent."""
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

        time_sync = self.read_port("dhs.obc.time_sync_cmd")
        if time_sync >= 0.0:
            frames.append(self._build_s9_set_obt(time_sync))
            self._port_values["dhs.obc.time_sync_cmd"] = -1.0

        # FreeRTOS TMTC task queue depth is 4 (obsw/task/tmtc.h).
        # Excess TCs are dropped silently by the OBSW — warn before sending.
        if len(frames) > _FREERTOS_TC_QUEUE_DEPTH:
            logger.warning(
                "[obc-emu] TC burst %d exceeds FreeRTOS queue depth %d at t=%.3f"
                " — OBSW may drop %d frame(s)",
                len(frames),
                _FREERTOS_TC_QUEUE_DEPTH,
                t,
                len(frames) - _FREERTOS_TC_QUEUE_DEPTH,
            )

        for frame in frames:
            self._write_typed_frame(FRAME_TC, frame)
        return len(frames)

    def _build_s9_set_obt(self, obt_seconds: float) -> bytes:
        tc = PusService9.build_set_obt(obt_seconds, tc_apid=self._apid)
        return PusTcBuilder().build(tc)

    def _build_s17_ping(self) -> bytes:
        # PUS-A TC(17,1): primary [type=TC, sec_hdr=1, APID] + secondary [0x11, svc, subsvc, src_id]
        # Length field = secondary_size - 1 = (1+1+1+2) - 1 = 4
        apid_word = 0x1800 | (self._apid & 0x7FF)
        return struct.pack(">HHHBBBH", apid_word, 0xC000, 0x0004, 0x11, 17, 1, 0)

    def _build_s8_recover_nominal(self) -> bytes:
        user_data = bytes([0x00, 0x01, 0x00])
        data_len = 3 + len(user_data) - 1
        hdr = struct.pack(">HHHBBB",
                          0x1801, 0xC000, data_len, 0x20, 8, 1,
                          )
        return hdr + user_data

    def _write_typed_frame(self, frame_type: int, frame: bytes) -> None:
        """Send [type_byte][uint16 BE length][frame bytes] to obsw_sim."""
        payload = (
            bytes([frame_type]) +
            struct.pack(">H", len(frame)) +
            frame
        )
        if self._serial_dev is not None:
            try:
                self._serial_dev.write(payload)
            except Exception as e:
                logger.error(f"[obc-emu] serial write failed: {e}")
        elif self._sock is not None:
            try:
                self._sock.sendall(payload)
            except Exception as e:
                logger.error(f"[obc-emu] socket write failed: {e}")
        elif self._proc is not None and self._proc.stdin is not None:
            try:
                self._proc.stdin.write(payload)
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

        self._command_store.inject("aocs.mtq.dipole_x", mtq_x,
                                   t=sim_time, source_id="obc-emu")
        self._command_store.inject("aocs.mtq.dipole_y", mtq_y,
                                   t=sim_time, source_id="obc-emu")
        self._command_store.inject("aocs.mtq.dipole_z", mtq_z,
                                   t=sim_time, source_id="obc-emu")
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
        Read type-prefixed frames from the OBSW until the 0xFF sync byte.

        Called once per tick after sending the sensor and TC frames. Parses:

        - Type 0x03 — actuator frame: injected into ``CommandStore``
        - Type 0x04 — PUS TM packet: recorded in ``ParameterStore`` and
          passed to ``_parse_tm()``

        Args:
            timeout: Maximum wall-clock seconds to wait for the sync byte.

        Returns:
            Tuple of (list of raw TM packet bytes, synced: bool).
            ``synced`` is False if the timeout expired before seeing 0xFF.
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
        svc = pkt[7]
        subsvc = pkt[8]
        self._tm_seq += 1
        if self._store is not None:
            self._store.write(
                name=f"svf.tm.{svc}.{subsvc}.received",
                value=float(self._tm_seq),
                t=t,
                model_id=self.equipment_id,
            )
        # Forward raw TM to YAMCS if bridge is attached
        if self._yamcs_bridge is not None:
            try:
                self._yamcs_bridge.send_tm(pkt)
            except Exception:
                pass

        # Queue for campaign procedures (Gap 1)
        try:
            parsed = self._tm_parser.parse(pkt)
            with self._tm_lock:
                self._tm_queue.append(parsed)
        except Exception:
            pass

        if svc == 1:
            self._on_s1(subsvc, pkt, t)
        elif svc == 3 and subsvc == 25:
            self._on_s3_25(pkt, t)
        elif svc == 5:
            self._on_s5(subsvc, pkt, t)
        elif svc == 17 and subsvc == 2:
            logger.info(f"[obc-emu] TM(17,2) pong t={t:.3f}")

    def _on_s1(self, subsvc: int, pkt: bytes, t: float) -> None:
        labels = {1: "accepted", 2: "accept_failed",
                  7: "completed", 8: "completion_failed"}
        logger.debug(
            f"[obc-emu] TM(1,{subsvc}) {labels.get(subsvc, '?')} t={t:.3f}")

    def _on_s5(self, subsvc: int, pkt: bytes, t: float) -> None:
        if len(pkt) < 19:
            return
        event_id = struct.unpack(">H", pkt[17:19])[0]
        logger.info(
            f"[obc-emu] TM(5,{subsvc}) event=0x{event_id:04X} t={t:.3f}")
        if event_id == 0x0002:
            self._mode = MODE_SAFE
        elif event_id == 0x0003:
            self._mode = MODE_NOMINAL

    def _on_s3_25(self, pkt: bytes, t: float) -> None:
        """Parse TM(3,25) DHS OBC HK set_id=3 and update instance state."""
        if len(pkt) < _DHS_OBC_HK_MIN_PKT_LEN:
            return
        app = pkt[_APP_DATA_OFFSET:]
        if app[0] != _DHS_OBC_HK_SID:
            return
        mode, obt, wd, mem, health, reset, cpu = struct.unpack_from(
            _DHS_OBC_HK_FMT, app, 1
        )
        self._mode                 = mode
        self._obc_watchdog_status  = wd
        self._obc_memory_used_pct  = mem
        self._obc_health           = health
        self._obc_reset_count      = reset
        self._obc_cpu_load         = cpu
        if self._store is not None:
            for name, val in (
                ("obc_mode",            mode),
                ("obc_obt",             obt),
                ("obc_watchdog_status", wd),
                ("obc_memory_used_pct", mem),
                ("obc_health",          health),
                ("obc_reset_count",     reset),
                ("obc_cpu_load",        cpu),
            ):
                self._store.write(
                    name=name, value=float(val),
                    t=t, model_id=self.equipment_id,
                )
        logger.debug(
            f"[obc-emu] TM(3,25) mode={mode} obt={obt} wd={wd} "
            f"mem={mem}% health={health} reset={reset} cpu={cpu}%"
        )

    # ── HilAdapter interface ──────────────────────────────────────────────────

    def connect(self) -> None:
        """Connection is established in initialise() — no-op here."""

    def disconnect(self) -> None:
        """Disconnection is handled in teardown() — no-op here."""

    def is_connected(self) -> bool:
        """Return True if the subprocess, socket, or serial port is alive."""
        if self._serial_dev is not None:
            return bool(self._serial_dev.is_open)
        if self._sock is not None:
            return True
        return self._proc is not None and self._proc.poll() is None

    def receive_tc(self, raw_tc: bytes, t: float = 0.0) -> list[PusTmPacket]:
        self._write_typed_frame(FRAME_TC, raw_tc)
        # Drain pending sync blocks so TM from this TC reaches YAMCS on this tick,
        # not 2 ticks later.  Short timeout: binary responds in microseconds.
        for _ in range(3):
            tm_packets, synced = self._collect_until_sync(timeout=0.3)
            for pkt in tm_packets:
                self._parse_tm(pkt, t)
            if not synced:
                break
        return []

    def get_tm_queue(self) -> list[PusTmPacket]:
        with self._tm_lock:
            packets = list(self._tm_queue)
            self._tm_queue.clear()
            return packets

    def get_tm_by_service(self, service: int, subservice: int) -> list[PusTmPacket]:
        with self._tm_lock:
            return [
                p for p in self._tm_queue
                if p.service == service and p.subservice == subservice
            ]
