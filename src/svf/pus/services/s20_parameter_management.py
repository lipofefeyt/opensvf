"""PUS Service 20  -  On-Board Parameter Management."""

from __future__ import annotations

import struct

from svf.pus.tc import PusTcPacket
from svf.pus.tm import PusTmPacket


class PusService20:
    """
    PUS Service 20  -  On-Board Parameter Management.

    TC(20,1)  -  Set parameter value
    TC(20,3)  -  Get parameter value
    TM(20,4)  -  Parameter value report
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
        """TM(20,4)  -  Parameter value report."""
        app_data = struct.pack(">Hf", parameter_id, value)
        return PusTmPacket(
            apid=tm_apid,
            sequence_count=sequence_count,
            service=20,
            subservice=4,
            timestamp=timestamp,
            app_data=app_data,
        )
