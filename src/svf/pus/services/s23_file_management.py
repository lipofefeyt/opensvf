"""PUS Service 23  -  File Management."""

from __future__ import annotations

import struct

from svf.pus.tc import PusTcPacket
from svf.pus.tm import PusTmPacket


class PusService23:
    """
    PUS Service 23  -  File Management.

    TC(23,1)  -  Create file:            name_len(1) | name(...) | size(4 BE)
    TC(23,2)  -  Delete file:            name_len(1) | name(...)
    TC(23,3)  -  Report file attributes: name_len(1) | name(...)
    TM(23,4)  -  File attribute report:  name_len(1) | name(...) | size(4 BE)

    Scoped deliberately to create/delete/report-attributes against an
    in-memory virtual file table (no write-data subservice) - opensvf
    defines this wire format itself, there is no external OBSW reference
    to match. TC(23,1)'s size field declares the file's reported size at
    creation time (there being no write-data subservice to grow it later).
    """

    @staticmethod
    def is_create(tc: PusTcPacket) -> bool:
        return tc.service == 23 and tc.subservice == 1

    @staticmethod
    def is_delete(tc: PusTcPacket) -> bool:
        return tc.service == 23 and tc.subservice == 2

    @staticmethod
    def is_report_attributes(tc: PusTcPacket) -> bool:
        return tc.service == 23 and tc.subservice == 3

    @staticmethod
    def build_create(name: str, size: int = 0) -> bytes:
        """Build TC(23,1) application data."""
        name_bytes = name.encode("ascii")
        if len(name_bytes) > 255:
            raise ValueError(f"S23 file name too long: {len(name_bytes)} bytes (max 255)")
        return bytes([len(name_bytes)]) + name_bytes + struct.pack(">I", size)

    @staticmethod
    def build_delete(name: str) -> bytes:
        """Build TC(23,2) application data."""
        name_bytes = name.encode("ascii")
        if len(name_bytes) > 255:
            raise ValueError(f"S23 file name too long: {len(name_bytes)} bytes (max 255)")
        return bytes([len(name_bytes)]) + name_bytes

    @staticmethod
    def build_report_attributes(name: str) -> bytes:
        """Build TC(23,3) application data."""
        name_bytes = name.encode("ascii")
        if len(name_bytes) > 255:
            raise ValueError(f"S23 file name too long: {len(name_bytes)} bytes (max 255)")
        return bytes([len(name_bytes)]) + name_bytes

    @staticmethod
    def parse_create(tc: PusTcPacket) -> tuple[str, int]:
        """Parse TC(23,1) application data. Returns (name, size)."""
        if len(tc.app_data) < 1:
            raise ValueError(f"TC(23,1) app_data too short: {len(tc.app_data)} bytes")
        name_len = tc.app_data[0]
        if len(tc.app_data) < 1 + name_len + 4:
            raise ValueError(f"TC(23,1) app_data truncated: expected {1 + name_len + 4} bytes")
        name = tc.app_data[1:1 + name_len].decode("ascii")
        size, = struct.unpack_from(">I", tc.app_data, 1 + name_len)
        return name, size

    @staticmethod
    def parse_delete(tc: PusTcPacket) -> str:
        """Parse TC(23,2) application data. Returns name."""
        return PusService23._parse_name_only(tc, "TC(23,2)")

    @staticmethod
    def parse_report_attributes(tc: PusTcPacket) -> str:
        """Parse TC(23,3) application data. Returns name."""
        return PusService23._parse_name_only(tc, "TC(23,3)")

    @staticmethod
    def _parse_name_only(tc: PusTcPacket, label: str) -> str:
        if len(tc.app_data) < 1:
            raise ValueError(f"{label} app_data too short: {len(tc.app_data)} bytes")
        name_len = tc.app_data[0]
        if len(tc.app_data) < 1 + name_len:
            raise ValueError(f"{label} app_data truncated: expected {1 + name_len} bytes")
        return tc.app_data[1:1 + name_len].decode("ascii")

    @staticmethod
    def file_attribute_report(
        name: str, size: int,
        tm_apid: int, sequence_count: int, timestamp: int = 0,
    ) -> PusTmPacket:
        """TM(23,4)  -  File attribute report."""
        name_bytes = name.encode("ascii")
        app_data = bytes([len(name_bytes)]) + name_bytes + struct.pack(">I", size)
        return PusTmPacket(
            apid=tm_apid, sequence_count=sequence_count,
            service=23, subservice=4, timestamp=timestamp, app_data=app_data,
        )
