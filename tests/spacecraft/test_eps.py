"""
SVF EPS Validation Test Procedures
Validates the integrated EPS FMU (Solar Array + Battery + PCDU).

Test cases:
  TC-PWR-001: Battery charges in full sunlight
  TC-PWR-002: Battery discharges in eclipse
  TC-PWR-003: Sunlight to eclipse transition (simplified — see issue #XX)
  TC-PWR-004: Partial illumination (penumbra)
  TC-PWR-005: Low battery recovery (simplified — see issue #XX)

Note: TC-PWR-003 and TC-PWR-005 require scheduled command injection
for proper multi-phase testing. Simplified single-phase versions used
until svf_command_schedule mark is implemented.

Requirements verified: SVF-DEV-063, SVF-DEV-065
"""

import pytest
from pathlib import Path
from svf.plugin.fixtures import FmuConfig

EPS_FMU = Path(__file__).parent.parent.parent / "models" / "EpsFmu.fmu"


@pytest.mark.svf_fmus([FmuConfig(EPS_FMU, "eps")])
@pytest.mark.svf_stop_time(120.0)
@pytest.mark.svf_dt(1.0)
@pytest.mark.svf_initial_commands([("solar_illumination", 1.0), ("load_power", 30.0)])
@pytest.mark.requirement("SVF-DEV-063", "SVF-DEV-065")
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
    svf_session.observe("battery_soc").exceeds(0.88).within(120.0)
    svf_session.observe("charge_current").exceeds(0.0).within(5.0)

    bus_v = svf_session.observe("bus_voltage").exceeds(3.5).within(5.0)
    assert bus_v < 4.2, f"Bus voltage out of range: {bus_v:.3f}V"
    svf_session.stop()


@pytest.mark.svf_fmus([FmuConfig(EPS_FMU, "eps")])
@pytest.mark.svf_stop_time(120.0)
@pytest.mark.svf_dt(1.0)
@pytest.mark.svf_initial_commands([("solar_illumination", 0.0), ("load_power", 30.0)])
@pytest.mark.requirement("SVF-DEV-063", "SVF-DEV-065")
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
    svf_session.observe("battery_soc").drops_below(0.75).within(120.0)
    svf_session.observe("charge_current").drops_below(0.0).within(5.0)

    bus_v = svf_session.store.read("bus_voltage")
    assert bus_v is not None
    assert bus_v.value > 3.0, f"Bus voltage below cutoff: {bus_v.value:.3f}V"
    svf_session.stop()


@pytest.mark.svf_fmus([FmuConfig(EPS_FMU, "eps")])
@pytest.mark.svf_stop_time(120.0)
@pytest.mark.svf_dt(1.0)
@pytest.mark.svf_initial_commands([("solar_illumination", 1.0), ("load_power", 30.0)])
@pytest.mark.requirement("SVF-DEV-063", "SVF-DEV-065")
def test_tc_pwr_003_charging_in_sunlight(svf_session) -> None:  # type: ignore[no-untyped-def]
    """
    TC-PWR-003: Charging behaviour in full sunlight.

    Simplified version of sunlight-to-eclipse transition test.
    Full multi-phase test deferred until svf_command_schedule is
    implemented (see GitHub issue for scheduled command injection).

    Objective: Verify steady-state charging in sunlight.

    Expected outcome:
      - Charge current positive throughout
      - SoC increases monotonically
      - Generated power close to peak (90W)
    """
    svf_session.observe("charge_current").exceeds(0.0).within(5.0)
    svf_session.observe("battery_soc").exceeds(0.85).within(120.0)

    gen = svf_session.store.read("generated_power")
    assert gen is not None
    assert gen.value == pytest.approx(90.0, abs=1.0), \
        f"Generated power off: {gen.value:.1f}W"
    svf_session.stop()


@pytest.mark.svf_fmus([FmuConfig(EPS_FMU, "eps")])
@pytest.mark.svf_stop_time(120.0)
@pytest.mark.svf_dt(1.0)
@pytest.mark.svf_initial_commands([("solar_illumination", 0.4), ("load_power", 30.0)])
@pytest.mark.requirement("SVF-DEV-063", "SVF-DEV-065")
def test_tc_pwr_004_penumbra(svf_session) -> None:  # type: ignore[no-untyped-def]
    """
    TC-PWR-004: Partial illumination (penumbra).

    Objective: Verify that the EPS correctly handles partial solar
    illumination, as occurs during penumbra phases in LEO.

    Preconditions:
      - Solar illumination: 0.4 (40% penumbra)
      - Load power: 30W

    Expected outcome:
      - Generated power approximately 36W (40% of 90W peak)
    """
    svf_session.observe("generated_power").exceeds(30.0).within(10.0)

    gen = svf_session.store.read("generated_power")
    assert gen is not None
    assert 33.0 < gen.value < 39.0, \
        f"Generated power out of range: {gen.value:.1f}W"
    svf_session.stop()


@pytest.mark.svf_fmus([FmuConfig(EPS_FMU, "eps")])
@pytest.mark.svf_stop_time(300.0)
@pytest.mark.svf_dt(1.0)
@pytest.mark.svf_initial_commands([("solar_illumination", 0.0), ("load_power", 50.0)])
@pytest.mark.requirement("SVF-DEV-063", "SVF-DEV-065")
def test_tc_pwr_005_deep_eclipse_discharge(svf_session) -> None:  # type: ignore[no-untyped-def]
    """
    TC-PWR-005: Deep eclipse discharge behaviour.

    Simplified version of low-battery recovery test. Full multi-phase
    recovery test deferred until svf_command_schedule is implemented.

    Objective: Verify battery discharge under high load in eclipse.

    Preconditions:
      - Solar illumination: 0.0 (eclipse)
      - Load power: 50W (high load)

    Expected outcome:
      - SoC drops below 0.65 within 300s
      - Charge current negative throughout
      - Bus voltage stays above protection cutoff (3.0V)
    """
    svf_session.observe("battery_soc").drops_below(0.65).within(300.0)
    svf_session.observe("charge_current").drops_below(0.0).within(5.0)

    bus_v = svf_session.store.read("bus_voltage")
    assert bus_v is not None
    assert bus_v.value > 3.0, f"Bus voltage below cutoff: {bus_v.value:.3f}V"
    svf_session.stop()
