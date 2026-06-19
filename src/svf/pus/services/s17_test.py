"""PUS Service 17  -  Test (are-you-alive)."""

from __future__ import annotations

from svf.pus.tc import PusTcPacket
from svf.pus.tm import PusTmPacket


class PusService17:
    """
    PUS Service 17  -  Test.

    TC(17,1)  -  Are-you-alive test request
    TM(17,2)  -  Are-you-alive test response
    TC(17,3)  -  On-board connection test request
    TM(17,4)  -  On-board connection test response
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
        """TM(17,2)  -  Are-you-alive response."""
        return PusTmPacket(
            apid=tm_apid,
            sequence_count=sequence_count,
            service=17,
            subservice=2,
            timestamp=timestamp,
        )
