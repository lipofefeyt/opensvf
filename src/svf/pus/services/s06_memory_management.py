"""PUS Service 6  -  Memory Management."""

from __future__ import annotations

import struct

from svf.pus.tc import PusTcPacket, crc16
from svf.pus.tm import PusTmPacket


class PusService6:
    """
    PUS Service 6  -  Memory Management.

    TC(6,2)   -  Load memory area:  start_addr(4 BE) | data_len(2 BE) | data(...)
    TC(6,5)   -  Check memory area: start_addr(4 BE) | length(2 BE) | mem_id(1) | expected_crc(2 BE)
    TC(6,9)   -  Dump memory area:  start_addr(4 BE) | length(2 BE) | mem_id(1)
    TM(6,6)   -  Memory dump data:  start_addr(4 BE) | mem_id(1) | data(...)
    TM(6,10)  -  Memory check success: start_addr(4 BE) | length(2 BE)
    TM(6,11)  -  Memory check failure: start_addr(4 BE) | length(2 BE) | actual_crc(2 BE)

    Byte layout matches the openobsw C reference implementation
    (src/pus/s6.c) so TC/TM built here are wire-compatible with a real
    OBSW binary over the pipe/socket wire protocol.
    """

    @staticmethod
    def is_load(tc: PusTcPacket) -> bool:
        return tc.service == 6 and tc.subservice == 2

    @staticmethod
    def is_check(tc: PusTcPacket) -> bool:
        return tc.service == 6 and tc.subservice == 5

    @staticmethod
    def is_dump(tc: PusTcPacket) -> bool:
        return tc.service == 6 and tc.subservice == 9

    @staticmethod
    def build_load(start_addr: int, data: bytes) -> bytes:
        """Build TC(6,2) application data."""
        return struct.pack(">IH", start_addr, len(data)) + data

    @staticmethod
    def parse_load(tc: PusTcPacket) -> tuple[int, bytes]:
        """Parse TC(6,2) application data. Returns (start_addr, data)."""
        if len(tc.app_data) < 6:
            raise ValueError(f"TC(6,2) app_data too short: {len(tc.app_data)} bytes")
        start_addr, data_len = struct.unpack_from(">IH", tc.app_data)
        if len(tc.app_data) < 6 + data_len:
            raise ValueError(f"TC(6,2) app_data truncated: expected {6 + data_len} bytes")
        return start_addr, tc.app_data[6:6 + data_len]

    @staticmethod
    def build_check(start_addr: int, length: int, mem_id: int, expected_crc: int) -> bytes:
        """Build TC(6,5) application data."""
        return struct.pack(">IHBH", start_addr, length, mem_id, expected_crc)

    @staticmethod
    def parse_check(tc: PusTcPacket) -> tuple[int, int, int, int]:
        """Parse TC(6,5) application data. Returns (start_addr, length, mem_id, expected_crc)."""
        if len(tc.app_data) < 9:
            raise ValueError(f"TC(6,5) app_data too short: {len(tc.app_data)} bytes")
        return struct.unpack_from(">IHBH", tc.app_data)

    @staticmethod
    def build_dump(start_addr: int, length: int, mem_id: int) -> bytes:
        """Build TC(6,9) application data."""
        return struct.pack(">IHB", start_addr, length, mem_id)

    @staticmethod
    def parse_dump(tc: PusTcPacket) -> tuple[int, int, int]:
        """Parse TC(6,9) application data. Returns (start_addr, length, mem_id)."""
        if len(tc.app_data) < 7:
            raise ValueError(f"TC(6,9) app_data too short: {len(tc.app_data)} bytes")
        return struct.unpack_from(">IHB", tc.app_data)

    @staticmethod
    def dump_report(
        start_addr: int, mem_id: int, data: bytes,
        tm_apid: int, sequence_count: int, timestamp: int = 0,
    ) -> PusTmPacket:
        """TM(6,6)  -  Memory dump data."""
        app_data = struct.pack(">IB", start_addr, mem_id) + data
        return PusTmPacket(
            apid=tm_apid, sequence_count=sequence_count,
            service=6, subservice=6, timestamp=timestamp, app_data=app_data,
        )

    @staticmethod
    def check_success_report(
        start_addr: int, length: int,
        tm_apid: int, sequence_count: int, timestamp: int = 0,
    ) -> PusTmPacket:
        """TM(6,10)  -  Memory check success."""
        app_data = struct.pack(">IH", start_addr, length)
        return PusTmPacket(
            apid=tm_apid, sequence_count=sequence_count,
            service=6, subservice=10, timestamp=timestamp, app_data=app_data,
        )

    @staticmethod
    def check_failure_report(
        start_addr: int, length: int, actual_crc: int,
        tm_apid: int, sequence_count: int, timestamp: int = 0,
    ) -> PusTmPacket:
        """TM(6,11)  -  Memory check failure."""
        app_data = struct.pack(">IHH", start_addr, length, actual_crc)
        return PusTmPacket(
            apid=tm_apid, sequence_count=sequence_count,
            service=6, subservice=11, timestamp=timestamp, app_data=app_data,
        )

    @staticmethod
    def compute_crc(data: bytes) -> int:
        """CRC-16/CCITT over a memory region, matching openobsw's obsw_crc16_ccitt."""
        return crc16(data)
