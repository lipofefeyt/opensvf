"""
SVF OBC Equipment
On-Board Computer model — PUS TC router + DHS behaviour.

M7: PUS TC parsing, S1/S3/S5/S17/S20 service routing
M8: Mode state machine, OBT, watchdog, memory, CPU load

Implements: PUS-010, 1553-010, SVF-DEV-038
"""

from __future__ import annotations

import logging
import math
import struct
import threading
from dataclasses import dataclass, field
from typing import Optional

from svf.abstractions import SyncProtocol
from svf.command_store import CommandStore
from svf.equipment import Equipment, PortDefinition, PortDirection
from svf.parameter_store import ParameterStore
from svf.pus.tc import PusTcPacket, PusTcParser, PusTcError
from svf.pus.tm import PusTmPacket, PusTmBuilder
from svf.pus.services import (
    PusService1, PusService3, PusService5,
    PusService17, PusService20, HkReportDefinition,
    EventSeverity,
)

logger = logging.getLogger(__name__)

# OBC mode constants
MODE_SAFE    = 0
MODE_NOMINAL = 1
MODE_PAYLOAD = 2

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
    """
    apid: int = 0x101
    param_id_map: dict[int, str] = field(default_factory=dict)
    essential_hk: list[HkReportDefinition] = field(default_factory=list)
    watchdog_period_s: float = DEFAULT_WDG_PERIOD_S
    initial_mode: int = MODE_SAFE


class ObcEquipment(Equipment):
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

        # Register essential HK reports
        for defn in config.essential_hk:
            self._s3.add_essential(defn)

        super().__init__(
            equipment_id="obc",
            sync_protocol=sync_protocol,
            store=store,
            command_store=command_store,
        )

        # Specific for mode
        self._port_values["dhs.obc.mode_cmd"] = -1.0

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
        """Advance OBC by one tick — DHS state + PUS routing."""
        # ── On-board time ──────────────────────────────────────────────
        self._obt += dt

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
        return responses

    def _route_tc(self, tc: PusTcPacket, t: float) -> list[PusTmPacket]:
        responses: list[PusTmPacket] = []

        if PusService17.is_are_you_alive(tc):
            responses.append(PusService17.are_you_alive_response(
                tm_apid=self._config.apid,
                sequence_count=self._next_tm_seq(),
                timestamp=int(t),
            ))
        elif PusService20.is_set_parameter(tc):
            responses.extend(self._handle_s20_set(tc, t))
        elif PusService20.is_get_parameter(tc):
            responses.extend(self._handle_s20_get(tc, t))
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
            logger.info(
                f"[obc] S20 set: 0x{param_id:04X} -> {canonical} = {value}"
            )
        return []

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
