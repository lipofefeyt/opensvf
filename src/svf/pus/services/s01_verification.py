"""PUS Service 1 — Request Verification."""

from __future__ import annotations

import struct

from svf.pus.tc import PusTcPacket
from svf.pus.tm import PusTmPacket


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
