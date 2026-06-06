"""PUS Service 12 — On-Board Monitoring."""

from __future__ import annotations

import logging
import math
import struct
from dataclasses import dataclass, field
from typing import Callable, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from svf.stores.parameter_store import ParameterStore

from svf.pus.tc import PusTcPacket
from svf.pus.tm import PusTmPacket
from svf.pus.services.s05_event_reporting import PusService5

logger = logging.getLogger(__name__)

_S12_ADD_FMT = ">HffHHB"   # param_id, low, high, event_id_low, event_id_high, severity
_S12_ADD_LEN = struct.calcsize(_S12_ADD_FMT)  # 15 bytes


@dataclass
class MonitoringDefinition:
    """
    A single parameter monitoring definition (PMD).

    Attributes:
        param_id:       PUS parameter ID (key in ObcConfig.param_id_map)
        param_name:     SRDB canonical name (resolved at insertion)
        low_limit:      Trigger OOL when value < low_limit (None = no check)
        high_limit:     Trigger OOL when value > high_limit (None = no check)
        event_id_low:   S5 event_id emitted on low-limit violation
        event_id_high:  S5 event_id emitted on high-limit violation
        severity:       EventSeverity for generated S5 events
        enabled:        Whether this PMD is active
    """
    param_id:      int
    param_name:    str
    low_limit:     Optional[float]
    high_limit:    Optional[float]
    event_id_low:  int
    event_id_high: int
    severity:      int
    enabled:       bool = True
    _in_low_ool:   bool = field(default=False, init=False, repr=False)
    _in_high_ool:  bool = field(default=False, init=False, repr=False)


class OnBoardMonitor:
    """
    On-Board Monitoring subsystem.

    Holds a dict of ``MonitoringDefinition`` items keyed by param_id.
    On each OBC tick ``ObcEquipment`` calls ``check()`` to evaluate all
    enabled definitions and generate S5 event reports for OOL transitions.

    Transition semantics: a S5 event is generated once on *entry* into an
    OOL state. The event is not repeated until the parameter recovers and
    crosses the limit again (latching behaviour).
    """

    def __init__(self) -> None:
        self._definitions: dict[int, MonitoringDefinition] = {}
        self._enabled: bool = True

    def add(self, defn: MonitoringDefinition) -> None:
        self._definitions[defn.param_id] = defn

    def delete(self, param_id: int) -> bool:
        return self._definitions.pop(param_id, None) is not None

    def delete_all(self) -> int:
        n = len(self._definitions)
        self._definitions.clear()
        return n

    def enable(self) -> None:
        self._enabled = True

    def disable(self) -> None:
        self._enabled = False

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def count(self) -> int:
        return len(self._definitions)

    def update_limits_for_param(
        self,
        param_name: str,
        low: Optional[float] = None,
        high: Optional[float] = None,
    ) -> int:
        """Update low/high limits on all MonitoringDefinitions watching param_name.

        Called by the OBC S20 handler when a FDIR threshold parameter is set.
        Returns the number of definitions updated.
        """
        updated = 0
        for defn in self._definitions.values():
            if defn.param_name == param_name:
                if low is not None:
                    defn.low_limit = low
                if high is not None:
                    defn.high_limit = high
                updated += 1
        return updated

    def check(
        self,
        store: ParameterStore,
        tm_apid: int,
        next_seq: Callable[[], int],
        obt: float,
    ) -> list[PusTmPacket]:
        """
        Evaluate all enabled PMDs against the current ParameterStore.
        Returns a list of S5 event TM packets for any new OOL transitions.
        """
        if not self._enabled:
            return []
        packets: list[PusTmPacket] = []
        for defn in self._definitions.values():
            if not defn.enabled:
                continue
            entry = store.read(defn.param_name)
            if entry is None:
                continue
            value = entry.value

            if defn.low_limit is not None:
                if value < defn.low_limit:
                    if not defn._in_low_ool:
                        defn._in_low_ool = True
                        packets.append(PusService5.report(
                            severity=defn.severity,
                            event_id=defn.event_id_low,
                            tm_apid=tm_apid,
                            sequence_count=next_seq(),
                            auxiliary_data=struct.pack(">f", value),
                            timestamp=int(obt),
                        ))
                else:
                    defn._in_low_ool = False

            if defn.high_limit is not None:
                if value > defn.high_limit:
                    if not defn._in_high_ool:
                        defn._in_high_ool = True
                        packets.append(PusService5.report(
                            severity=defn.severity,
                            event_id=defn.event_id_high,
                            tm_apid=tm_apid,
                            sequence_count=next_seq(),
                            auxiliary_data=struct.pack(">f", value),
                            timestamp=int(obt),
                        ))
                else:
                    defn._in_high_ool = False

        return packets


class PusService12:
    """
    PUS Service 12 — On-Board Monitoring.

    TC(12,1)  — Enable Monitoring
    TC(12,2)  — Disable Monitoring
    TC(12,3)  — Add/Replace Monitoring Definition
    TC(12,4)  — Delete Monitoring Definition
    TC(12,5)  — Delete All Monitoring Definitions

    TC(12,3) app_data format (SVF subset, 15 bytes):
        2B uint16  param_id
        4B float32 low_limit  (NaN = no check)
        4B float32 high_limit (NaN = no check)
        2B uint16  event_id_low
        2B uint16  event_id_high
        1B uint8   severity (1–4)
    """

    @staticmethod
    def is_enable(tc: PusTcPacket) -> bool:
        return tc.service == 12 and tc.subservice == 1

    @staticmethod
    def is_disable(tc: PusTcPacket) -> bool:
        return tc.service == 12 and tc.subservice == 2

    @staticmethod
    def is_add(tc: PusTcPacket) -> bool:
        return tc.service == 12 and tc.subservice == 3

    @staticmethod
    def is_delete(tc: PusTcPacket) -> bool:
        return tc.service == 12 and tc.subservice == 4

    @staticmethod
    def is_delete_all(tc: PusTcPacket) -> bool:
        return tc.service == 12 and tc.subservice == 5

    @staticmethod
    def parse_add(tc: PusTcPacket, param_name: str) -> MonitoringDefinition:
        """
        Parse TC(12,3) app_data into a ``MonitoringDefinition``.

        Args:
            tc:         The TC(12,3) packet.
            param_name: Resolved SRDB canonical name for ``param_id``.
        """
        if len(tc.app_data) < _S12_ADD_LEN:
            raise ValueError(
                f"TC(12,3) app_data too short: {len(tc.app_data)} bytes "
                f"(need {_S12_ADD_LEN})"
            )
        param_id: int
        low: float
        high: float
        ev_low: int
        ev_high: int
        sev: int
        param_id, low, high, ev_low, ev_high, sev = struct.unpack_from(
            _S12_ADD_FMT, tc.app_data
        )
        return MonitoringDefinition(
            param_id=param_id,
            param_name=param_name,
            low_limit=None if math.isnan(low) else low,
            high_limit=None if math.isnan(high) else high,
            event_id_low=ev_low,
            event_id_high=ev_high,
            severity=sev,
        )

    @staticmethod
    def parse_delete(tc: PusTcPacket) -> int:
        """Parse TC(12,4) app_data → param_id."""
        if len(tc.app_data) < 2:
            raise ValueError(
                f"TC(12,4) app_data too short: {len(tc.app_data)} bytes (need 2)"
            )
        param_id: int
        param_id, = struct.unpack_from(">H", tc.app_data)
        return param_id

    @staticmethod
    def build_add(
        param_id: int,
        low_limit: Optional[float],
        high_limit: Optional[float],
        event_id_low: int,
        event_id_high: int,
        severity: int,
        tc_apid: int = 0x100,
        sequence_count: int = 0,
    ) -> PusTcPacket:
        """Build TC(12,3) from monitoring parameters."""
        low  = float("nan") if low_limit  is None else low_limit
        high = float("nan") if high_limit is None else high_limit
        app_data = struct.pack(
            _S12_ADD_FMT,
            param_id, low, high, event_id_low, event_id_high, severity,
        )
        return PusTcPacket(
            apid=tc_apid,
            sequence_count=sequence_count,
            service=12,
            subservice=3,
            app_data=app_data,
        )
