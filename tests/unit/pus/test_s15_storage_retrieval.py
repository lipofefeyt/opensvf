"""
Tests for PUS Service 15  -  On-Board Storage and Retrieval.
Implements: SVF-DEV-188
"""

import struct

import pytest
from svf.pus.tc import PusTcPacket
from svf.pus.services import PusService15


@pytest.mark.requirement("SVF-DEV-188")
def test_s15_is_enable_disable_retrieve_delete_predicates() -> None:
    enable = PusTcPacket(apid=0x100, sequence_count=1, service=15, subservice=1)
    disable = PusTcPacket(apid=0x100, sequence_count=2, service=15, subservice=2)
    retrieve = PusTcPacket(apid=0x100, sequence_count=3, service=15, subservice=3)
    delete = PusTcPacket(apid=0x100, sequence_count=4, service=15, subservice=9)
    other = PusTcPacket(apid=0x100, sequence_count=5, service=15, subservice=4)

    assert PusService15.is_enable(enable)
    assert PusService15.is_disable(disable)
    assert PusService15.is_retrieve(retrieve)
    assert PusService15.is_delete(delete)
    assert not PusService15.is_enable(other)
    assert not PusService15.is_disable(other)
    assert not PusService15.is_retrieve(other)
    assert not PusService15.is_delete(other)


@pytest.mark.requirement("SVF-DEV-188")
def test_s15_build_and_parse_enable_roundtrip() -> None:
    app_data = PusService15.build_enable(store_id=3)
    tc = PusTcPacket(apid=0x100, sequence_count=1, service=15, subservice=1, app_data=app_data)
    assert PusService15.parse_enable(tc) == 3


@pytest.mark.requirement("SVF-DEV-188")
def test_s15_build_and_parse_disable_roundtrip() -> None:
    app_data = PusService15.build_disable(store_id=3)
    tc = PusTcPacket(apid=0x100, sequence_count=1, service=15, subservice=2, app_data=app_data)
    assert PusService15.parse_disable(tc) == 3


@pytest.mark.requirement("SVF-DEV-188")
def test_s15_build_and_parse_retrieve_roundtrip() -> None:
    app_data = PusService15.build_retrieve(store_id=1, start_time=100, end_time=200)
    tc = PusTcPacket(apid=0x100, sequence_count=1, service=15, subservice=3, app_data=app_data)
    store_id, start_time, end_time = PusService15.parse_retrieve(tc)
    assert (store_id, start_time, end_time) == (1, 100, 200)


@pytest.mark.requirement("SVF-DEV-188")
def test_s15_build_and_parse_delete_roundtrip() -> None:
    app_data = PusService15.build_delete(store_id=1, start_time=50, end_time=75)
    tc = PusTcPacket(apid=0x100, sequence_count=1, service=15, subservice=9, app_data=app_data)
    store_id, start_time, end_time = PusService15.parse_delete(tc)
    assert (store_id, start_time, end_time) == (1, 50, 75)


@pytest.mark.requirement("SVF-DEV-188")
def test_s15_parse_retrieve_layout() -> None:
    """store_id(1) | start_time(4 BE) | end_time(4 BE)."""
    app_data = struct.pack(">BII", 2, 1000, 2000)
    tc = PusTcPacket(apid=0x100, sequence_count=1, service=15, subservice=3, app_data=app_data)
    assert PusService15.parse_retrieve(tc) == (2, 1000, 2000)


@pytest.mark.requirement("SVF-DEV-188")
def test_s15_parse_enable_too_short_raises() -> None:
    tc = PusTcPacket(apid=0x100, sequence_count=1, service=15, subservice=1, app_data=b"")
    with pytest.raises(ValueError):
        PusService15.parse_enable(tc)


@pytest.mark.requirement("SVF-DEV-188")
def test_s15_parse_retrieve_too_short_raises() -> None:
    tc = PusTcPacket(apid=0x100, sequence_count=1, service=15, subservice=3, app_data=b"\x01\x02")
    with pytest.raises(ValueError):
        PusService15.parse_retrieve(tc)
