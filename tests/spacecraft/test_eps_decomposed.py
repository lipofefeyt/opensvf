"""
SVF EPS Decomposed Validation Test Procedures
Validates the decomposed EPS: SolarArray + Battery + PCDU
connected via WiringMap.

Requirements verified: SVF-DEV-066
"""

import pytest
from pathlib import Path
from cyclonedds.domain import DomainParticipant

from svf.simulation import SimulationMaster
from svf.software_tick import SoftwareTickSource
from svf.dds_sync import DdsSyncProtocol
from svf.fmu_equipment import FmuEquipment
from svf.parameter_store import ParameterStore
from svf.command_store import CommandStore
from svf.wiring import WiringLoader
from svf.plugin.fixtures import FmuConfig

MODELS = Path(__file__).parent.parent.parent / "models"

SOLAR_MAP = {
    "solar_illumination": "eps.solar_array.illumination",
    "generated_power":    "eps.solar_array.generated_power",
    "array_voltage":      "eps.solar_array.voltage",
}

BATTERY_MAP = {
    "charge_current":  "eps.battery.charge_current_in",
    "battery_voltage": "eps.battery.voltage",
    "battery_soc":     "eps.battery.soc",
}

PCDU_MAP = {
    "generated_power":  "eps.solar_input",
    "battery_voltage":  "eps.battery_voltage_in",
    "load_power":       "eps.load.power",
    "bus_voltage":      "eps.bus.voltage",
    "charge_current":   "eps.pcdu.charge_current",
}

WIRING_FILE = Path(__file__).parent.parent.parent / "srdb" / "wiring" / "eps_wiring.yaml"


@pytest.fixture
def eps_simulation():  # type: ignore[no-untyped-def]
    """Full decomposed EPS simulation session."""
    participant = DomainParticipant()
    store = ParameterStore()
    cmd_store = CommandStore()
    sync = DdsSyncProtocol(participant)

    solar = FmuEquipment(
        fmu_path=MODELS / "SolarArrayFmu.fmu",
        equipment_id="solar_array",
        sync_protocol=sync,
        store=store,
        command_store=cmd_store,
        parameter_map=SOLAR_MAP,
    )
    battery = FmuEquipment(
        fmu_path=MODELS / "BatteryFmu.fmu",
        equipment_id="battery",
        sync_protocol=sync,
        store=store,
        command_store=cmd_store,
        parameter_map=BATTERY_MAP,
    )
    pcdu = FmuEquipment(
        fmu_path=MODELS / "PcduFmu.fmu",
        equipment_id="pcdu",
        sync_protocol=sync,
        store=store,
        command_store=cmd_store,
        parameter_map=PCDU_MAP,
    )

    equipment = {
        "solar_array": solar,
        "battery": battery,
        "pcdu": pcdu,
    }
    wiring = WiringLoader(equipment).load(WIRING_FILE)

    master = SimulationMaster(
        tick_source=SoftwareTickSource(),
        sync_protocol=sync,
        models=[solar, battery, pcdu],
        dt=1.0,
        stop_time=120.0,
        sync_timeout=5.0,
        wiring=wiring,
        command_store=cmd_store,
    )

    return master, store, cmd_store

@pytest.mark.requirement("EPS-014", "EPS-016")
def test_decomposed_eps_sunlight(eps_simulation) -> None:  # type: ignore[no-untyped-def]
    """Decomposed EPS charges battery in full sunlight."""
    master, store, cmd_store = eps_simulation

    cmd_store.inject("eps.solar_array.illumination", 1.0,
                     source_id="test")
    cmd_store.inject("eps.load.power", 30.0, source_id="test")

    master.run()

    soc = store.read("eps.battery.soc")
    gen = store.read("eps.solar_array.generated_power")
    bus = store.read("eps.bus.voltage")

    assert soc is not None
    assert gen is not None
    assert bus is not None
    assert soc.value > 0.8, f"SoC should increase: {soc.value:.3f}"
    assert gen.value == pytest.approx(90.0, abs=1.0)
    assert bus.value > 3.5

@pytest.mark.requirement("EPS-015", "EPS-016")
def test_decomposed_eps_eclipse(eps_simulation) -> None:  # type: ignore[no-untyped-def]
    """Decomposed EPS discharges battery in eclipse."""
    master, store, cmd_store = eps_simulation

    cmd_store.inject("eps.solar_array.illumination", 0.0,
                     source_id="test")
    cmd_store.inject("eps.load.power", 30.0, source_id="test")

    master.run()

    soc = store.read("eps.battery.soc")
    gen = store.read("eps.solar_array.generated_power")

    assert soc is not None
    assert gen is not None
    assert soc.value < 0.8, f"SoC should decrease: {soc.value:.3f}"
    assert gen.value == pytest.approx(0.0, abs=0.1)
