"""PUS Service 15  -  On-Board Storage and Retrieval."""

from __future__ import annotations

import struct

from svf.pus.tc import PusTcPacket


class PusService15:
    """
    PUS Service 15  -  On-Board Storage and Retrieval.

    TC(15,1)  -  Enable storage in a packet store:  store_id(1)
    TC(15,2)  -  Disable storage in a packet store:  store_id(1)
    TC(15,3)  -  Start-by-time-range retrieval:      store_id(1) | start_time(4 BE) | end_time(4 BE)
    TC(15,9)  -  Delete packet store content by time range: store_id(1) | start_time(4 BE) | end_time(4 BE)

    Scoped deliberately to a single packet store per TC and a single numeric
    store_id (not the full ECSS-E-ST-70-41C packet-store-definition
    subservices) - opensvf defines this wire format itself, there is no
    external OBSW reference to match. Retrieval re-emits the original
    buffered TM packets rather than wrapping them in a dedicated report
    subservice, matching real S15 retrieval semantics.
    """

    @staticmethod
    def is_enable(tc: PusTcPacket) -> bool:
        return tc.service == 15 and tc.subservice == 1

    @staticmethod
    def is_disable(tc: PusTcPacket) -> bool:
        return tc.service == 15 and tc.subservice == 2

    @staticmethod
    def is_retrieve(tc: PusTcPacket) -> bool:
        return tc.service == 15 and tc.subservice == 3

    @staticmethod
    def is_delete(tc: PusTcPacket) -> bool:
        return tc.service == 15 and tc.subservice == 9

    @staticmethod
    def build_enable(store_id: int) -> bytes:
        """Build TC(15,1) application data."""
        return struct.pack(">B", store_id)

    @staticmethod
    def build_disable(store_id: int) -> bytes:
        """Build TC(15,2) application data."""
        return struct.pack(">B", store_id)

    @staticmethod
    def build_retrieve(store_id: int, start_time: int, end_time: int) -> bytes:
        """Build TC(15,3) application data."""
        return struct.pack(">BII", store_id, start_time, end_time)

    @staticmethod
    def build_delete(store_id: int, start_time: int, end_time: int) -> bytes:
        """Build TC(15,9) application data."""
        return struct.pack(">BII", store_id, start_time, end_time)

    @staticmethod
    def parse_enable(tc: PusTcPacket) -> int:
        """Parse TC(15,1) application data. Returns store_id."""
        if len(tc.app_data) < 1:
            raise ValueError(f"TC(15,1) app_data too short: {len(tc.app_data)} bytes")
        return tc.app_data[0]

    @staticmethod
    def parse_disable(tc: PusTcPacket) -> int:
        """Parse TC(15,2) application data. Returns store_id."""
        if len(tc.app_data) < 1:
            raise ValueError(f"TC(15,2) app_data too short: {len(tc.app_data)} bytes")
        return tc.app_data[0]

    @staticmethod
    def parse_retrieve(tc: PusTcPacket) -> tuple[int, int, int]:
        """Parse TC(15,3) application data. Returns (store_id, start_time, end_time)."""
        if len(tc.app_data) < 9:
            raise ValueError(f"TC(15,3) app_data too short: {len(tc.app_data)} bytes")
        return struct.unpack_from(">BII", tc.app_data)

    @staticmethod
    def parse_delete(tc: PusTcPacket) -> tuple[int, int, int]:
        """Parse TC(15,9) application data. Returns (store_id, start_time, end_time)."""
        if len(tc.app_data) < 9:
            raise ValueError(f"TC(15,9) app_data too short: {len(tc.app_data)} bytes")
        return struct.unpack_from(">BII", tc.app_data)
