"""
SVF EPS Subsystem Unit Tests
Verifies individual SolarArray, Battery, and PCDU FMU behaviour.
Implements: EPS-001 through EPS-010
"""

import pytest
from pathlib import Path
from svf.abstractions import SyncProtocol
from svf.parameter_store import ParameterStore
from svf.command_store import CommandStore
from svf.fmu_equipment import FmuEquipment

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


class _NoSync(SyncProtocol):
    def reset(self) -> None: pass
    def publish_ready(self, model_id: str, t: float) -> None: pass
    def wait_for_ready(self, expected: list[str], timeout: float) -> bool: return True


@pytest.fixture
def sync() -> _NoSync:
    return _NoSync()


@pytest.fixture
def store() -> ParameterStore:
    return ParameterStore()


@pytest.fixture
def cmd_store() -> CommandStore:
    return CommandStore()


@pytest.fixture
def solar(sync: _NoSync, store: ParameterStore,
          cmd_store: CommandStore) -> FmuEquipment:
    eq = FmuEquipment(
        fmu_path=MODELS / "SolarArrayFmu.fmu",
        equipment_id="solar_array",
        sync_protocol=sync,
        store=store,
        command_store=cmd_store,
        parameter_map=SOLAR_MAP,
    )
    eq.initialise()
    return eq


@pytest.fixture
def battery(sync: _NoSync, store: ParameterStore,
            cmd_store: CommandStore) -> FmuEquipment:
    eq = FmuEquipment(
        fmu_path=MODELS / "BatteryFmu.fmu",
        equipment_id="battery",
        sync_protocol=sync,
        store=store,
        command_store=cmd_store,
        parameter_map=BATTERY_MAP,
    )
    eq.initialise()
    return eq


@pytest.fixture
def pcdu(sync: _NoSync, store: ParameterStore,
         cmd_store: CommandStore) -> FmuEquipment:
    eq = FmuEquipment(
        fmu_path=MODELS / "PcduFmu.fmu",
        equipment_id="pcdu",
        sync_protocol=sync,
        store=store,
        command_store=cmd_store,
        parameter_map=PCDU_MAP,
    )
    eq.initialise()
    return eq


# ── Solar Array ───────────────────────────────────────────────────────────────

@pytest.mark.requirement("EPS-001")
def test_solar_power_proportional_to_illumination(
    solar: FmuEquipment
) -> None:
    """Generated power is proportional to illumination fraction."""
    solar.receive("eps.solar_array.illumination", 0.5)
    solar.do_step(0.0, 1.0)
    half = solar.read_port("eps.solar_array.generated_power")

    solar.receive("eps.solar_array.illumination", 1.0)
    solar.do_step(1.0, 1.0)
    full = solar.read_port("eps.solar_array.generated_power")

    assert full == pytest.approx(half * 2.0, rel=0.01)


@pytest.mark.requirement("EPS-002")
def test_solar_zero_power_in_eclipse(solar: FmuEquipment) -> None:
    """Zero illumination produces zero generated power."""
    solar.receive("eps.solar_array.illumination", 0.0)
    solar.do_step(0.0, 1.0)
    assert solar.read_port("eps.solar_array.generated_power") == pytest.approx(0.0)


@pytest.mark.requirement("EPS-003")
def test_solar_full_power_in_sunlight(solar: FmuEquipment) -> None:
    """Full illumination produces peak power (100W * 0.9 efficiency = 90W)."""
    solar.receive("eps.solar_array.illumination", 1.0)
    solar.do_step(0.0, 1.0)
    assert solar.read_port("eps.solar_array.generated_power") == pytest.approx(
        90.0, abs=1.0
    )


# ── Battery ───────────────────────────────────────────────────────────────────

@pytest.mark.requirement("EPS-004")
def test_battery_soc_decreases_when_discharging(battery: FmuEquipment) -> None:
    """Negative charge current decreases SoC."""
    battery.receive("eps.battery.charge_current_in", -5.0)
    battery.do_step(0.0, 1.0)
    soc_after = battery.read_port("eps.battery.soc")
    assert soc_after < 0.8


@pytest.mark.requirement("EPS-005")
def test_battery_soc_increases_when_charging(battery: FmuEquipment) -> None:
    """Positive charge current increases SoC."""
    battery.receive("eps.battery.charge_current_in", 5.0)
    battery.do_step(0.0, 1.0)
    soc_after = battery.read_port("eps.battery.soc")
    assert soc_after > 0.8


@pytest.mark.requirement("EPS-006")
def test_battery_voltage_within_lion_range(battery: FmuEquipment) -> None:
    """Battery voltage stays within Li-Ion range (3.0V to 4.2V)."""
    battery.receive("eps.battery.charge_current_in", 0.0)
    battery.do_step(0.0, 1.0)
    voltage = battery.read_port("eps.battery.voltage")
    assert 3.0 <= voltage <= 4.2


@pytest.mark.requirement("EPS-007")
def test_battery_soc_clamped_at_min(battery: FmuEquipment) -> None:
    """Battery SoC never falls below SOC_MIN (0.05)."""
    # Apply large discharge current for many steps
    for i in range(1000):
        battery.receive("eps.battery.charge_current_in", -100.0)
        battery.do_step(float(i), 1.0)
    assert battery.read_port("eps.battery.soc") >= 0.05


@pytest.mark.requirement("EPS-007")
def test_battery_soc_clamped_at_max(battery: FmuEquipment) -> None:
    """Battery SoC never exceeds SOC_MAX (1.0)."""
    for i in range(1000):
        battery.receive("eps.battery.charge_current_in", 100.0)
        battery.do_step(float(i), 1.0)
    assert battery.read_port("eps.battery.soc") <= 1.0


# ── PCDU ──────────────────────────────────────────────────────────────────────

@pytest.mark.requirement("EPS-008")
def test_pcdu_positive_current_when_generation_exceeds_load(
    pcdu: FmuEquipment,
) -> None:
    """Charge current positive when generation > load."""
    pcdu.receive("eps.solar_input", 90.0)
    pcdu.receive("eps.battery_voltage_in", 3.7)
    pcdu.receive("eps.load.power", 30.0)
    pcdu.do_step(0.0, 1.0)
    assert pcdu.read_port("eps.pcdu.charge_current") > 0.0


@pytest.mark.requirement("EPS-009")
def test_pcdu_negative_current_when_load_exceeds_generation(
    pcdu: FmuEquipment,
) -> None:
    """Charge current negative when load > generation."""
    pcdu.receive("eps.solar_input", 0.0)
    pcdu.receive("eps.battery_voltage_in", 3.7)
    pcdu.receive("eps.load.power", 30.0)
    pcdu.do_step(0.0, 1.0)
    assert pcdu.read_port("eps.pcdu.charge_current") < 0.0


@pytest.mark.requirement("EPS-010")
def test_pcdu_bus_voltage_equals_battery_voltage(pcdu: FmuEquipment) -> None:
    """Bus voltage equals battery voltage (simplified model)."""
    pcdu.receive("eps.solar_input", 50.0)
    pcdu.receive("eps.battery_voltage_in", 3.85)
    pcdu.receive("eps.load.power", 30.0)
    pcdu.do_step(0.0, 1.0)
    assert pcdu.read_port("eps.bus.voltage") == pytest.approx(3.85, abs=0.01)


# ── Decomposed EPS (Wiring Integration) ───────────────────────────────────────

@pytest.fixture
def eps_wired(sync: _NoSync, store: ParameterStore,
              cmd_store: CommandStore):  # type: ignore[no-untyped-def]
    """Full decomposed EPS wired via WiringMap."""
    from cyclonedds.domain import DomainParticipant
    from svf.simulation import SimulationMaster
    from svf.software_tick import SoftwareTickSource
    from svf.dds_sync import DdsSyncProtocol
    from svf.wiring import WiringLoader

    WIRING_FILE = Path(__file__).parent.parent.parent / "srdb" / "wiring" / "eps_wiring.yaml"
    participant = DomainParticipant()
    dds_sync = DdsSyncProtocol(participant)
    wired_store = ParameterStore()
    wired_cmd = CommandStore()

    solar = FmuEquipment(
        fmu_path=MODELS / "SolarArrayFmu.fmu",
        equipment_id="solar_array",
        sync_protocol=dds_sync,
        store=wired_store,
        command_store=wired_cmd,
        parameter_map=SOLAR_MAP,
    )
    battery = FmuEquipment(
        fmu_path=MODELS / "BatteryFmu.fmu",
        equipment_id="battery",
        sync_protocol=dds_sync,
        store=wired_store,
        command_store=wired_cmd,
        parameter_map=BATTERY_MAP,
    )
    pcdu = FmuEquipment(
        fmu_path=MODELS / "PcduFmu.fmu",
        equipment_id="pcdu",
        sync_protocol=dds_sync,
        store=wired_store,
        command_store=wired_cmd,
        parameter_map=PCDU_MAP,
    )

    equipment = {"solar_array": solar, "battery": battery, "pcdu": pcdu}
    wiring = WiringLoader(equipment).load(WIRING_FILE)

    master = SimulationMaster(
        tick_source=SoftwareTickSource(),
        sync_protocol=dds_sync,
        models=[solar, battery, pcdu],
        dt=1.0,
        stop_time=120.0,
        sync_timeout=5.0,
        wiring=wiring,
        command_store=wired_cmd,
    )
    return master, wired_store, wired_cmd


@pytest.mark.requirement("EPS-014", "EPS-016")
def test_decomposed_eps_charges_in_sunlight(eps_wired) -> None:  # type: ignore[no-untyped-def]
    """Decomposed EPS charges battery in full sunlight."""
    master, store, cmd_store = eps_wired
    cmd_store.inject("eps.solar_array.illumination", 1.0, source_id="test")
    cmd_store.inject("eps.load.power", 30.0, source_id="test")
    master.run()

    soc = store.read("eps.battery.soc")
    gen = store.read("eps.solar_array.generated_power")
    assert soc is not None and soc.value > 0.8
    assert gen is not None and gen.value == pytest.approx(90.0, abs=1.0)


@pytest.mark.requirement("EPS-015", "EPS-016")
def test_decomposed_eps_discharges_in_eclipse(eps_wired) -> None:  # type: ignore[no-untyped-def]
    """Decomposed EPS discharges battery in eclipse."""
    master, store, cmd_store = eps_wired
    cmd_store.inject("eps.solar_array.illumination", 0.0, source_id="test")
    cmd_store.inject("eps.load.power", 30.0, source_id="test")
    master.run()

    soc = store.read("eps.battery.soc")
    gen = store.read("eps.solar_array.generated_power")
    assert soc is not None and soc.value < 0.8
    assert gen is not None and gen.value == pytest.approx(0.0, abs=0.1)
