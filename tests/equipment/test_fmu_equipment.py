"""
Tests for FmuEquipment.
Implements: SVF-DEV-004, SVF-DEV-014
"""

import pytest
from pathlib import Path

from cyclonedds.domain import DomainParticipant

from svf.core.fmu_equipment import FmuEquipment
from svf.core.equipment import PortDirection
from svf.core.abstractions import SyncProtocol
from svf.stores.parameter_store import ParameterStore
from svf.stores.command_store import CommandStore
from svf.ground.dds_sync import DdsSyncProtocol

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
    """Passthrough sync for unit tests."""
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


# ── Construction tests ────────────────────────────────────────────────────────

@pytest.mark.requirement("EQP-001","EQP-008")
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

@pytest.mark.requirement("SVF-DEV-007")
def test_fmu_equipment_missing_fmu(
    sync: _NoSync, store: ParameterStore
) -> None:
    """FileNotFoundError raised for missing FMU."""
    with pytest.raises(FileNotFoundError, match="FMU not found"):
        FmuEquipment(
            fmu_path="nonexistent.fmu",
            equipment_id="bad",
            sync_protocol=sync,
            store=store,
        )

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


# ── Step tests ────────────────────────────────────────────────────────────────

@pytest.mark.requirement("EQP-009")
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

@pytest.mark.requirement("EQP-006","SVF-DEV-014")
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