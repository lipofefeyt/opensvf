"""
SVF TTC Equipment
Telemetry Tracking and Command equipment model.
Bridges ground segment to OBC via simulated RF link.
Implements: PUS-011
"""

from __future__ import annotations

import logging
from typing import Optional

from svf.abstractions import SyncProtocol
from svf.equipment import Equipment, PortDefinition, PortDirection
from svf.models.obc import ObcEquipment
from svf.parameter_store import ParameterStore
from svf.command_store import CommandStore
from svf.pus.tc import PusTcBuilder, PusTcPacket
from svf.pus.tm import PusTmPacket

logger = logging.getLogger(__name__)


class TtcEquipment(Equipment):
    """
    TTC Equipment — ground-to-spacecraft interface.

    Forwards raw PUS TC bytes to the OBC.
    Exposes received TM for observable assertions.

    In a real spacecraft, TTC handles RF uplink/downlink,
    frequency conversion, modulation, and frame sync.
    This model abstracts all of that to a simple byte pipe.

    Usage in test procedures:
        ttc.send_tc(PusTcPacket(service=17, subservice=1, ...))
        responses = ttc.get_tm_responses(service=17, subservice=2)
    """

    def __init__(
        self,
        obc: ObcEquipment,
        sync_protocol: SyncProtocol,
        store: ParameterStore,
        command_store: Optional[CommandStore] = None,
    ) -> None:
        self._obc = obc
        self._builder = PusTcBuilder()
        self._pending_tcs: list[PusTcPacket] = []
        self._sim_time: float = 0.0

        super().__init__(
            equipment_id="ttc",
            sync_protocol=sync_protocol,
            store=store,
            command_store=command_store,
        )

    def _declare_ports(self) -> list[PortDefinition]:
        return [
            PortDefinition(
                "ttc.uplink_active", PortDirection.OUT,
                description="Uplink active flag (1=receiving TC)",
            ),
            PortDefinition(
                "ttc.downlink_active", PortDirection.OUT,
                description="Downlink active flag (1=transmitting TM)",
            ),
        ]

    def initialise(self, start_time: float = 0.0) -> None:
        self._sim_time = start_time
        logger.info("[ttc] Initialised")

    def do_step(self, t: float, dt: float) -> None:
        """Forward pending TCs to OBC."""
        self._sim_time = t

        uplink = 0.0
        if self._pending_tcs:
            uplink = 1.0
            for tc in self._pending_tcs:
                raw = self._builder.build(tc)
                self._obc.receive_tc(raw, t=t)
                logger.info(
                    f"[ttc] Forwarded TC S{tc.service}/{tc.subservice} "
                    f"to OBC at t={t:.1f}s"
                )
            self._pending_tcs.clear()

        self.write_port("ttc.uplink_active", uplink)
        self.write_port(
            "ttc.downlink_active",
            1.0 if self._obc.get_tm_by_service(3, 25) else 0.0,
        )

    def send_tc(self, tc: PusTcPacket) -> None:
        """
        Queue a TC for forwarding to OBC on the next tick.
        Called by test procedures to inject commands.
        """
        self._pending_tcs.append(tc)
        logger.info(
            f"[ttc] TC queued: S{tc.service}/{tc.subservice} "
            f"seq={tc.sequence_count}"
        )

    def get_tm_responses(
        self,
        service: Optional[int] = None,
        subservice: Optional[int] = None,
    ) -> list[PusTmPacket]:
        """
        Get TM responses from OBC queue.
        Optionally filter by service/subservice.
        """
        all_tm = self._obc.get_tm_queue()
        if service is None:
            return all_tm
        return [
            p for p in all_tm
            if p.service == service
            and (subservice is None or p.subservice == subservice)
        ]
