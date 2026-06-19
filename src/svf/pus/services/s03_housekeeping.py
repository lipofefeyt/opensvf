"""PUS Service 3  -  Housekeeping and Diagnostic Data Reporting."""

from __future__ import annotations

import logging
import struct
from dataclasses import dataclass
from typing import Optional

from svf.pus.tm import PusTmPacket

logger = logging.getLogger(__name__)


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
    PUS Service 3  -  Housekeeping and Diagnostic Data Reporting.

    TC(3,1)   -  Define New HK Parameter Report Structure
    TC(3,5)   -  Enable Periodic Generation of HK Parameter Report
    TC(3,6)   -  Disable Periodic Generation
    TC(3,27)  -  Generate One-Shot HK Report (immediate)
    TM(3,25)  -  HK Parameter Report
    """

    def __init__(self) -> None:
        self._definitions: dict[int, HkReportDefinition] = {}
        self._essential: list[HkReportDefinition] = []

    def define_report(self, definition: HkReportDefinition) -> None:
        """TC(3,1)  -  Define a new HK report structure."""
        self._definitions[definition.report_id] = definition
        logger.info(
            f"[S3] Defined HK report {definition.report_id}: "
            f"{definition.parameter_names}"
        )

    def add_essential(self, definition: HkReportDefinition) -> None:
        """
        Add an essential HK report  -  activated automatically at boot.
        Essential reports are always enabled regardless of TC(3,5/6).
        """
        definition.enabled = True
        self._essential.append(definition)
        self._definitions[definition.report_id] = definition

    def enable(self, report_id: int) -> None:
        """TC(3,5)  -  Enable periodic generation."""
        if report_id in self._definitions:
            self._definitions[report_id].enabled = True
            logger.info(f"[S3] Enabled HK report {report_id}")

    def disable(self, report_id: int) -> None:
        """TC(3,6)  -  Disable periodic generation."""
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
        TM(3,25)  -  Generate a HK parameter report.

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
        struct.unpack_from(">H", data, 0)[0]  # report_id (consumed for framing)
        values: dict[str, float] = {}
        offset = 2
        for name in parameter_names:
            if offset + 4 > len(data):
                break
            value = struct.unpack_from(">f", data, offset)[0]
            values[name] = value
            offset += 4
        return values
