"""
SVF PUS Service Catalogue
Implements PUS-C services S1, S3, S5, S17, S20.
Reference: ECSS-E-ST-70-41C

Service summary:
  S1  - Request Verification (acceptance, execution, completion)
  S3  - Housekeeping (define, enable, report)
  S5  - Event Reporting
  S17 - Test (are-you-alive)
  S20 - On-Board Parameter Management (set, get)

Implements: SVF-DEV-037, PUS-005 through PUS-009
"""

from __future__ import annotations

import logging
import struct
from dataclasses import dataclass, field
from typing import Optional

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
