"""
Tests for PUS Service 6  -  Memory Management.
Implements: SVF-DEV-190
"""

import struct

import pytest
from svf.pus.tc import PusTcPacket, crc16
from svf.pus.services import PusService6


@pytest.mark.requirement("SVF-DEV-190")
def test_s6_is_load_check_dump_predicates() -> None:
    load = PusTcPacket(apid=0x100, sequence_count=1, service=6, subservice=2)
    check = PusTcPacket(apid=0x100, sequence_count=2, service=6, subservice=5)
    dump = PusTcPacket(apid=0x100, sequence_count=3, service=6, subservice=9)
    other = PusTcPacket(apid=0x100, sequence_count=4, service=6, subservice=1)

    assert PusService6.is_load(load)
    assert PusService6.is_check(check)
    assert PusService6.is_dump(dump)
    assert not PusService6.is_load(check)
    assert not PusService6.is_check(load)
    assert not PusService6.is_dump(load)
    assert not PusService6.is_load(other)


@pytest.mark.requirement("SVF-DEV-190")
def test_s6_build_and_parse_load_roundtrip() -> None:
    app_data = PusService6.build_load(0x1000, b"\xDE\xAD\xBE\xEF")
    tc = PusTcPacket(apid=0x100, sequence_count=1, service=6, subservice=2, app_data=app_data)

    start_addr, data = PusService6.parse_load(tc)
    assert start_addr == 0x1000
    assert data == b"\xDE\xAD\xBE\xEF"


@pytest.mark.requirement("SVF-DEV-190")
def test_s6_parse_load_matches_openobsw_layout() -> None:
    """start_addr(4 BE) | data_len(2 BE) | data  -  matches src/pus/s6.c."""
    app_data = struct.pack(">IH", 0x2000, 2) + b"\x01\x02"
    tc = PusTcPacket(apid=0x100, sequence_count=1, service=6, subservice=2, app_data=app_data)
    start_addr, data = PusService6.parse_load(tc)
    assert start_addr == 0x2000
    assert data == b"\x01\x02"


@pytest.mark.requirement("SVF-DEV-190")
def test_s6_parse_load_too_short_raises() -> None:
    tc = PusTcPacket(apid=0x100, sequence_count=1, service=6, subservice=2, app_data=b"\x00\x01")
    with pytest.raises(ValueError):
        PusService6.parse_load(tc)


@pytest.mark.requirement("SVF-DEV-190")
def test_s6_build_and_parse_check_roundtrip() -> None:
    app_data = PusService6.build_check(0x1000, 16, mem_id=1, expected_crc=0xABCD)
    tc = PusTcPacket(apid=0x100, sequence_count=1, service=6, subservice=5, app_data=app_data)

    start_addr, length, mem_id, expected_crc = PusService6.parse_check(tc)
    assert start_addr == 0x1000
    assert length == 16
    assert mem_id == 1
    assert expected_crc == 0xABCD


@pytest.mark.requirement("SVF-DEV-190")
def test_s6_build_and_parse_dump_roundtrip() -> None:
    app_data = PusService6.build_dump(0x1000, 8, mem_id=2)
    tc = PusTcPacket(apid=0x100, sequence_count=1, service=6, subservice=9, app_data=app_data)

    start_addr, length, mem_id = PusService6.parse_dump(tc)
    assert start_addr == 0x1000
    assert length == 8
    assert mem_id == 2


@pytest.mark.requirement("SVF-DEV-190")
def test_s6_dump_report_layout() -> None:
    tm = PusService6.dump_report(
        start_addr=0x1000, mem_id=3, data=b"\x01\x02\x03",
        tm_apid=0x101, sequence_count=1,
    )
    assert tm.service == 6
    assert tm.subservice == 6
    addr, mem_id = struct.unpack_from(">IB", tm.app_data)
    assert addr == 0x1000
    assert mem_id == 3
    assert tm.app_data[5:] == b"\x01\x02\x03"


@pytest.mark.requirement("SVF-DEV-190")
def test_s6_check_success_report_layout() -> None:
    tm = PusService6.check_success_report(
        start_addr=0x1000, length=16, tm_apid=0x101, sequence_count=1,
    )
    assert tm.service == 6
    assert tm.subservice == 10
    addr, length = struct.unpack_from(">IH", tm.app_data)
    assert addr == 0x1000
    assert length == 16


@pytest.mark.requirement("SVF-DEV-190")
def test_s6_check_failure_report_layout() -> None:
    tm = PusService6.check_failure_report(
        start_addr=0x1000, length=16, actual_crc=0x1234,
        tm_apid=0x101, sequence_count=1,
    )
    assert tm.service == 6
    assert tm.subservice == 11
    addr, length, actual_crc = struct.unpack_from(">IHH", tm.app_data)
    assert addr == 0x1000
    assert length == 16
    assert actual_crc == 0x1234


@pytest.mark.requirement("SVF-DEV-190")
def test_s6_compute_crc_matches_pus_crc16() -> None:
    """S6 check CRC uses the same CRC-16/CCITT as the PUS TC/TM headers."""
    data = b"the quick brown fox"
    assert PusService6.compute_crc(data) == crc16(data)
