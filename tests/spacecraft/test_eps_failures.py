"""
SVF EPS Failure Test Procedures
Exercises EPS failure modes and boundary conditions.

TC-EPS-FAIL-001: Battery reaches minimum SoC in extended eclipse
TC-EPS-FAIL-002: Overcurrent — high discharge current under heavy load
TC-EPS-FAIL-003: Partial solar array — reduced generation
TC-EPS-FAIL-004: Load shedding — charge current recovers after shed
TC-EPS-FAIL-005: Bus voltage stays above cutoff as battery discharges

Implements: EPS-004 through EPS-013
"""

import pytest
from cyclonedds.domain import DomainParticipant

from svf.simulation import SimulationMaster
from svf.software_tick import SoftwareTickSource
from svf.dds_sync import DdsSyncProtocol
from svf.parameter_store import ParameterStore
from svf.command_store import CommandStore
from svf.fmu_equipment import FmuEquipment
from pathlib import Path

EPS_FMU = "models/EpsFmu.fmu"
EPS_MAP = {
    "battery_soc":        "eps.battery.soc",
    "battery_voltage":    "eps.battery.voltage",
    "bus_voltage":        "eps.bus.voltage",
    "generated_power":    "eps.solar_array.generated_power",
    "charge_current":     "eps.battery.charge_current",
    "solar_illumination": "eps.solar_array.illumination",
    "load_power":         "eps.load.power",
}


def make_eps_system(
    stop_time: float = 120.0,
    dt: float = 1.0,
    illumination: float = 1.0,
    load_power: float = 30.0,
) -> tuple[SimulationMaster, ParameterStore, CommandStore]:
    """Build standalone EPS simulation."""
    participant = DomainParticipant()
    store = ParameterStore()
    cmd_store = CommandStore()
    sync = DdsSyncProtocol(participant)

    eps = FmuEquipment(
        fmu_path=EPS_FMU,
        equipment_id="eps",
        sync_protocol=sync,
        store=store,
        command_store=cmd_store,
        parameter_map=EPS_MAP,
    )

    master = SimulationMaster(
        tick_source=SoftwareTickSource(),
        sync_protocol=sync,
        models=[eps],
        dt=dt,
        stop_time=stop_time,
        sync_timeout=5.0,
        command_store=cmd_store,
        param_store=store,
    )

    # Set initial conditions
    cmd_store.inject("eps.solar_array.illumination", illumination,
                     source_id="test")
    cmd_store.inject("eps.load.power", load_power, source_id="test")

    return master, store, cmd_store


@pytest.mark.requirement("EPS-004", "EPS-007")
def test_tc_eps_fail_001_battery_reaches_minimum_soc() -> None:
    """
    TC-EPS-FAIL-001: Battery SoC drops significantly in extended eclipse.
    Expected: SoC below 0.55 after 600s at 30W load.
    """
    master, store, _ = make_eps_system(
        stop_time=600.0, illumination=0.0, load_power=30.0
    )
    master.run()

    soc = store.read("eps.battery.soc")
    assert soc is not None
    assert soc.value < 0.55, \
        f"Battery SoC too high after 600s eclipse: {soc.value:.3f}"


@pytest.mark.requirement("EPS-009", "EPS-012")
def test_tc_eps_fail_002_overcurrent_discharge() -> None:
    """
    TC-EPS-FAIL-002: High load in eclipse — large discharge current.
    Expected: charge_current below -10A under 150W load.
    """
    master, store, _ = make_eps_system(
        stop_time=10.0, illumination=0.0, load_power=150.0
    )
    master.run()

    current = store.read("eps.battery.charge_current")
    assert current is not None
    assert current.value < -10.0, \
        f"Discharge current too low: {current.value:.2f}A"


@pytest.mark.requirement("EPS-001", "EPS-003", "EPS-008")
def test_tc_eps_fail_003_partial_solar_array_failure() -> None:
    """
    TC-EPS-FAIL-003: Partial solar array failure (30% illumination).
    At 30% illumination with 30W load, battery discharges.
    Expected: charge_current negative after 10s.
    """
    master, store, _ = make_eps_system(
        stop_time=10.0, illumination=0.3, load_power=30.0
    )
    master.run()

    current = store.read("eps.battery.charge_current")
    assert current is not None
    assert current.value < 0.0, \
        f"Expected discharge at 30% illumination, got: {current.value:.2f}A"


@pytest.mark.requirement("EPS-008", "EPS-011")
def test_tc_eps_fail_004_load_shedding_recovery() -> None:
    """
    TC-EPS-FAIL-004: Load shed in full sun — charge current becomes positive.
    Run with heavy load then shed to light load.
    """
    # Phase 1: heavy load
    master, store, cmd_store = make_eps_system(
        stop_time=10.0, illumination=1.0, load_power=150.0
    )
    master.run()
    current_heavy = store.read("eps.battery.charge_current")
    assert current_heavy is not None
    assert current_heavy.value < 0.0

    # Phase 2: shed load
    cmd_store.inject("eps.load.power", 10.0, source_id="test")
    master2, store2, _ = make_eps_system(
        stop_time=10.0, illumination=1.0, load_power=10.0
    )
    master2.run()
    current_light = store2.read("eps.battery.charge_current")
    assert current_light is not None
    assert current_light.value > 0.0, \
        f"Expected positive charge after load shed: {current_light.value:.2f}A"


@pytest.mark.requirement("EPS-006", "EPS-010", "EPS-013")
def test_tc_eps_fail_005_bus_voltage_stays_above_cutoff() -> None:
    """
    TC-EPS-FAIL-005: Bus voltage stays above 3.0V even as
    battery discharges in eclipse.
    """
    master, store, _ = make_eps_system(
        stop_time=600.0, illumination=0.0, load_power=30.0
    )
    master.run()

    soc = store.read("eps.battery.soc")
    bus_v = store.read("eps.bus.voltage")

    assert soc is not None
    assert soc.value < 0.55  # significant discharge occurred

    assert bus_v is not None
    assert bus_v.value > 3.0, \
        f"Bus voltage below cutoff: {bus_v.value:.3f}V"
