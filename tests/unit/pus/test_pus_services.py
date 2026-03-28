"""
Tests for PUS service catalogue S1, S3, S5, S17, S20.
Implements: PUS-005, PUS-006, PUS-007, PUS-008, PUS-009
"""

import pytest
import struct
from svf.pus.tc import PusTcPacket, PusTcBuilder, PusTcParser
from svf.pus.tm import PusTmPacket, PusTmBuilder, PusTmParser
from svf.pus.services import (
    PusService1, PusService3, PusService5, PusService17, PusService20,
    HkReportDefinition, EventSeverity,
)


@pytest.fixture
def tc_s17() -> PusTcPacket:
    """TC(17,1) are-you-alive."""
    return PusTcPacket(
        apid=0x100, sequence_count=1,
        service=17, subservice=1,
    )


@pytest.fixture
def tc_s20_set() -> PusTcPacket:
    """TC(20,1) set parameter."""
    return PusTcPacket(
        apid=0x100, sequence_count=2,
        service=20, subservice=1,
        app_data=struct.pack(">Hf", 0x2021, 0.15),
    )


@pytest.fixture
def tc_s20_get() -> PusTcPacket:
    """TC(20,3) get parameter."""
    return PusTcPacket(
        apid=0x100, sequence_count=3,
        service=20, subservice=3,
        app_data=struct.pack(">H", 0x2021),
    )


# ── Service 1 tests ───────────────────────────────────────────────────────────

@pytest.mark.requirement("PUS-009")
def test_s1_acceptance_success(tc_s17: PusTcPacket) -> None:
    """TM(1,1) acceptance success carries TC APID and sequence count."""
    tm = PusService1.acceptance_success(tc_s17, tm_apid=0x101, sequence_count=1)
    assert tm.service == 1
    assert tm.subservice == 1
    apid, seq = struct.unpack_from(">HH", tm.app_data)
    assert apid == tc_s17.apid
    assert seq == tc_s17.sequence_count


@pytest.mark.requirement("PUS-009")
def test_s1_acceptance_failure(tc_s17: PusTcPacket) -> None:
    """TM(1,2) acceptance failure carries failure code."""
    tm = PusService1.acceptance_failure(
        tc_s17, tm_apid=0x101, sequence_count=1, failure_code=0x0001
    )
    assert tm.subservice == 2
    _, _, code = struct.unpack_from(">HHH", tm.app_data)
    assert code == 0x0001


@pytest.mark.requirement("PUS-009")
def test_s1_completion_success(tc_s17: PusTcPacket) -> None:
    """TM(1,7) completion success."""
    tm = PusService1.completion_success(tc_s17, tm_apid=0x101, sequence_count=2)
    assert tm.subservice == 7


@pytest.mark.requirement("PUS-009")
def test_s1_completion_failure(tc_s17: PusTcPacket) -> None:
    """TM(1,8) completion failure."""
    tm = PusService1.completion_failure(
        tc_s17, tm_apid=0x101, sequence_count=2, failure_code=0x0002
    )
    assert tm.subservice == 8


# ── Service 3 tests ───────────────────────────────────────────────────────────

@pytest.mark.requirement("PUS-005")
def test_s3_define_and_generate_report() -> None:
    """TC(3,1) defines report, TM(3,25) generated with correct values."""
    s3 = PusService3()
    defn = HkReportDefinition(
        report_id=1,
        parameter_names=["eps.battery.soc", "eps.bus.voltage"],
        period_s=1.0,
    )
    s3.define_report(defn)

    tm = s3.generate_report(
        report_id=1,
        parameter_values={"eps.battery.soc": 0.87, "eps.bus.voltage": 3.95},
        tm_apid=0x100,
        sequence_count=1,
    )
    assert tm is not None
    assert tm.service == 3
    assert tm.subservice == 25

    values = PusService3.parse_report(tm, defn.parameter_names)
    assert values["eps.battery.soc"] == pytest.approx(0.87, abs=1e-5)
    assert values["eps.bus.voltage"] == pytest.approx(3.95, abs=1e-5)


@pytest.mark.requirement("PUS-005")
def test_s3_enable_disable() -> None:
    """TC(3,5) enables, TC(3,6) disables periodic generation."""
    s3 = PusService3()
    defn = HkReportDefinition(report_id=1, parameter_names=["eps.battery.soc"])
    s3.define_report(defn)

    assert not s3._definitions[1].enabled
    s3.enable(1)
    assert s3._definitions[1].enabled
    s3.disable(1)
    assert not s3._definitions[1].enabled


@pytest.mark.requirement("PUS-005")
def test_s3_essential_hk_always_enabled() -> None:
    """Essential HK reports cannot be disabled."""
    s3 = PusService3()
    defn = HkReportDefinition(report_id=0, parameter_names=["eps.battery.soc"])
    s3.add_essential(defn)

    assert s3._definitions[0].enabled
    s3.disable(0)  # should not disable essential
    assert s3._definitions[0].enabled


@pytest.mark.requirement("PUS-005")
def test_s3_unknown_report_returns_none() -> None:
    """generate_report returns None for unknown report ID."""
    s3 = PusService3()
    result = s3.generate_report(
        report_id=99,
        parameter_values={},
        tm_apid=0x100,
        sequence_count=1,
    )
    assert result is None


# ── Service 5 tests ───────────────────────────────────────────────────────────

@pytest.mark.requirement("PUS-006")
def test_s5_informative_event() -> None:
    """TM(5,1) informative event generated correctly."""
    tm = PusService5.report(
        severity=EventSeverity.INFORMATIVE,
        event_id=0x0001,
        tm_apid=0x100,
        sequence_count=1,
    )
    assert tm.service == 5
    assert tm.subservice == 1
    event_id = struct.unpack_from(">H", tm.app_data)[0]
    assert event_id == 0x0001


@pytest.mark.requirement("PUS-006")
def test_s5_high_severity_event() -> None:
    """TM(5,4) high severity event generated correctly."""
    tm = PusService5.report(
        severity=EventSeverity.HIGH,
        event_id=0x00FF,
        tm_apid=0x100,
        sequence_count=1,
        auxiliary_data=b"\x01\x02",
    )
    assert tm.subservice == 4
    assert tm.app_data[2:] == b"\x01\x02"


@pytest.mark.requirement("PUS-006")
def test_s5_invalid_severity_raises() -> None:
    """Invalid severity raises ValueError."""
    with pytest.raises(ValueError, match="severity"):
        PusService5.report(
            severity=5, event_id=1,
            tm_apid=0x100, sequence_count=1
        )


# ── Service 17 tests ──────────────────────────────────────────────────────────

@pytest.mark.requirement("PUS-007")
def test_s17_are_you_alive_detected(tc_s17: PusTcPacket) -> None:
    """is_are_you_alive() correctly identifies TC(17,1)."""
    assert PusService17.is_are_you_alive(tc_s17) is True


@pytest.mark.requirement("PUS-007")
def test_s17_are_you_alive_response(tc_s17: PusTcPacket) -> None:
    """TM(17,2) response generated correctly."""
    tm = PusService17.are_you_alive_response(tm_apid=0x101, sequence_count=1)
    assert tm.service == 17
    assert tm.subservice == 2


@pytest.mark.requirement("PUS-007")
def test_s17_non_alive_tc_not_detected() -> None:
    """TC with different service not identified as are-you-alive."""
    tc = PusTcPacket(apid=0x100, sequence_count=1, service=3, subservice=25)
    assert PusService17.is_are_you_alive(tc) is False


# ── Service 20 tests ──────────────────────────────────────────────────────────

@pytest.mark.requirement("PUS-008")
def test_s20_parse_set_parameter(tc_s20_set: PusTcPacket) -> None:
    """TC(20,1) parsed to parameter_id and value."""
    param_id, value = PusService20.parse_set_parameter(tc_s20_set)
    assert param_id == 0x2021
    assert value == pytest.approx(0.15, abs=1e-5)


@pytest.mark.requirement("PUS-008")
def test_s20_parse_get_parameter(tc_s20_get: PusTcPacket) -> None:
    """TC(20,3) parsed to parameter_id."""
    param_id = PusService20.parse_get_parameter(tc_s20_get)
    assert param_id == 0x2021


@pytest.mark.requirement("PUS-008")
def test_s20_parameter_value_report() -> None:
    """TM(20,4) carries parameter_id and value."""
    tm = PusService20.parameter_value_report(
        parameter_id=0x2021,
        value=1500.0,
        tm_apid=0x101,
        sequence_count=1,
    )
    assert tm.service == 20
    assert tm.subservice == 4
    param_id, value = struct.unpack_from(">Hf", tm.app_data)
    assert param_id == 0x2021
    assert value == pytest.approx(1500.0, abs=0.1)


@pytest.mark.requirement("PUS-008")
def test_s20_roundtrip_set_and_report() -> None:
    """S20 set TC then value report TM — full roundtrip."""
    builder = PusTcBuilder()
    parser = PusTcParser()
    tm_builder = PusTmBuilder()
    tm_parser = PusTmParser()

    # Ground builds TC(20,1)
    tc = PusTcPacket(
        apid=0x100, sequence_count=42,
        service=20, subservice=1,
        app_data=struct.pack(">Hf", 0x2021, 0.15),
    )
    raw_tc = builder.build(tc)

    # OBC parses TC
    parsed_tc = parser.parse(raw_tc)
    param_id, value = PusService20.parse_set_parameter(parsed_tc)
    assert param_id == 0x2021
    assert value == pytest.approx(0.15, abs=1e-5)

    # OBC generates TM(20,4)
    tm = PusService20.parameter_value_report(
        parameter_id=param_id,
        value=value,
        tm_apid=0x101,
        sequence_count=1,
    )
    raw_tm = tm_builder.build(tm)

    # Ground parses TM
    parsed_tm = tm_parser.parse(raw_tm)
    pid, val = struct.unpack_from(">Hf", parsed_tm.app_data)
    assert pid == 0x2021
    assert val == pytest.approx(0.15, abs=1e-5)
