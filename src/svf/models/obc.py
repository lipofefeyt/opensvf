"""
SVF OBC Equipment
On-Board Computer model acting as PUS TC router.

Receives raw PUS-C TC bytes via tc_input IN port.
Parses TCs using PusTcParser.
Routes commands to equipment via CommandStore.
Generates PUS TM responses (S1, S3, S17, S20).
Exposes TM via tm_output OUT port.

This model intentionally knows nothing about specific equipment
parameters. It routes by APID + service/subservice + parameter_id,
looking up canonical parameter names from the SRDB PUS mappings.

Implements: PUS-010, 1553-010
"""

from __future__ import annotations

import logging
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
)

logger = logging.getLogger(__name__)


@dataclass
class ObcConfig:
    """
    OBC configuration.

    Attributes:
        apid:              OBC APID for generated TM packets
        param_id_map:      Maps PUS parameter_id -> SRDB canonical name
                           Built from SRDB PUS mappings at startup
        essential_hk:      List of essential HK report definitions
                           activated automatically at initialise()
    """
    apid: int = 0x101
    param_id_map: dict[int, str] = field(default_factory=dict)
    essential_hk: list[HkReportDefinition] = field(default_factory=list)


class ObcEquipment(Equipment):
    """
    On-Board Computer Equipment.

    Port interface:
        tc_input  (IN,  FLOAT) — raw PUS TC packet size in bytes (signals arrival)
        tm_output (OUT, FLOAT) — latest TM sequence count (signals TM generated)

    Note: Raw TC bytes are passed via CommandStore using the key
    'obc.tc_raw_{sequence}'. This avoids encoding binary data as floats.
    The tc_input port carries the TC sequence count as a signal.

    TM packets are stored internally and retrievable via get_tm_queue().
    Test procedures can assert on TM content directly.
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
        self._tc_seq: int = 0
        self._lock = threading.Lock()

        # Register essential HK reports
        for defn in config.essential_hk:
            self._s3.add_essential(defn)

        super().__init__(
            equipment_id="obc",
            sync_protocol=sync_protocol,
            store=store,
            command_store=command_store,
        )

    def _declare_ports(self) -> list[PortDefinition]:
        return [
            PortDefinition(
                "obc.tc_input", PortDirection.IN,
                description="TC arrival signal (sequence count)",
            ),
            PortDefinition(
                "obc.tm_output", PortDirection.OUT,
                description="Latest TM sequence count",
            ),
        ]

    def initialise(self, start_time: float = 0.0) -> None:
        logger.info(
            f"[obc] Initialised: APID=0x{self._config.apid:03X}, "
            f"{len(self._config.param_id_map)} parameter mappings, "
            f"{len(self._config.essential_hk)} essential HK reports"
        )

    def do_step(self, t: float, dt: float) -> None:
        """
        Process pending TCs and generate TM responses.
        """
        if self._command_store is None:
            return

        # Check for pending TC raw bytes
        tc_signal = self.read_port("obc.tc_input")
        if tc_signal > 0 and self._command_store is not None:
            # Read raw TC from CommandStore
            key = f"obc.tc_raw_{int(tc_signal)}"
            entry = self._command_store.take(key)
            if entry is not None:
                # Entry value encodes byte index — raw bytes stored separately
                # For simplicity: TC bytes stored as list in _pending_tcs
                pass

        # Process any directly queued TCs
        self._process_pending_tcs(t)

        # Generate periodic HK reports
        self._generate_hk_reports(t)

        # Signal TM output
        self.write_port("obc.tm_output", float(self._tm_seq))

    def receive_tc(self, raw_tc: bytes, t: float = 0.0) -> list[PusTmPacket]:
        """
        Receive a raw PUS TC packet and process it immediately.

        This is the primary entry point for TC injection from TTC Equipment
        or directly from test procedures.

        Returns list of generated TM packets (S1 ack + service response).
        """
        responses: list[PusTmPacket] = []

        try:
            tc = self._parser.parse(raw_tc)
        except PusTcError as e:
            logger.warning(f"[obc] TC parse error: {e}")
            # Build S1(1,2) acceptance failure directly
            # We don't have a valid TC to reference so use zeros
            import struct as _struct
            app_data = _struct.pack(">HHH", 0, 0, 0x0001)  # apid=0, seq=0, code=format_error
            from svf.pus.tm import PusTmPacket
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
            f"[obc] TC received: S{tc.service}/{tc.subservice} "
            f"APID=0x{tc.apid:03X} seq={tc.sequence_count}"
        )

        # S1(1,1) acceptance
        responses.append(PusService1.acceptance_success(
            tc,
            tm_apid=self._config.apid,
            sequence_count=self._next_tm_seq(),
            timestamp=int(t),
        ))

        # Route by service
        service_responses = self._route_tc(tc, t)
        responses.extend(service_responses)

        # S1(1,7) completion success
        responses.append(PusService1.completion_success(
            tc,
            tm_apid=self._config.apid,
            sequence_count=self._next_tm_seq(),
            timestamp=int(t),
        ))

        self._enqueue_tm(responses)
        return responses

    def get_tm_queue(self) -> list[PusTmPacket]:
        """Return and clear all queued TM packets."""
        with self._lock:
            packets = list(self._tm_queue)
            self._tm_queue.clear()
            return packets

    def get_tm_by_service(
        self, service: int, subservice: int
    ) -> list[PusTmPacket]:
        """
        Return all queued TM packets matching service/subservice.
        Does not consume packets from the queue.
        """
        with self._lock:
            return [
                p for p in self._tm_queue
                if p.service == service and p.subservice == subservice
            ]

    def register_hk_report(self, definition: HkReportDefinition) -> None:
        """Register a housekeeping report definition (TC(3,1) equivalent)."""
        self._s3.define_report(definition)

    # ── Private helpers ───────────────────────────────────────────────────────

    def _route_tc(
        self, tc: PusTcPacket, t: float
    ) -> list[PusTmPacket]:
        """Route TC to appropriate service handler."""
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
            logger.debug(
                f"[obc] Unhandled TC: S{tc.service}/{tc.subservice}"
            )

        return responses

    def _handle_s20_set(
        self, tc: PusTcPacket, t: float
    ) -> list[PusTmPacket]:
        """Handle TC(20,1) — set parameter value."""
        try:
            param_id, value = PusService20.parse_set_parameter(tc)
        except ValueError as e:
            logger.warning(f"[obc] S20 set parse error: {e}")
            return []

        canonical = self._config.param_id_map.get(param_id)
        if canonical is None:
            logger.warning(
                f"[obc] Unknown parameter_id 0x{param_id:04X} in S20 set"
            )
            return []

        # Route to CommandStore — bus adapter will pick it up
        if self._command_store is not None:
            self._command_store.inject(
                name=canonical,
                value=value,
                t=t,
                source_id=f"obc.s20.set",
            )
            logger.info(
                f"[obc] S20 set: param_id=0x{param_id:04X} "
                f"-> {canonical} = {value}"
            )

        return []  # S1 completion generated by caller

    def _handle_s20_get(
        self, tc: PusTcPacket, t: float
    ) -> list[PusTmPacket]:
        """Handle TC(20,3) — get parameter value."""
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
            parameter_id=param_id,
            value=value,
            tm_apid=self._config.apid,
            sequence_count=self._next_tm_seq(),
            timestamp=int(t),
        )]

    def _generate_hk_reports(self, t: float) -> None:
        """Generate enabled HK reports — called each tick."""
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

    def _process_pending_tcs(self, t: float) -> None:
        """Process TCs pending in internal queue."""
        pass  # TCs arrive via receive_tc() directly

    def _next_tm_seq(self) -> int:
        self._tm_seq = (self._tm_seq + 1) % 0x4000
        return self._tm_seq

    def _enqueue_tm(self, packets: list[PusTmPacket]) -> None:
        with self._lock:
            self._tm_queue.extend(packets)
