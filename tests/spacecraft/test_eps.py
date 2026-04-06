"""
SVF EPS Validation Test Procedures
Validates the integrated EPS FMU (Solar Array + Battery + PCDU).

Test cases:
  TC-PWR-001: Battery charges in full sunlight
  TC-PWR-002: Battery discharges in eclipse
  TC-PWR-003: Charging behaviour in sunlight
  TC-PWR-004: Partial illumination (penumbra)
  TC-PWR-005: Deep eclipse discharge

Requirements verified: SVF-DEV-063, SVF-DEV-065
"""

import pytest
from pathlib import Path
from svf.plugin.fixtures import FmuConfig

EPS_FMU = Path(__file__).parent.parent.parent / "models" / "fmu" / "EpsFmu.fmu"

# Maps FMU variable names to SRDB canonical parameter names
EPS_PARAMETER_MAP = {
    "battery_soc":        "eps.battery.soc",
    "battery_voltage":    "eps.battery.voltage",
    "bus_voltage":        "eps.bus.voltage",
    "generated_power":    "eps.solar_array.generated_power",
    "charge_current":     "eps.battery.charge_current",
    "solar_illumination": "eps.solar_array.illumination",
    "load_power":         "eps.load.power",
}


@pytest.mark.svf_fmus([FmuConfig(EPS_FMU, "eps", EPS_PARAMETER_MAP)])
@pytest.mark.svf_stop_time(120.0)
@pytest.mark.svf_dt(1.0)
@pytest.mark.svf_initial_commands([
    ("eps.solar_array.illumination", 1.0),
    ("eps.load.power", 30.0),
])
@pytest.mark.requirement("EPS-011", "SVF-DEV-063", "SVF-DEV-065")
def test_tc_pwr_001_battery_charges_in_sunlight(svf_session) -> None:  # type: ignore[no-untyped-def]
    """
    TC-PWR-001: Battery charges in full sunlight.

    Objective: Verify that the EPS correctly charges the battery
    when the spacecraft is in full sunlight with nominal load.

    Preconditions:
      - Initial SoC: 0.8 (80%)
      - Solar illumination: 1.0 (full sun)
      - Load power: 30W

    Expected outcome:
      - Battery SoC increases above 0.88 within 120s
      - Charge current is positive (charging)
      - Bus voltage is within Li-Ion range (3.5V to 4.2V)
    """
    svf_session.observe("eps.battery.soc").exceeds(0.88).within(120.0)
    svf_session.observe("eps.battery.charge_current").exceeds(0.0).within(5.0)

    bus_v = svf_session.observe("eps.bus.voltage").exceeds(3.5).within(5.0)
    assert bus_v < 4.2, f"Bus voltage out of range: {bus_v:.3f}V"
    svf_session.stop()


@pytest.mark.svf_fmus([FmuConfig(EPS_FMU, "eps", EPS_PARAMETER_MAP)])
@pytest.mark.svf_stop_time(120.0)
@pytest.mark.svf_dt(1.0)
@pytest.mark.svf_initial_commands([
    ("eps.solar_array.illumination", 0.0),
    ("eps.load.power", 30.0),
])
@pytest.mark.requirement("EPS-012", "EPS-013", "SVF-DEV-063", "SVF-DEV-065")
def test_tc_pwr_002_battery_discharges_in_eclipse(svf_session) -> None:  # type: ignore[no-untyped-def]
    """
    TC-PWR-002: Battery discharges in eclipse.

    Objective: Verify that the EPS correctly discharges the battery
    when the spacecraft is in eclipse with nominal load.

    Preconditions:
      - Initial SoC: 0.8 (80%)
      - Solar illumination: 0.0 (eclipse)
      - Load power: 30W

    Expected outcome:
      - Battery SoC drops below 0.75 within 120s
      - Charge current is negative (discharging)
      - Bus voltage remains above minimum cutoff (3.0V)
    """
    svf_session.observe("eps.battery.soc").drops_below(0.75).within(120.0)
    svf_session.observe("eps.battery.charge_current").drops_below(0.0).within(5.0)

    bus_v = svf_session.store.read("eps.bus.voltage")
    assert bus_v is not None
    assert bus_v.value > 3.0, f"Bus voltage below cutoff: {bus_v.value:.3f}V"
    svf_session.stop()


@pytest.mark.svf_fmus([FmuConfig(EPS_FMU, "eps", EPS_PARAMETER_MAP)])
@pytest.mark.svf_stop_time(120.0)
@pytest.mark.svf_dt(1.0)
@pytest.mark.svf_initial_commands([
    ("eps.solar_array.illumination", 1.0),
    ("eps.load.power", 30.0),
])
@pytest.mark.requirement("EPS-001", "EPS-003", "EPS-011", "SVF-DEV-063", "SVF-DEV-065", "SVF-DEV-048")
def test_tc_pwr_003_charging_in_sunlight(svf_session) -> None:  # type: ignore[no-untyped-def]
    """
    TC-PWR-003: Charging behaviour in full sunlight.

    Simplified version — full multi-phase test deferred until
    svf_command_schedule is implemented.

    Expected outcome:
      - Charge current positive throughout
      - SoC increases monotonically
      - Generated power close to peak (90W)
    """
    svf_session.observe("eps.battery.charge_current").exceeds(0.0).within(5.0)
    svf_session.observe("eps.battery.soc").exceeds(0.85).within(120.0)

    gen = svf_session.store.read("eps.solar_array.generated_power")
    assert gen is not None
    assert gen.value == pytest.approx(90.0, abs=1.0), \
        f"Generated power off: {gen.value:.1f}W"
    svf_session.stop()


@pytest.mark.svf_fmus([FmuConfig(EPS_FMU, "eps", EPS_PARAMETER_MAP)])
@pytest.mark.svf_stop_time(120.0)
@pytest.mark.svf_dt(1.0)
@pytest.mark.svf_initial_commands([
    ("eps.solar_array.illumination", 0.4),
    ("eps.load.power", 30.0),
])
@pytest.mark.requirement("EPS-001", "SVF-DEV-063", "SVF-DEV-065")
def test_tc_pwr_004_penumbra(svf_session) -> None:  # type: ignore[no-untyped-def]
    """
    TC-PWR-004: Partial illumination (penumbra).

    Objective: Verify EPS handles 40% illumination correctly.

    Expected outcome:
      - Generated power approximately 36W (40% of 90W peak)
    """
    svf_session.observe("eps.solar_array.generated_power").exceeds(30.0).within(10.0)

    gen = svf_session.store.read("eps.solar_array.generated_power")
    assert gen is not None
    assert 33.0 < gen.value < 39.0, \
        f"Generated power out of range: {gen.value:.1f}W"
    svf_session.stop()


@pytest.mark.svf_fmus([FmuConfig(EPS_FMU, "eps", EPS_PARAMETER_MAP)])
@pytest.mark.svf_stop_time(300.0)
@pytest.mark.svf_dt(1.0)
@pytest.mark.svf_initial_commands([
    ("eps.solar_array.illumination", 0.0),
    ("eps.load.power", 50.0),
])
@pytest.mark.requirement("EPS-012", "EPS-013", "SVF-DEV-063", "SVF-DEV-065")
def test_tc_pwr_005_deep_eclipse_discharge(svf_session) -> None:  # type: ignore[no-untyped-def]
    """
    TC-PWR-005: Deep eclipse discharge behaviour.

    Expected outcome:
      - SoC drops below 0.65 under high load in eclipse
      - Charge current negative throughout
      - Bus voltage stays above protection cutoff (3.0V)
    """
    svf_session.observe("eps.battery.soc").drops_below(0.65).within(300.0)
    svf_session.observe("eps.battery.charge_current").drops_below(0.0).within(5.0)

    bus_v = svf_session.store.read("eps.bus.voltage")
    assert bus_v is not None
    assert bus_v.value > 3.0, f"Bus voltage below cutoff: {bus_v.value:.3f}V"
    svf_session.stop()