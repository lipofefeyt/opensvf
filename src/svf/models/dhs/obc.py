"""
SVF OBC Equipment
On-Board Computer model  -  PUS TC router + DHS behaviour.

M7: PUS TC parsing, S1/S3/S5/S17/S20 service routing
M8: Mode state machine, OBT, watchdog, memory, CPU load
M52: S6 Memory Management (simulated RAM shadow), S8 Function Management
     (mission-configurable function_id -> mode transition)
M51: S15 On-Board Storage & Retrieval (packet stores), S23 File Management
     (virtual file table)

Implements: PUS-010, 1553-010, SVF-DEV-038, SVF-DEV-188 through SVF-DEV-191
"""

from __future__ import annotations

import logging
import math
import struct
import threading
from dataclasses import dataclass, field
from typing import Optional

from svf.core.abstractions import SyncProtocol
from svf.stores.command_store import CommandStore
from svf.core.equipment import PortDefinition, PortDirection
from svf.models.dhs.hil_adapter import HilAdapter
from svf.stores.parameter_store import ParameterStore
from svf.pus.tc import PusTcPacket, PusTcParser, PusTcError
from svf.pus.tm import PusTmPacket, PusTmBuilder
from svf.pus.services import (
    PusService1, PusService3, PusService5, PusService6, PusService8,
    PusService9, PusService11, PusService12, PusService15, PusService17,
    PusService19, PusService20, PusService23,
    TimeBasedScheduler, OnBoardMonitor, EventActionService, EventActionDefinition,
    HkReportDefinition, EventSeverity,
)

logger = logging.getLogger(__name__)

# OBC mode constants. 0-2 are openobsw's SRDB obc_mode enumeration, which
# owns the encoding (dhs_obc_hk.mode, SRDB_ENUM_OBC_MODE_*). PAYLOAD is an
# opensvf-only extension of the Python OBC model.
MODE_STANDBY = 0
MODE_SAFE    = 1
MODE_NOMINAL = 2
MODE_PAYLOAD = 3

# Watchdog status constants
WDG_NOMINAL  = 0
WDG_WARNING  = 1
WDG_RESET    = 2

# OBC health constants
HEALTH_NOMINAL  = 0
HEALTH_DEGRADED = 1
HEALTH_FAILED   = 2

# Default watchdog period in seconds
DEFAULT_WDG_PERIOD_S = 30.0

# Memory fill rate per second (% of total)
MEMORY_FILL_RATE_PCT_S = 0.01

# Simulated OBC RAM shadow for S6 Memory Management (load/check/dump).
# A fixed-size byte buffer standing in for real process memory  -  ObcEquipment
# is a pure-Python model with no real address space to patch.
S6_SIMULATED_MEMORY_SIZE = 4096


@dataclass
class PacketStore:
    """S15 packet store: enabled flag + buffered (obt, packet) history."""
    enabled: bool = False
    packets: list[tuple[float, PusTmPacket]] = field(default_factory=list)


@dataclass
class ObcConfig:
    """
    OBC configuration.

    Attributes:
        apid:              OBC APID for generated TM packets
        param_id_map:      Maps PUS parameter_id -> SRDB canonical name
        essential_hk:      HK report definitions activated at boot
        watchdog_period_s: Watchdog timeout period in seconds
        initial_mode:      Initial OBC mode (default: SAFE)
        function_mode_map: Maps a S8 TC(8,1) function_id -> target OBC mode.
                            Function IDs are mission/OBSW-specific; this lets
                            a mission wire e.g. openobsw's function IDs
                            (1=recover nominal, 2=request safe) onto this
                            model's mode transitions for HIL-parity testing.
    """
    apid: int = 0x101
    param_id_map: dict[int, str] = field(default_factory=dict)
    essential_hk: list[HkReportDefinition] = field(default_factory=list)
    watchdog_period_s: float = DEFAULT_WDG_PERIOD_S
    initial_mode: int = MODE_SAFE
    function_mode_map: dict[int, int] = field(default_factory=dict)


class ObcEquipment(HilAdapter):
    """
    On-Board Computer Equipment.

    M7 capabilities:
    - PUS TC parsing and routing (S1, S3, S5, S17, S20)
    - TM generation and queuing
    - Essential HK auto-activated at boot

    M8 additions:
    - Mode state machine: SAFE -> NOMINAL -> PAYLOAD
    - On-board time (OBT): monotonic seconds counter
    - Watchdog timer: resets if not kicked within period
    - Mass memory fill simulation
    - CPU load simulation
    - Full DHS SRDB port set
    """

    def __init__(
        self,
        config: ObcConfig,
        sync_protocol: SyncProtocol,
        store: ParameterStore,
        command_store: Optional[CommandStore] = None,
    ) -> None:
        self._config = config
        self._parser = PusTcParser()
        self._tm_builder = PusTmBuilder()
        self._s3 = PusService3()
        self._s11 = TimeBasedScheduler()
        self._s12 = OnBoardMonitor()
        self._s19 = EventActionService()
        self._pending_reactions: list[bytes] = []
        self._tm_queue: list[PusTmPacket] = []
        self._tm_seq: int = 0
        self._lock = threading.Lock()

        # DHS state
        self._mode: int = config.initial_mode
        self._obt: float = 0.0
        self._wdg_last_kick: float = 0.0
        self._wdg_status: int = WDG_NOMINAL
        self._memory_used_pct: float = 0.0
        self._cpu_load: float = 15.0  # nominal baseline
        self._reset_count: int = 0
        self._health: int = HEALTH_NOMINAL
        self._memory: bytearray = bytearray(S6_SIMULATED_MEMORY_SIZE)
        self._packet_stores: dict[int, PacketStore] = {}
        self._packet_store_feed_suppressed: bool = False
        self._files: dict[str, int] = {}  # S23 virtual file table: name -> size

        # Register essential HK reports
        for defn in config.essential_hk:
            self._s3.add_essential(defn)

        super().__init__(
            equipment_id="obc",
            sync_protocol=sync_protocol,
            store=store,
            command_store=command_store,
        )

        # Idle sentinels for command ports
        self._port_values["dhs.obc.mode_cmd"]     = -1.0
        self._port_values["dhs.obc.time_sync_cmd"] = -1.0

    def _declare_ports(self) -> list[PortDefinition]:
        return [
            # TC input from TTC
            PortDefinition("obc.tc_input", PortDirection.IN,
                           description="TC arrival signal"),
            # DHS TC inputs
            PortDefinition("dhs.obc.mode_cmd", PortDirection.IN,
                           description="Mode transition command"),
            PortDefinition("dhs.obc.watchdog_kick", PortDirection.IN,
                           description="Watchdog kick (write 1)"),
            PortDefinition("dhs.obc.memory_dump_cmd", PortDirection.IN,
                           description="Memory dump command"),
            PortDefinition("dhs.obc.time_sync_cmd", PortDirection.IN,
                           unit="s", description="OBT sync: write target OBT seconds (-1 = idle)"),
            # DHS TM outputs
            PortDefinition("dhs.obc.mode", PortDirection.OUT,
                           description="Current OBC mode"),
            PortDefinition("dhs.obc.obt", PortDirection.OUT,
                           unit="s", description="On-board time"),
            PortDefinition("dhs.obc.watchdog_status", PortDirection.OUT,
                           description="Watchdog status"),
            PortDefinition("dhs.obc.memory_used_pct", PortDirection.OUT,
                           unit="%", description="Mass memory used"),
            PortDefinition("dhs.obc.health", PortDirection.OUT,
                           description="OBC health status"),
            PortDefinition("dhs.obc.reset_count", PortDirection.OUT,
                           description="Reset counter"),
            PortDefinition("dhs.obc.cpu_load", PortDirection.OUT,
                           unit="%", description="CPU load"),
            # TM output signal
            PortDefinition("obc.tm_output", PortDirection.OUT,
                           description="Latest TM sequence count"),
        ]

    def initialise(self, start_time: float = 0.0) -> None:
        self._obt = start_time
        self._wdg_last_kick = start_time
        logger.info(
            f"[obc] Initialised: APID=0x{self._config.apid:03X}, "
            f"mode={self._mode}, "
            f"{len(self._config.param_id_map)} param mappings, "
            f"{len(self._config.essential_hk)} essential HK reports"
        )

    def do_step(self, t: float, dt: float) -> None:
        """Advance OBC by one tick  -  DHS state + PUS routing."""
        # ── S19 reactions deferred from previous tick ─────────────────
        pending, self._pending_reactions = self._pending_reactions, []
        for tc_bytes in pending:
            self.receive_tc(tc_bytes, t)

        # ── On-board time ──────────────────────────────────────────────
        self._obt += dt

        # ── OBT sync (port-based, for test procedures / stub mode) ─────
        time_sync = self.read_port("dhs.obc.time_sync_cmd")
        if time_sync >= 0.0:
            self._obt = time_sync
            self.receive("dhs.obc.time_sync_cmd", -1.0)
            logger.info(f"[obc] OBT sync: set to {time_sync:.3f}s at t={t:.1f}s")

        # ── S11 time-based schedule: fire due activities ───────────────
        for tc_bytes in self._s11.due(self._obt):
            self.receive_tc(tc_bytes, t)

        # ── S12 on-board monitoring: check parameters against limits ───
        if self._store is not None:
            ool_tms = self._s12.check(
                self._store, self._config.apid, self._next_tm_seq, self._obt
            )
            if ool_tms:
                self._enqueue_tm(ool_tms)

        # ── Mode transitions ───────────────────────────────────────────
        mode_cmd = self.read_port("dhs.obc.mode_cmd")
        if mode_cmd >= 0.0:
            new_mode = int(round(mode_cmd))
            if new_mode != self._mode:
                self._transition_mode(new_mode, t)
            self.receive("dhs.obc.mode_cmd", -1.0)  # consume

        # ── Watchdog ───────────────────────────────────────────────────
        wdg_kick = self.read_port("dhs.obc.watchdog_kick")
        if wdg_kick > 0.5:
            self._wdg_last_kick = t
            self._wdg_status = WDG_NOMINAL
            self.receive("dhs.obc.watchdog_kick", 0.0)  # consume it
            logger.debug(f"[obc] Watchdog kicked at t={t:.1f}s")

        elapsed = t - self._wdg_last_kick
        if elapsed > self._config.watchdog_period_s:
            if self._wdg_status == WDG_NOMINAL:
                self._wdg_status = WDG_WARNING
                # Generate S5 low severity event
                tm = PusService5.report(
                    severity=EventSeverity.LOW,
                    event_id=0x0001,  # WDG_TIMEOUT_WARNING
                    tm_apid=self._config.apid,
                    sequence_count=self._next_tm_seq(),
                    timestamp=int(t),
                )
                self._enqueue_tm([tm])
                logger.warning(f"[obc] Watchdog timeout warning at t={t:.1f}s")
            elif elapsed > self._config.watchdog_period_s * 2:
                self._wdg_status = WDG_RESET
                self._reset_count += 1
                self._mode = MODE_SAFE
                self._wdg_last_kick = t
                tm = PusService5.report(
                    severity=EventSeverity.HIGH,
                    event_id=0x0002,  # WDG_RESET
                    tm_apid=self._config.apid,
                    sequence_count=self._next_tm_seq(),
                    timestamp=int(t),
                )
                self._enqueue_tm([tm])
                logger.warning(f"[obc] Watchdog reset at t={t:.1f}s")

        # ── Memory fill ────────────────────────────────────────────────
        dump_cmd = self.read_port("dhs.obc.memory_dump_cmd")
        if dump_cmd > 0.5:
            self._memory_used_pct = 0.0
            self.receive("dhs.obc.memory_dump_cmd", 0.0)  # consume it
            logger.info(f"[obc] Memory dump at t={t:.1f}s")

        else:
            fill_rate = MEMORY_FILL_RATE_PCT_S
            if self._mode == MODE_PAYLOAD:
                fill_rate *= 5.0  # faster fill in payload mode
            self._memory_used_pct = min(
                100.0, self._memory_used_pct + fill_rate * dt
            )

        # ── CPU load ───────────────────────────────────────────────────
        # Simplified: varies sinusoidally around baseline
        self._cpu_load = 15.0 + 5.0 * math.sin(t * 0.1)
        if self._mode == MODE_PAYLOAD:
            self._cpu_load += 20.0

        # ── Health ─────────────────────────────────────────────────────
        if self._memory_used_pct > 90.0 or self._cpu_load > 90.0:
            self._health = HEALTH_DEGRADED
        else:
            self._health = HEALTH_NOMINAL

        # ── Write DHS TM ports ─────────────────────────────────────────
        self.write_port("dhs.obc.mode", float(self._mode))
        self.write_port("dhs.obc.obt", self._obt)
        self.write_port("dhs.obc.watchdog_status", float(self._wdg_status))
        self.write_port("dhs.obc.memory_used_pct", self._memory_used_pct)
        self.write_port("dhs.obc.health", float(self._health))
        self.write_port("dhs.obc.reset_count", float(self._reset_count))
        self.write_port("dhs.obc.cpu_load", self._cpu_load)
        self.write_port("obc.tm_output", float(self._tm_seq))

        # ── HK reports ─────────────────────────────────────────────────
        self._generate_hk_reports(t)

    def _transition_mode(self, new_mode: int, t: float) -> None:
        """Execute a mode transition with S5 event reporting."""
        old_mode = self._mode
        self._mode = new_mode
        event_id = 0x0010 + new_mode  # 0x10=safe, 0x11=nominal, 0x12=payload
        tm = PusService5.report(
            severity=EventSeverity.INFORMATIVE,
            event_id=event_id,
            tm_apid=self._config.apid,
            sequence_count=self._next_tm_seq(),
            auxiliary_data=struct.pack(">BB", old_mode, new_mode),
            timestamp=int(t),
        )
        self._enqueue_tm([tm])
        logger.info(
            f"[obc] Mode transition: {old_mode} -> {new_mode} at t={t:.1f}s"
        )

    # ── HilAdapter interface ──────────────────────────────────────────────────

    def connect(self) -> None:
        """No-op  -  software stub requires no external connection."""

    def disconnect(self) -> None:
        """No-op  -  software stub has no connection to close."""

    def is_connected(self) -> bool:
        """Always True  -  software stub is always ready."""
        return True

    # ── PUS TC routing (unchanged from M7) ───────────────────────────────────

    def receive_tc(self, raw_tc: bytes, t: float = 0.0) -> list[PusTmPacket]:
        """Receive raw PUS TC bytes, parse and route."""
        responses: list[PusTmPacket] = []

        try:
            tc = self._parser.parse(raw_tc)
        except PusTcError as e:
            logger.warning(f"[obc] TC parse error: {e}")
            app_data = struct.pack(">HHH", 0, 0, 0x0001)
            failure_tm = PusTmPacket(
                apid=self._config.apid,
                sequence_count=self._next_tm_seq(),
                service=1,
                subservice=2,
                app_data=app_data,
            )
            self._enqueue_tm([failure_tm])
            return [failure_tm]

        logger.info(
            f"[obc] TC: S{tc.service}/{tc.subservice} "
            f"APID=0x{tc.apid:03X} seq={tc.sequence_count}"
        )

        responses.append(PusService1.acceptance_success(
            tc, tm_apid=self._config.apid,
            sequence_count=self._next_tm_seq(), timestamp=int(t),
        ))

        responses.extend(self._route_tc(tc, t))

        responses.append(PusService1.completion_success(
            tc, tm_apid=self._config.apid,
            sequence_count=self._next_tm_seq(), timestamp=int(t),
        ))

        self._enqueue_tm(responses)
        self._packet_store_feed_suppressed = False
        return responses

    def _route_tc(self, tc: PusTcPacket, t: float) -> list[PusTmPacket]:
        responses: list[PusTmPacket] = []

        if PusService9.is_set_obt(tc):
            try:
                new_obt = PusService9.parse_set_obt(tc)
                self._obt = new_obt
                logger.info(f"[obc] S9 OBT sync: {new_obt:.3f}s at t={t:.1f}s")
            except ValueError as e:
                logger.warning(f"[obc] S9 parse error: {e}")
        elif PusService11.is_insert(tc):
            try:
                time_tag, embedded = PusService11.parse_insert(tc)
                rid = self._s11.insert(time_tag, embedded)
                logger.info(
                    f"[obc] S11 insert #{rid}: OBT={time_tag:.1f}s "
                    f"({len(embedded)}B TC)"
                )
            except ValueError as e:
                logger.warning(f"[obc] S11 insert error: {e}")
        elif PusService11.is_delete(tc):
            try:
                rid = PusService11.parse_delete(tc)
                found = self._s11.delete(rid)
                logger.info(f"[obc] S11 delete #{rid}: {'removed' if found else 'not found'}")
            except ValueError as e:
                logger.warning(f"[obc] S11 delete error: {e}")
        elif PusService11.is_delete_all(tc):
            n = self._s11.delete_all()
            logger.info(f"[obc] S11 delete all: removed {n} activities")
        elif PusService11.is_enable(tc):
            self._s11.enable()
            logger.info("[obc] S11 schedule enabled")
        elif PusService11.is_disable(tc):
            self._s11.disable()
            logger.info("[obc] S11 schedule disabled")
        elif PusService12.is_add(tc):
            try:
                param_id, = struct.unpack_from(">H", tc.app_data)
                param_name = self._config.param_id_map.get(param_id)
                if param_name is None:
                    logger.warning(
                        f"[obc] S12 add: unknown param_id 0x{param_id:04X}"
                    )
                else:
                    defn = PusService12.parse_add(tc, param_name)
                    self._s12.add(defn)
                    logger.info(
                        f"[obc] S12 add monitor: 0x{param_id:04X} "
                        f"({param_name}) low={defn.low_limit} "
                        f"high={defn.high_limit}"
                    )
            except (ValueError, struct.error) as e:
                logger.warning(f"[obc] S12 add error: {e}")
        elif PusService12.is_delete(tc):
            try:
                param_id = PusService12.parse_delete(tc)
                found = self._s12.delete(param_id)
                logger.info(
                    f"[obc] S12 delete 0x{param_id:04X}: "
                    f"{'removed' if found else 'not found'}"
                )
            except ValueError as e:
                logger.warning(f"[obc] S12 delete error: {e}")
        elif PusService12.is_delete_all(tc):
            n = self._s12.delete_all()
            logger.info(f"[obc] S12 delete all: removed {n} monitors")
        elif PusService12.is_enable(tc):
            self._s12.enable()
            logger.info("[obc] S12 monitoring enabled")
        elif PusService12.is_disable(tc):
            self._s12.disable()
            logger.info("[obc] S12 monitoring disabled")
        elif PusService19.is_add(tc):
            try:
                event_id, action_tc = PusService19.parse_add(tc)
                self._s19.add(EventActionDefinition(event_id=event_id, action_tc=action_tc))
                logger.info(
                    f"[obc] S19 add: event 0x{event_id:04X} → "
                    f"{len(action_tc)}B action TC"
                )
            except ValueError as e:
                logger.warning(f"[obc] S19 add error: {e}")
        elif PusService19.is_delete(tc):
            try:
                event_id = PusService19.parse_delete(tc)
                found = self._s19.delete(event_id)
                logger.info(
                    f"[obc] S19 delete 0x{event_id:04X}: "
                    f"{'removed' if found else 'not found'}"
                )
            except ValueError as e:
                logger.warning(f"[obc] S19 delete error: {e}")
        elif PusService19.is_delete_all(tc):
            n = self._s19.delete_all()
            logger.info(f"[obc] S19 delete all: removed {n} definitions")
        elif PusService19.is_enable(tc):
            self._s19.enable()
            logger.info("[obc] S19 event-action enabled")
        elif PusService19.is_disable(tc):
            self._s19.disable()
            logger.info("[obc] S19 event-action disabled")
        elif PusService17.is_are_you_alive(tc):
            responses.append(PusService17.are_you_alive_response(
                tm_apid=self._config.apid,
                sequence_count=self._next_tm_seq(),
                timestamp=int(t),
            ))
        elif PusService20.is_set_parameter(tc):
            responses.extend(self._handle_s20_set(tc, t))
        elif PusService20.is_get_parameter(tc):
            responses.extend(self._handle_s20_get(tc, t))
        elif PusService6.is_load(tc):
            self._handle_s6_load(tc)
        elif PusService6.is_check(tc):
            responses.extend(self._handle_s6_check(tc, t))
        elif PusService6.is_dump(tc):
            responses.extend(self._handle_s6_dump(tc, t))
        elif PusService8.is_perform(tc):
            self._handle_s8_perform(tc, t)
        elif PusService15.is_enable(tc):
            self._handle_s15_enable(tc)
        elif PusService15.is_disable(tc):
            self._handle_s15_disable(tc)
        elif PusService15.is_retrieve(tc):
            # Stays suppressed through receive_tc()'s own final _enqueue_tm()
            # call (after this method returns) - reset there, not here, or
            # retrieved packets get silently re-buffered into the same store.
            self._packet_store_feed_suppressed = True
            responses.extend(self._handle_s15_retrieve(tc))
        elif PusService15.is_delete(tc):
            self._handle_s15_delete(tc)
        elif PusService23.is_create(tc):
            self._handle_s23_create(tc)
        elif PusService23.is_delete(tc):
            self._handle_s23_delete(tc)
        elif PusService23.is_report_attributes(tc):
            responses.extend(self._handle_s23_report_attributes(tc, t))
        else:
            logger.debug(f"[obc] Unhandled TC: S{tc.service}/{tc.subservice}")

        return responses

    def _handle_s20_set(
        self, tc: PusTcPacket, t: float
    ) -> list[PusTmPacket]:
        try:
            param_id, value = PusService20.parse_set_parameter(tc)
        except ValueError as e:
            logger.warning(f"[obc] S20 set parse error: {e}")
            return []

        canonical = self._config.param_id_map.get(param_id)
        if canonical is None:
            logger.warning(f"[obc] Unknown param_id 0x{param_id:04X}")
            return []

        if self._command_store is not None:
            self._command_store.inject(
                name=canonical, value=value, t=t,
                source_id="obc.s20.set",
            )
        if self._store is not None:
            self._store.write(
                name=canonical, value=value, t=t,
                model_id=self.equipment_id,
            )
            logger.info(
                f"[obc] S20 set: 0x{param_id:04X} -> {canonical} = {value}"
            )
        self._apply_fdir_limit(canonical, value)
        return []

    # Maps FDIR threshold param name → (monitored_param_name, field)
    _FDIR_LIMIT_MAP: dict[str, tuple[str, str]] = {
        "aocs.fdir.rate_ool_high":   ("aocs.rate", "high"),
        "aocs.fdir.rate_ool_low":    ("aocs.rate", "low"),
        "aocs.fdir.rw_speed_ool_high": ("aocs.rw", "high"),
    }

    def _apply_fdir_limit(self, canonical: str, value: float) -> None:
        """Propagate S20 FDIR threshold updates into active S12 definitions."""
        entry = self._FDIR_LIMIT_MAP.get(canonical)
        if entry is None:
            return
        prefix, field = entry
        low  = value if field == "low"  else None
        high = value if field == "high" else None
        for defn in self._s12._definitions.values():
            if defn.param_name.startswith(prefix):
                if low is not None:
                    defn.low_limit = low
                if high is not None:
                    defn.high_limit = high

    def _handle_s20_get(
        self, tc: PusTcPacket, t: float
    ) -> list[PusTmPacket]:
        try:
            param_id = PusService20.parse_get_parameter(tc)
        except ValueError as e:
            logger.warning(f"[obc] S20 get parse error: {e}")
            return []

        canonical = self._config.param_id_map.get(param_id)
        if canonical is None:
            return []

        entry = self._store.read(canonical)
        value = entry.value if entry is not None else 0.0

        return [PusService20.parameter_value_report(
            parameter_id=param_id, value=value,
            tm_apid=self._config.apid,
            sequence_count=self._next_tm_seq(),
            timestamp=int(t),
        )]

    def _handle_s6_load(self, tc: PusTcPacket) -> None:
        try:
            start_addr, data = PusService6.parse_load(tc)
        except ValueError as e:
            logger.warning(f"[obc] S6 load parse error: {e}")
            return

        if start_addr + len(data) > len(self._memory):
            logger.warning(
                f"[obc] S6 load out of range: addr=0x{start_addr:08X} "
                f"len={len(data)} (memory size={len(self._memory)})"
            )
            return

        self._memory[start_addr:start_addr + len(data)] = data
        logger.info(f"[obc] S6 load: {len(data)}B at 0x{start_addr:08X}")

    def _handle_s6_check(self, tc: PusTcPacket, t: float) -> list[PusTmPacket]:
        try:
            start_addr, length, _mem_id, expected_crc = PusService6.parse_check(tc)
        except ValueError as e:
            logger.warning(f"[obc] S6 check parse error: {e}")
            return []

        if start_addr + length > len(self._memory):
            logger.warning(
                f"[obc] S6 check out of range: addr=0x{start_addr:08X} "
                f"len={length} (memory size={len(self._memory)})"
            )
            return []

        actual_crc = PusService6.compute_crc(
            bytes(self._memory[start_addr:start_addr + length])
        )
        if actual_crc == expected_crc:
            logger.info(f"[obc] S6 check OK: addr=0x{start_addr:08X} len={length}")
            return [PusService6.check_success_report(
                start_addr, length, tm_apid=self._config.apid,
                sequence_count=self._next_tm_seq(), timestamp=int(t),
            )]

        logger.warning(
            f"[obc] S6 check mismatch: addr=0x{start_addr:08X} "
            f"expected=0x{expected_crc:04X} actual=0x{actual_crc:04X}"
        )
        return [PusService6.check_failure_report(
            start_addr, length, actual_crc, tm_apid=self._config.apid,
            sequence_count=self._next_tm_seq(), timestamp=int(t),
        )]

    def _handle_s6_dump(self, tc: PusTcPacket, t: float) -> list[PusTmPacket]:
        try:
            start_addr, length, mem_id = PusService6.parse_dump(tc)
        except ValueError as e:
            logger.warning(f"[obc] S6 dump parse error: {e}")
            return []

        if start_addr + length > len(self._memory):
            logger.warning(
                f"[obc] S6 dump out of range: addr=0x{start_addr:08X} "
                f"len={length} (memory size={len(self._memory)})"
            )
            return []

        data = bytes(self._memory[start_addr:start_addr + length])
        logger.info(f"[obc] S6 dump: {length}B at 0x{start_addr:08X}")
        return [PusService6.dump_report(
            start_addr, mem_id, data, tm_apid=self._config.apid,
            sequence_count=self._next_tm_seq(), timestamp=int(t),
        )]

    def _handle_s8_perform(self, tc: PusTcPacket, t: float) -> None:
        try:
            function_id, _args = PusService8.parse_perform(tc)
        except ValueError as e:
            logger.warning(f"[obc] S8 parse error: {e}")
            return

        new_mode = self._config.function_mode_map.get(function_id)
        if new_mode is None:
            logger.warning(f"[obc] S8 unknown function_id: {function_id}")
            return

        if new_mode != self._mode:
            self._transition_mode(new_mode, t)
        else:
            logger.info(
                f"[obc] S8 function_id={function_id}: already in mode {new_mode}"
            )

    def _handle_s15_enable(self, tc: PusTcPacket) -> None:
        try:
            store_id = PusService15.parse_enable(tc)
        except ValueError as e:
            logger.warning(f"[obc] S15 enable parse error: {e}")
            return
        store = self._packet_stores.setdefault(store_id, PacketStore())
        store.enabled = True
        logger.info(f"[obc] S15 store {store_id} enabled")

    def _handle_s15_disable(self, tc: PusTcPacket) -> None:
        try:
            store_id = PusService15.parse_disable(tc)
        except ValueError as e:
            logger.warning(f"[obc] S15 disable parse error: {e}")
            return
        store = self._packet_stores.setdefault(store_id, PacketStore())
        store.enabled = False
        logger.info(f"[obc] S15 store {store_id} disabled")

    def _handle_s15_retrieve(self, tc: PusTcPacket) -> list[PusTmPacket]:
        try:
            store_id, start_time, end_time = PusService15.parse_retrieve(tc)
        except ValueError as e:
            logger.warning(f"[obc] S15 retrieve parse error: {e}")
            return []
        store = self._packet_stores.get(store_id)
        if store is None:
            logger.warning(f"[obc] S15 retrieve: unknown store {store_id}")
            return []
        matched = [
            p for (stored_t, p) in store.packets
            if start_time <= stored_t <= end_time
        ]
        logger.info(
            f"[obc] S15 retrieve store {store_id}: {len(matched)} packet(s) "
            f"in [{start_time},{end_time}]"
        )
        return matched

    def _handle_s15_delete(self, tc: PusTcPacket) -> None:
        try:
            store_id, start_time, end_time = PusService15.parse_delete(tc)
        except ValueError as e:
            logger.warning(f"[obc] S15 delete parse error: {e}")
            return
        store = self._packet_stores.get(store_id)
        if store is None:
            logger.warning(f"[obc] S15 delete: unknown store {store_id}")
            return
        before = len(store.packets)
        store.packets = [
            (stored_t, p) for (stored_t, p) in store.packets
            if not (start_time <= stored_t <= end_time)
        ]
        logger.info(
            f"[obc] S15 delete store {store_id}: removed "
            f"{before - len(store.packets)} packet(s)"
        )

    def _handle_s23_create(self, tc: PusTcPacket) -> None:
        try:
            name, size = PusService23.parse_create(tc)
        except ValueError as e:
            logger.warning(f"[obc] S23 create parse error: {e}")
            return
        self._files[name] = size
        logger.info(f"[obc] S23 create: {name!r} ({size}B)")

    def _handle_s23_delete(self, tc: PusTcPacket) -> None:
        try:
            name = PusService23.parse_delete(tc)
        except ValueError as e:
            logger.warning(f"[obc] S23 delete parse error: {e}")
            return
        found = self._files.pop(name, None) is not None
        logger.info(f"[obc] S23 delete {name!r}: {'removed' if found else 'not found'}")

    def _handle_s23_report_attributes(
        self, tc: PusTcPacket, t: float
    ) -> list[PusTmPacket]:
        try:
            name = PusService23.parse_report_attributes(tc)
        except ValueError as e:
            logger.warning(f"[obc] S23 report attributes parse error: {e}")
            return []
        size = self._files.get(name)
        if size is None:
            logger.warning(f"[obc] S23 report attributes: {name!r} not found")
            return []
        return [PusService23.file_attribute_report(
            name, size, tm_apid=self._config.apid,
            sequence_count=self._next_tm_seq(), timestamp=int(t),
        )]

    def _generate_hk_reports(self, t: float) -> None:
        for report_id, defn in self._s3._definitions.items():
            if not defn.enabled:
                continue
            values = {}
            for name in defn.parameter_names:
                entry = self._store.read(name)
                if entry is not None:
                    values[name] = entry.value
            tm = self._s3.generate_report(
                report_id=report_id,
                parameter_values=values,
                tm_apid=self._config.apid,
                sequence_count=self._next_tm_seq(),
                timestamp=int(t),
            )
            if tm is not None:
                self._enqueue_tm([tm])

    # ── Queue access ──────────────────────────────────────────────────────────

    def get_tm_queue(self) -> list[PusTmPacket]:
        with self._lock:
            packets = list(self._tm_queue)
            self._tm_queue.clear()
            return packets

    def get_tm_by_service(
        self, service: int, subservice: int
    ) -> list[PusTmPacket]:
        with self._lock:
            return [
                p for p in self._tm_queue
                if p.service == service and p.subservice == subservice
            ]

    def register_hk_report(self, definition: HkReportDefinition) -> None:
        self._s3.define_report(definition)

    # ── Properties for test assertions ───────────────────────────────────────

    @property
    def mode(self) -> int:
        return self._mode

    @property
    def obt(self) -> float:
        return self._obt

    @property
    def watchdog_status(self) -> int:
        return self._wdg_status

    @property
    def memory_used_pct(self) -> float:
        return self._memory_used_pct

    @property
    def reset_count(self) -> int:
        return self._reset_count

    # ── Private helpers ───────────────────────────────────────────────────────

    def _next_tm_seq(self) -> int:
        self._tm_seq = (self._tm_seq + 1) % 0x4000
        return self._tm_seq

    def _enqueue_tm(self, packets: list[PusTmPacket]) -> None:
        with self._lock:
            self._tm_queue.extend(packets)
        if not self._packet_store_feed_suppressed:
            for store in self._packet_stores.values():
                if store.enabled:
                    store.packets.extend((self._obt, p) for p in packets)
        if self._store is not None:
            for p in packets:
                self._store.write(
                    f"svf.tm.{p.service}.{p.subservice}.received",
                    float(self._tm_seq), self._obt, self.equipment_id,
                )
        # Collect S19 reactions for S5 events  -  dispatched next tick
        for p in packets:
            if p.service == 5 and len(p.app_data) >= 2:
                event_id = struct.unpack_from(">H", p.app_data)[0]
                self._pending_reactions.extend(self._s19.react(event_id))
