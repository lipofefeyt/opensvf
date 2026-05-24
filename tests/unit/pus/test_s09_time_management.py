"""
Tests for PUS Service 9 — Time Management.
Implements: SVF-DEV-162
"""

import struct
import pytest
from svf.pus.tc import PusTcPacket, PusTcBuilder, PusTcParser
from svf.pus.services import PusService9


@pytest.mark.requirement("SVF-DEV-162")
def test_s9_is_set_obt_detects_correct_tc() -> None:
    tc = PusTcPacket(apid=0x100, sequence_count=1, service=9, subservice=128,
                     app_data=struct.pack(">IH", 1000, 0))
    assert PusService9.is_set_obt(tc) is True


@pytest.mark.requirement("SVF-DEV-162")
def test_s9_is_set_obt_rejects_other_tc() -> None:
    tc = PusTcPacket(apid=0x100, sequence_count=1, service=17, subservice=1)
    assert PusService9.is_set_obt(tc) is False


@pytest.mark.requirement("SVF-DEV-162")
def test_s9_parse_set_obt_integer_seconds() -> None:
    """TC(9,128) with zero fine component parses to exact integer seconds."""
    tc = PusTcPacket(apid=0x100, sequence_count=1, service=9, subservice=128,
                     app_data=struct.pack(">IH", 3600, 0))
    assert PusService9.parse_set_obt(tc) == pytest.approx(3600.0)


@pytest.mark.requirement("SVF-DEV-162")
def test_s9_parse_set_obt_fractional_seconds() -> None:
    """TC(9,128) CUC fine component (0.5 s = 0x8000) parsed correctly."""
    tc = PusTcPacket(apid=0x100, sequence_count=1, service=9, subservice=128,
                     app_data=struct.pack(">IH", 100, 0x8000))
    assert PusService9.parse_set_obt(tc) == pytest.approx(100.5, abs=1e-4)


@pytest.mark.requirement("SVF-DEV-162")
def test_s9_parse_set_obt_short_app_data_raises() -> None:
    tc = PusTcPacket(apid=0x100, sequence_count=1, service=9, subservice=128,
                     app_data=b"\x00\x00\x00")
    with pytest.raises(ValueError, match="too short"):
        PusService9.parse_set_obt(tc)


@pytest.mark.requirement("SVF-DEV-162")
def test_s9_build_and_parse_roundtrip() -> None:
    """build_set_obt → parse_set_obt round-trip preserves OBT to 1/65536 s."""
    obt = 86400.75
    tc = PusService9.build_set_obt(obt, tc_apid=0x100, sequence_count=5)
    assert tc.service == 9
    assert tc.subservice == 128
    recovered = PusService9.parse_set_obt(tc)
    assert recovered == pytest.approx(obt, abs=1 / 65536)


@pytest.mark.requirement("SVF-DEV-162")
def test_s9_build_survives_wire_encode_decode() -> None:
    """TC(9,128) survives PusTcBuilder serialisation and PusTcParser parse."""
    obt = 1234.5
    tc = PusService9.build_set_obt(obt, tc_apid=0x100, sequence_count=7)
    raw = PusTcBuilder().build(tc)
    parsed = PusTcParser().parse(raw)
    recovered = PusService9.parse_set_obt(parsed)
    assert recovered == pytest.approx(obt, abs=1 / 65536)
