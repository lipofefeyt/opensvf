"""
Tests for PUS Service 3  -  Housekeeping.
Implements: PUS-005
"""

import pytest
from svf.pus.services import PusService3, HkReportDefinition


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
    s3.disable(0)
    assert s3._definitions[0].enabled


@pytest.mark.requirement("PUS-005")
def test_s3_unknown_report_returns_none() -> None:
    """generate_report returns None for unknown report ID."""
    s3 = PusService3()
    result = s3.generate_report(
        report_id=99, parameter_values={}, tm_apid=0x100, sequence_count=1,
    )
    assert result is None
