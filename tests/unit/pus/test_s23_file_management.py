"""
Tests for PUS Service 23  -  File Management.
Implements: SVF-DEV-189
"""

import struct

import pytest
from svf.pus.tc import PusTcPacket
from svf.pus.services import PusService23


@pytest.mark.requirement("SVF-DEV-189")
def test_s23_is_create_delete_report_predicates() -> None:
    create = PusTcPacket(apid=0x100, sequence_count=1, service=23, subservice=1)
    delete = PusTcPacket(apid=0x100, sequence_count=2, service=23, subservice=2)
    report = PusTcPacket(apid=0x100, sequence_count=3, service=23, subservice=3)
    other = PusTcPacket(apid=0x100, sequence_count=4, service=23, subservice=4)

    assert PusService23.is_create(create)
    assert PusService23.is_delete(delete)
    assert PusService23.is_report_attributes(report)
    assert not PusService23.is_create(other)
    assert not PusService23.is_delete(other)
    assert not PusService23.is_report_attributes(other)


@pytest.mark.requirement("SVF-DEV-189")
def test_s23_build_and_parse_create_roundtrip() -> None:
    app_data = PusService23.build_create("boot.log", size=1024)
    tc = PusTcPacket(apid=0x100, sequence_count=1, service=23, subservice=1, app_data=app_data)
    name, size = PusService23.parse_create(tc)
    assert name == "boot.log"
    assert size == 1024


@pytest.mark.requirement("SVF-DEV-189")
def test_s23_build_and_parse_delete_roundtrip() -> None:
    app_data = PusService23.build_delete("boot.log")
    tc = PusTcPacket(apid=0x100, sequence_count=1, service=23, subservice=2, app_data=app_data)
    assert PusService23.parse_delete(tc) == "boot.log"


@pytest.mark.requirement("SVF-DEV-189")
def test_s23_build_and_parse_report_attributes_roundtrip() -> None:
    app_data = PusService23.build_report_attributes("boot.log")
    tc = PusTcPacket(apid=0x100, sequence_count=1, service=23, subservice=3, app_data=app_data)
    assert PusService23.parse_report_attributes(tc) == "boot.log"


@pytest.mark.requirement("SVF-DEV-189")
def test_s23_parse_create_layout() -> None:
    """name_len(1) | name(...) | size(4 BE)."""
    name = b"a.bin"
    app_data = bytes([len(name)]) + name + struct.pack(">I", 42)
    tc = PusTcPacket(apid=0x100, sequence_count=1, service=23, subservice=1, app_data=app_data)
    parsed_name, size = PusService23.parse_create(tc)
    assert parsed_name == "a.bin"
    assert size == 42


@pytest.mark.requirement("SVF-DEV-189")
def test_s23_file_attribute_report_layout() -> None:
    tm = PusService23.file_attribute_report(
        name="boot.log", size=1024, tm_apid=0x101, sequence_count=1,
    )
    assert tm.service == 23
    assert tm.subservice == 4
    name_len = tm.app_data[0]
    name = tm.app_data[1:1 + name_len].decode("ascii")
    size, = struct.unpack_from(">I", tm.app_data, 1 + name_len)
    assert name == "boot.log"
    assert size == 1024


@pytest.mark.requirement("SVF-DEV-189")
def test_s23_parse_create_too_short_raises() -> None:
    tc = PusTcPacket(apid=0x100, sequence_count=1, service=23, subservice=1, app_data=b"")
    with pytest.raises(ValueError):
        PusService23.parse_create(tc)


@pytest.mark.requirement("SVF-DEV-189")
def test_s23_parse_create_truncated_raises() -> None:
    tc = PusTcPacket(
        apid=0x100, sequence_count=1, service=23, subservice=1,
        app_data=bytes([5]) + b"a.bin",  # missing 4-byte size field
    )
    with pytest.raises(ValueError):
        PusService23.parse_create(tc)


@pytest.mark.requirement("SVF-DEV-189")
def test_s23_build_create_rejects_oversized_name() -> None:
    with pytest.raises(ValueError):
        PusService23.build_create("x" * 256)
