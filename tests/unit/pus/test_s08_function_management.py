"""
Tests for PUS Service 8  -  Function Management.
Implements: SVF-DEV-191
"""

import pytest
from svf.pus.tc import PusTcPacket
from svf.pus.services import PusService8


@pytest.mark.requirement("SVF-DEV-191")
def test_s8_is_perform_predicate() -> None:
    perform = PusTcPacket(apid=0x100, sequence_count=1, service=8, subservice=1)
    other = PusTcPacket(apid=0x100, sequence_count=2, service=8, subservice=2)

    assert PusService8.is_perform(perform)
    assert not PusService8.is_perform(other)


@pytest.mark.requirement("SVF-DEV-191")
def test_s8_build_and_parse_perform_roundtrip_no_args() -> None:
    app_data = PusService8.build_perform(function_id=1)
    tc = PusTcPacket(apid=0x100, sequence_count=1, service=8, subservice=1, app_data=app_data)

    function_id, args = PusService8.parse_perform(tc)
    assert function_id == 1
    assert args == b""


@pytest.mark.requirement("SVF-DEV-191")
def test_s8_build_and_parse_perform_roundtrip_with_args() -> None:
    app_data = PusService8.build_perform(function_id=42, args=b"\x01\x02\x03")
    tc = PusTcPacket(apid=0x100, sequence_count=1, service=8, subservice=1, app_data=app_data)

    function_id, args = PusService8.parse_perform(tc)
    assert function_id == 42
    assert args == b"\x01\x02\x03"


@pytest.mark.requirement("SVF-DEV-191")
def test_s8_parse_perform_matches_openobsw_layout() -> None:
    """function_id(2 BE) | args_len(1) | args  -  matches src/pus/s8.c."""
    app_data = (3).to_bytes(2, "big") + bytes([2]) + b"\xAA\xBB"
    tc = PusTcPacket(apid=0x100, sequence_count=1, service=8, subservice=1, app_data=app_data)

    function_id, args = PusService8.parse_perform(tc)
    assert function_id == 3
    assert args == b"\xAA\xBB"


@pytest.mark.requirement("SVF-DEV-191")
def test_s8_parse_perform_too_short_raises() -> None:
    tc = PusTcPacket(apid=0x100, sequence_count=1, service=8, subservice=1, app_data=b"\x00")
    with pytest.raises(ValueError):
        PusService8.parse_perform(tc)


@pytest.mark.requirement("SVF-DEV-191")
def test_s8_build_perform_rejects_oversized_args() -> None:
    with pytest.raises(ValueError):
        PusService8.build_perform(function_id=1, args=b"\x00" * 256)
