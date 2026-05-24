"""PUS Service 5 — Event Reporting."""

from __future__ import annotations

import struct

from svf.pus.tm import PusTmPacket


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
