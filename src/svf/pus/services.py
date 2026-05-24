"""
SVF PUS Service Catalogue
Implements PUS-C services S1, S3, S5, S9, S11, S12, S17, S20.
Reference: ECSS-E-ST-70-41C

Service summary:
  S1  - Request Verification (acceptance, execution, completion)
  S3  - Housekeeping (define, enable, report)
  S5  - Event Reporting
  S9  - Time Management (OBT sync via CUC timestamp)
  S11 - Time-Based Scheduling (insert/delete/enable/disable time-tagged TCs)
  S12 - On-Board Monitoring (parameter OOL limit checks → S5 events)
  S17 - Test (are-you-alive)
  S20 - On-Board Parameter Management (set, get)

Implements: SVF-DEV-037, PUS-005 through PUS-009, SVF-DEV-162, SVF-DEV-163, SVF-DEV-164
"""

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

logger = logging.getLogger(__name__)


# ── Service 1 — Request Verification ─────────────────────────────────────────

class PusService1:
    """
    PUS Service 1 — Request Verification.

    Generates TM(1,1) acceptance, TM(1,3) execution started,
    TM(1,7) completion success, TM(1,2/4/8) failure reports.
    """

    @staticmethod
    def acceptance_success(
        tc: PusTcPacket,
        tm_apid: int,
        sequence_count: int,
        timestamp: int = 0,
    ) -> PusTmPacket:
        """TM(1,1) — TC acceptance success."""
        app_data = struct.pack(
            ">HH",
            tc.apid,
            tc.sequence_count,
        )
        return PusTmPacket(
            apid=tm_apid,
            sequence_count=sequence_count,
            service=1,
            subservice=1,
            timestamp=timestamp,
            app_data=app_data,
        )

    @staticmethod
    def acceptance_failure(
        tc: PusTcPacket,
        tm_apid: int,
        sequence_count: int,
        failure_code: int = 0,
        timestamp: int = 0,
    ) -> PusTmPacket:
        """TM(1,2) — TC acceptance failure."""
        app_data = struct.pack(
            ">HHH",
            tc.apid,
            tc.sequence_count,
            failure_code,
        )
        return PusTmPacket(
            apid=tm_apid,
            sequence_count=sequence_count,
            service=1,
            subservice=2,
            timestamp=timestamp,
            app_data=app_data,
        )

    @staticmethod
    def completion_success(
        tc: PusTcPacket,
        tm_apid: int,
        sequence_count: int,
        timestamp: int = 0,
    ) -> PusTmPacket:
        """TM(1,7) — TC execution completion success."""
        app_data = struct.pack(
            ">HH",
            tc.apid,
            tc.sequence_count,
        )
        return PusTmPacket(
            apid=tm_apid,
            sequence_count=sequence_count,
            service=1,
            subservice=7,
            timestamp=timestamp,
            app_data=app_data,
        )

    @staticmethod
    def completion_failure(
        tc: PusTcPacket,
        tm_apid: int,
        sequence_count: int,
        failure_code: int = 0,
        timestamp: int = 0,
    ) -> PusTmPacket:
        """TM(1,8) — TC execution completion failure."""
        app_data = struct.pack(
            ">HHH",
            tc.apid,
            tc.sequence_count,
            failure_code,
        )
        return PusTmPacket(
            apid=tm_apid,
            sequence_count=sequence_count,
            service=1,
            subservice=8,
            timestamp=timestamp,
            app_data=app_data,
        )


# ── Service 3 — Housekeeping ──────────────────────────────────────────────────

@dataclass
class HkReportDefinition:
    """
    A housekeeping report structure definition.

    Attributes:
        report_id:       Unique report identifier
        parameter_names: Ordered list of SRDB canonical parameter names
        period_s:        Collection period in seconds (0 = on-request only)
        enabled:         Whether periodic generation is active
    """
    report_id: int
    parameter_names: list[str]
    period_s: float = 1.0
    enabled: bool = False


class PusService3:
    """
    PUS Service 3 — Housekeeping and Diagnostic Data Reporting.

    TC(3,1)  — Define New HK Parameter Report Structure
    TC(3,5)  — Enable Periodic Generation of HK Parameter Report
    TC(3,6)  — Disable Periodic Generation
    TC(3,27) — Generate One-Shot HK Report (immediate)
    TM(3,25) — HK Parameter Report
    """

    def __init__(self) -> None:
        self._definitions: dict[int, HkReportDefinition] = {}
        self._essential: list[HkReportDefinition] = []

    def define_report(self, definition: HkReportDefinition) -> None:
        """TC(3,1) — Define a new HK report structure."""
        self._definitions[definition.report_id] = definition
        logger.info(
            f"[S3] Defined HK report {definition.report_id}: "
            f"{definition.parameter_names}"
        )

    def add_essential(self, definition: HkReportDefinition) -> None:
        """
        Add an essential HK report — activated automatically at boot.
        Essential reports are always enabled regardless of TC(3,5/6).
        """
        definition.enabled = True
        self._essential.append(definition)
        self._definitions[definition.report_id] = definition

    def enable(self, report_id: int) -> None:
        """TC(3,5) — Enable periodic generation."""
        if report_id in self._definitions:
            self._definitions[report_id].enabled = True
            logger.info(f"[S3] Enabled HK report {report_id}")

    def disable(self, report_id: int) -> None:
        """TC(3,6) — Disable periodic generation."""
        defn = self._definitions.get(report_id)
        if defn and defn not in self._essential:
            defn.enabled = False
            logger.info(f"[S3] Disabled HK report {report_id}")

    def generate_report(
        self,
        report_id: int,
        parameter_values: dict[str, float],
        tm_apid: int,
        sequence_count: int,
        timestamp: int = 0,
    ) -> Optional[PusTmPacket]:
        """
        TM(3,25) — Generate a HK parameter report.

        Args:
            report_id:         Report structure ID
            parameter_values:  Dict of canonical_name -> current value
            tm_apid:           TM APID
            sequence_count:    TM sequence counter
            timestamp:         CUC timestamp
        """
        defn = self._definitions.get(report_id)
        if defn is None:
            logger.warning(f"[S3] Unknown report ID {report_id}")
            return None

        # Pack: report_id (2B) + N floats (4B each)
        app_data = struct.pack(">H", report_id)
        for name in defn.parameter_names:
            value = parameter_values.get(name, 0.0)
            app_data += struct.pack(">f", value)

        return PusTmPacket(
            apid=tm_apid,
            sequence_count=sequence_count,
            service=3,
            subservice=25,
            timestamp=timestamp,
            app_data=app_data,
        )

    @staticmethod
    def parse_report(
        tm: PusTmPacket,
        parameter_names: list[str],
    ) -> dict[str, float]:
        """
        Parse a TM(3,25) report into a dict of name -> value.
        Useful in test procedures to inspect OBC telemetry.
        """
        if tm.service != 3 or tm.subservice != 25:
            raise ValueError("Not a TM(3,25) packet")
        data = tm.app_data
        report_id = struct.unpack_from(">H", data, 0)[0]
        values: dict[str, float] = {}
        offset = 2
        for name in parameter_names:
            if offset + 4 > len(data):
                break
            value = struct.unpack_from(">f", data, offset)[0]
            values[name] = value
            offset += 4
        return values


# ── Service 5 — Event Reporting ───────────────────────────────────────────────

class EventSeverity:
    INFORMATIVE = 1
    LOW         = 2
    MEDIUM      = 3
    HIGH        = 4


class PusService5:
    """
    PUS Service 5 — Event Reporting.

    TM(5,1) — Informative event
    TM(5,2) — Low severity anomaly
    TM(5,3) — Medium severity anomaly
    TM(5,4) — High severity anomaly
    """

    @staticmethod
    def report(
        severity: int,
        event_id: int,
        tm_apid: int,
        sequence_count: int,
        auxiliary_data: bytes = b"",
        timestamp: int = 0,
    ) -> PusTmPacket:
        """Generate an event report TM(5, severity)."""
        if severity not in (1, 2, 3, 4):
            raise ValueError(f"Invalid severity {severity} — must be 1-4")
        app_data = struct.pack(">H", event_id) + auxiliary_data
        return PusTmPacket(
            apid=tm_apid,
            sequence_count=sequence_count,
            service=5,
            subservice=severity,
            timestamp=timestamp,
            app_data=app_data,
        )


# ── Service 9 — Time Management ──────────────────────────────────────────────

class PusService9:
    """
    PUS Service 9 — Time Management.

    TC(9,128) — Set On-Board Time (OBT) from CUC-4,2 timestamp.
    """

    @staticmethod
    def is_set_obt(tc: PusTcPacket) -> bool:
        """True if this TC is a S9 Set OBT request."""
        return tc.service == 9 and tc.subservice == 128

    @staticmethod
    def parse_set_obt(tc: PusTcPacket) -> float:
        """
        Parse TC(9,128) application data as CUC-4,2 timestamp.

        Format: 4-byte coarse seconds (big-endian) + 2-byte fine (1/65536 s resolution).
        Returns OBT in seconds as a float.
        """
        if len(tc.app_data) < 6:
            raise ValueError(
                f"TC(9,128) app_data too short: {len(tc.app_data)} bytes (need 6)"
            )
        coarse: int
        fine: int
        coarse, fine = struct.unpack_from(">IH", tc.app_data)
        return coarse + fine / 65536.0

    @staticmethod
    def build_set_obt(
        obt_seconds: float,
        tc_apid: int = 0x100,
        sequence_count: int = 0,
    ) -> PusTcPacket:
        """Build TC(9,128) from an OBT value in seconds."""
        coarse = int(obt_seconds)
        fine = int((obt_seconds - coarse) * 65536) & 0xFFFF
        app_data = struct.pack(">IH", coarse, fine)
        return PusTcPacket(
            apid=tc_apid,
            sequence_count=sequence_count,
            service=9,
            subservice=128,
            app_data=app_data,
        )


# ── Service 11 — Time-Based Scheduling ───────────────────────────────────────

@dataclass
class ScheduledActivity:
    """A single entry in the on-board time-based schedule."""
    request_id: int
    time_tag: float
    tc_bytes: bytes


class TimeBasedScheduler:
    """
    On-board time-based schedule.

    Holds a sorted list of ``ScheduledActivity`` items. On each OBT tick
    ``ObcEquipment`` calls ``due(obt)`` to drain and fire any overdue TCs.
    """

    def __init__(self) -> None:
        self._activities: list[ScheduledActivity] = []
        self._next_id: int = 1
        self._enabled: bool = True

    def insert(self, time_tag: float, tc_bytes: bytes) -> int:
        """Schedule *tc_bytes* to fire at *time_tag* seconds OBT. Returns request_id."""
        rid = self._next_id
        self._next_id += 1
        self._activities.append(ScheduledActivity(rid, time_tag, tc_bytes))
        self._activities.sort(key=lambda a: a.time_tag)
        return rid

    def delete(self, request_id: int) -> bool:
        """Delete a scheduled activity. Returns True if found and removed."""
        before = len(self._activities)
        self._activities = [a for a in self._activities if a.request_id != request_id]
        return len(self._activities) < before

    def delete_all(self) -> int:
        """Remove all scheduled activities. Returns count removed."""
        n = len(self._activities)
        self._activities.clear()
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
        return len(self._activities)

    def due(self, obt: float) -> list[bytes]:
        """Return and remove TC bytes for all activities with time_tag <= *obt*."""
        if not self._enabled:
            return []
        due = [a for a in self._activities if a.time_tag <= obt]
        if due:
            due_ids = {a.request_id for a in due}
            self._activities = [a for a in self._activities if a.request_id not in due_ids]
        return [a.tc_bytes for a in due]


class PusService11:
    """
    PUS Service 11 — Time-Based Scheduling.

    TC(11,4)  — Insert Activity (time-tagged TC)
    TC(11,5)  — Delete Activity by request_id
    TC(11,6)  — Delete All Activities
    TC(11,17) — Enable Schedule
    TC(11,18) — Disable Schedule

    TC(11,4) app_data format (SVF pragmatic subset):
        4B CUC coarse time tag  (big-endian uint32)
        2B CUC fine time tag    (big-endian uint16, 1/65536 s)
        N B embedded TC frame
    """

    @staticmethod
    def is_insert(tc: PusTcPacket) -> bool:
        return tc.service == 11 and tc.subservice == 4

    @staticmethod
    def is_delete(tc: PusTcPacket) -> bool:
        return tc.service == 11 and tc.subservice == 5

    @staticmethod
    def is_delete_all(tc: PusTcPacket) -> bool:
        return tc.service == 11 and tc.subservice == 6

    @staticmethod
    def is_enable(tc: PusTcPacket) -> bool:
        return tc.service == 11 and tc.subservice == 17

    @staticmethod
    def is_disable(tc: PusTcPacket) -> bool:
        return tc.service == 11 and tc.subservice == 18

    @staticmethod
    def parse_insert(tc: PusTcPacket) -> tuple[float, bytes]:
        """
        Parse TC(11,4) app_data.
        Returns (time_tag_seconds, embedded_tc_bytes).
        """
        if len(tc.app_data) < 7:
            raise ValueError(
                f"TC(11,4) app_data too short: {len(tc.app_data)} bytes (need ≥7)"
            )
        coarse: int
        fine: int
        coarse, fine = struct.unpack_from(">IH", tc.app_data)
        time_tag = coarse + fine / 65536.0
        return time_tag, bytes(tc.app_data[6:])

    @staticmethod
    def parse_delete(tc: PusTcPacket) -> int:
        """Parse TC(11,5) app_data → request_id."""
        if len(tc.app_data) < 2:
            raise ValueError(
                f"TC(11,5) app_data too short: {len(tc.app_data)} bytes (need 2)"
            )
        rid: int
        rid, = struct.unpack_from(">H", tc.app_data)
        return rid

    @staticmethod
    def build_insert(
        time_tag: float,
        embedded_tc_bytes: bytes,
        tc_apid: int = 0x100,
        sequence_count: int = 0,
    ) -> PusTcPacket:
        """Build TC(11,4) wrapping *embedded_tc_bytes* with a CUC-4,2 time tag."""
        coarse = int(time_tag)
        fine = int((time_tag - coarse) * 65536) & 0xFFFF
        app_data = struct.pack(">IH", coarse, fine) + embedded_tc_bytes
        return PusTcPacket(
            apid=tc_apid,
            sequence_count=sequence_count,
            service=11,
            subservice=4,
            app_data=app_data,
        )


# ── Service 12 — On-Board Monitoring ─────────────────────────────────────────

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


# ── Service 17 — Test ─────────────────────────────────────────────────────────

class PusService17:
    """
    PUS Service 17 — Test.

    TC(17,1) — Are-you-alive test request
    TM(17,2) — Are-you-alive test response
    TC(17,3) — On-board connection test request
    TM(17,4) — On-board connection test response
    """

    @staticmethod
    def is_are_you_alive(tc: PusTcPacket) -> bool:
        """True if this TC is a S17 are-you-alive request."""
        return tc.service == 17 and tc.subservice == 1

    @staticmethod
    def are_you_alive_response(
        tm_apid: int,
        sequence_count: int,
        timestamp: int = 0,
    ) -> PusTmPacket:
        """TM(17,2) — Are-you-alive response."""
        return PusTmPacket(
            apid=tm_apid,
            sequence_count=sequence_count,
            service=17,
            subservice=2,
            timestamp=timestamp,
        )


# ── Service 20 — On-Board Parameter Management ────────────────────────────────

class PusService20:
    """
    PUS Service 20 — On-Board Parameter Management.

    TC(20,1) — Set parameter value
    TC(20,3) — Get parameter value
    TM(20,4) — Parameter value report
    """

    @staticmethod
    def is_set_parameter(tc: PusTcPacket) -> bool:
        """True if this TC is a S20 set parameter request."""
        return tc.service == 20 and tc.subservice == 1

    @staticmethod
    def is_get_parameter(tc: PusTcPacket) -> bool:
        """True if this TC is a S20 get parameter request."""
        return tc.service == 20 and tc.subservice == 3

    @staticmethod
    def parse_set_parameter(
        tc: PusTcPacket,
    ) -> tuple[int, float]:
        """
        Parse TC(20,1) application data.
        Returns (parameter_id, value).
        """
        if len(tc.app_data) < 6:
            raise ValueError(
                f"TC(20,1) app_data too short: {len(tc.app_data)} bytes"
            )
        param_id, value = struct.unpack_from(">Hf", tc.app_data)
        return param_id, value

    @staticmethod
    def parse_get_parameter(tc: PusTcPacket) -> int:
        """
        Parse TC(20,3) application data.
        Returns parameter_id.
        """
        if len(tc.app_data) < 2:
            raise ValueError(
                f"TC(20,3) app_data too short: {len(tc.app_data)} bytes"
            )
        param_id = int(struct.unpack_from(">H", tc.app_data)[0])
        return param_id

    @staticmethod
    def parameter_value_report(
        parameter_id: int,
        value: float,
        tm_apid: int,
        sequence_count: int,
        timestamp: int = 0,
    ) -> PusTmPacket:
        """TM(20,4) — Parameter value report."""
        app_data = struct.pack(">Hf", parameter_id, value)
        return PusTmPacket(
            apid=tm_apid,
            sequence_count=sequence_count,
            service=20,
            subservice=4,
            timestamp=timestamp,
            app_data=app_data,
        )
