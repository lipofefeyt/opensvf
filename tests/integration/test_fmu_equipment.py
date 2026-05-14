"""
Integration tests for FmuEquipment and SimulationMaster with FMU models.
Requires compiled FMU binaries in models/.
Implements: SVF-DEV-004, SVF-DEV-007, SVF-DEV-014, SVF-DEV-063, SVF-DEV-065,
            SVF-DEV-066, EQP-007, EQP-008, EQP-009, EQP-012
"""

import pytest
from pathlib import Path

from svf.core.fmu_equipment import FmuEquipment
from svf.core.native_equipment import NativeEquipment
from svf.core.equipment import PortDefinition, PortDirection
from svf.core.abstractions import SyncProtocol
from svf.stores.parameter_store import ParameterStore
from svf.stores.command_store import CommandStore
from svf.sim.simulation import SimulationMaster
from svf.sim.software_tick import SoftwareTickSource

EPS_FMU = Path(__file__).parent.parent.parent / "models" / "EpsFmu.fmu"
COUNTER_FMU = Path(__file__).parent.parent.parent / "models" / "SimpleCounter.fmu"

EPS_MAP = {
    "battery_soc":        "eps.battery.soc",
    "battery_voltage":    "eps.battery.voltage",
    "bus_voltage":        "eps.bus.voltage",
    "generated_power":    "eps.solar_array.generated_power",
    "charge_current":     "eps.battery.charge_current",
    "solar_illumination": "eps.solar_array.illumination",
    "load_power":         "eps.load.power",
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


# ── FmuEquipment construction ─────────────────────────────────────────────────

@pytest.mark.requirement("EQP-001", "EQP-008", "SVF-DEV-066")
def test_fmu_equipment_ports_declared(
    sync: _NoSync, store: ParameterStore, cmd_store: CommandStore
) -> None:
    """FmuEquipment declares ports from FMU model description."""
    eq = FmuEquipment(
        fmu_path=EPS_FMU,
        equipment_id="eps",
        sync_protocol=sync,
        store=store,
        command_store=cmd_store,
        parameter_map=EPS_MAP,
    )
    port_names = list(eq.ports.keys())
    assert "eps.battery.soc" in port_names
    assert "eps.solar_array.illumination" in port_names


@pytest.mark.requirement("EQP-008")
def test_fmu_equipment_port_directions(
    sync: _NoSync, store: ParameterStore, cmd_store: CommandStore
) -> None:
    """Output FMU variables are OUT ports, inputs are IN ports."""
    eq = FmuEquipment(
        fmu_path=EPS_FMU,
        equipment_id="eps",
        sync_protocol=sync,
        store=store,
        command_store=cmd_store,
        parameter_map=EPS_MAP,
    )
    assert eq.ports["eps.battery.soc"].direction == PortDirection.OUT
    assert eq.ports["eps.solar_array.illumination"].direction == PortDirection.IN


@pytest.mark.requirement("EQP-008")
def test_fmu_equipment_no_map(
    sync: _NoSync, store: ParameterStore, cmd_store: CommandStore
) -> None:
    """FmuEquipment works without parameter_map using raw FMU names."""
    eq = FmuEquipment(
        fmu_path=EPS_FMU,
        equipment_id="eps",
        sync_protocol=sync,
        store=store,
        command_store=cmd_store,
    )
    assert "battery_soc" in eq.ports
    assert "solar_illumination" in eq.ports


# ── EQP-007: parameter_map translation ───────────────────────────────────────

@pytest.mark.requirement("EQP-007")
def test_parameter_map_translates_port_names(
    sync: _NoSync, store: ParameterStore, cmd_store: CommandStore
) -> None:
    """FmuEquipment translates FMU variable names to canonical port names."""
    eq = FmuEquipment(
        fmu_path=EPS_FMU,
        equipment_id="eps",
        sync_protocol=sync,
        store=store,
        command_store=cmd_store,
        parameter_map=EPS_MAP,
    )
    assert "eps.battery.soc" in eq.ports
    assert "battery_soc" not in eq.ports


@pytest.mark.requirement("EQP-007")
def test_parameter_map_fallback_to_raw_name(
    sync: _NoSync, store: ParameterStore, cmd_store: CommandStore
) -> None:
    """Without parameter_map, raw FMU variable names are used as port names."""
    eq = FmuEquipment(
        fmu_path=EPS_FMU,
        equipment_id="eps",
        sync_protocol=sync,
        store=store,
        command_store=cmd_store,
    )
    assert "battery_soc" in eq.ports
    assert "eps.battery.soc" not in eq.ports


# ── FmuEquipment step ─────────────────────────────────────────────────────────

@pytest.mark.requirement("EQP-009", "SVF-DEV-063", "SVF-DEV-065")
def test_fmu_equipment_step(
    sync: _NoSync, store: ParameterStore, cmd_store: CommandStore
) -> None:
    """FmuEquipment steps correctly and OUT ports update."""
    eq = FmuEquipment(
        fmu_path=EPS_FMU,
        equipment_id="eps",
        sync_protocol=sync,
        store=store,
        command_store=cmd_store,
        parameter_map=EPS_MAP,
    )
    eq.initialise()
    eq.receive("eps.solar_array.illumination", 1.0)
    eq.receive("eps.load.power", 30.0)
    eq.do_step(t=0.0, dt=1.0)

    soc = eq.read_port("eps.battery.soc")
    gen = eq.read_port("eps.solar_array.generated_power")
    assert soc > 0.0
    assert gen == pytest.approx(90.0, abs=1.0)
    eq.teardown()


@pytest.mark.requirement("EQP-006", "SVF-DEV-014")
def test_fmu_equipment_on_tick_writes_store(
    sync: _NoSync, store: ParameterStore, cmd_store: CommandStore
) -> None:
    """on_tick() writes OUT ports to ParameterStore."""
    eq = FmuEquipment(
        fmu_path=COUNTER_FMU,
        equipment_id="counter",
        sync_protocol=sync,
        store=store,
        command_store=cmd_store,
    )
    eq.initialise()
    eq.on_tick(t=0.0, dt=0.1)

    entry = store.read("counter")
    assert entry is not None
    assert entry.value == pytest.approx(0.1)
    eq.teardown()


@pytest.mark.requirement("SVF-DEV-014")
def test_fmu_equipment_initialises(
    sync: _NoSync, store: ParameterStore, cmd_store: CommandStore
) -> None:
    """FmuEquipment loads and initialises without error."""
    eq = FmuEquipment(
        fmu_path=COUNTER_FMU,
        equipment_id="counter",
        sync_protocol=sync,
        store=store,
        command_store=cmd_store,
    )
    eq.initialise()
    assert "counter" in eq.ports
    eq.teardown()


# ── EQP-012: teardown ─────────────────────────────────────────────────────────

@pytest.mark.requirement("EQP-012")
def test_fmu_teardown_safe_without_initialise(
    sync: _NoSync, store: ParameterStore, cmd_store: CommandStore
) -> None:
    """FmuEquipment teardown() is safe even if initialise() was never called."""
    eq = FmuEquipment(
        fmu_path=EPS_FMU,
        equipment_id="eps",
        sync_protocol=sync,
        store=store,
        command_store=cmd_store,
    )
    eq.teardown()  # should not raise


# ── SimulationMaster with FMU ─────────────────────────────────────────────────

@pytest.mark.requirement("SVF-DEV-001", "SVF-DEV-002", "SVF-DEV-014")
def test_simulation_master_with_fmu(
    sync: _NoSync, store: ParameterStore, cmd_store: CommandStore
) -> None:
    """SimulationMaster runs correctly with FmuEquipment."""
    master = SimulationMaster(
        tick_source=SoftwareTickSource(),
        sync_protocol=sync,
        models=[FmuEquipment(COUNTER_FMU, "counter", sync, store, cmd_store)],
        dt=0.1,
        stop_time=1.0,
    )
    master.run()
    assert master.time == pytest.approx(0.9)
    entry = store.read("counter")
    assert entry is not None
    assert entry.value == pytest.approx(1.0)
