"""
Tests for PUS Service 20  -  On-Board Parameter Management.
Implements: PUS-008
"""

import pytest
import struct
from svf.pus.tc import PusTcPacket, PusTcBuilder, PusTcParser
from svf.pus.tm import PusTmParser, PusTmBuilder
from svf.pus.services import PusService20


@pytest.fixture
def tc_s20_set() -> PusTcPacket:
    return PusTcPacket(
        apid=0x100, sequence_count=2,
        service=20, subservice=1,
        app_data=struct.pack(">Hf", 0x2021, 0.15),
    )


@pytest.fixture
def tc_s20_get() -> PusTcPacket:
    return PusTcPacket(
        apid=0x100, sequence_count=3,
        service=20, subservice=3,
        app_data=struct.pack(">H", 0x2021),
    )


@pytest.mark.requirement("PUS-008")
def test_s20_parse_set_parameter(tc_s20_set: PusTcPacket) -> None:
    param_id, value = PusService20.parse_set_parameter(tc_s20_set)
    assert param_id == 0x2021
    assert value == pytest.approx(0.15, abs=1e-5)


@pytest.mark.requirement("PUS-008")
def test_s20_parse_get_parameter(tc_s20_get: PusTcPacket) -> None:
    param_id = PusService20.parse_get_parameter(tc_s20_get)
    assert param_id == 0x2021


@pytest.mark.requirement("PUS-008")
def test_s20_parameter_value_report() -> None:
    tm = PusService20.parameter_value_report(
        parameter_id=0x2021, value=1500.0, tm_apid=0x101, sequence_count=1,
    )
    assert tm.service == 20
    assert tm.subservice == 4
    param_id, value = struct.unpack_from(">Hf", tm.app_data)
    assert param_id == 0x2021
    assert value == pytest.approx(1500.0, abs=0.1)


@pytest.mark.requirement("PUS-008")
def test_s20_roundtrip_set_and_report() -> None:
    """S20 set TC then value report TM  -  full roundtrip."""
    builder = PusTcBuilder()
    parser = PusTcParser()
    tm_builder = PusTmBuilder()
    tm_parser = PusTmParser()

    tc = PusTcPacket(
        apid=0x100, sequence_count=42,
        service=20, subservice=1,
        app_data=struct.pack(">Hf", 0x2021, 0.15),
    )
    raw_tc = builder.build(tc)
    parsed_tc = parser.parse(raw_tc)
    param_id, value = PusService20.parse_set_parameter(parsed_tc)
    assert param_id == 0x2021
    assert value == pytest.approx(0.15, abs=1e-5)

    tm = PusService20.parameter_value_report(
        parameter_id=param_id, value=value, tm_apid=0x101, sequence_count=1,
    )
    raw_tm = tm_builder.build(tm)
    parsed_tm = tm_parser.parse(raw_tm)
    pid, val = struct.unpack_from(">Hf", parsed_tm.app_data)
    assert pid == 0x2021
    assert val == pytest.approx(0.15, abs=1e-5)
