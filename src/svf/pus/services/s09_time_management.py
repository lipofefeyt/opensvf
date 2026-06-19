"""PUS Service 9  -  Time Management."""

from __future__ import annotations

import struct

from svf.pus.tc import PusTcPacket


class PusService9:
    """
    PUS Service 9  -  Time Management.

    TC(9,128)  -  Set On-Board Time (OBT) from CUC-4,2 timestamp.
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
