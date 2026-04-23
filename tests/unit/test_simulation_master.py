"""
Tests for SimulationMaster, FmuEquipment, NativeEquipment and CsvLogger.
Implements: SVF-DEV-001, SVF-DEV-002, SVF-DEV-005, SVF-DEV-006, SVF-DEV-007,
            SVF-DEV-010, SVF-DEV-013, SVF-DEV-014, SVF-DEV-015, SVF-DEV-016
"""

import pytest
from pathlib import Path

from cyclonedds.domain import DomainParticipant

from svf.sim.simulation import SimulationMaster, SimulationError
from svf.core.abstractions import SyncProtocol
from svf.sim.software_tick import SoftwareTickSource
from svf.core.fmu_equipment import FmuEquipment
from svf.core.native_equipment import NativeEquipment
from svf.core.equipment import PortDefinition, PortDirection
from svf.stores.parameter_store import ParameterStore
from svf.stores.command_store import CommandStore
from svf.logging import CsvLogger

FMU_PATH = Path(__file__).parent.parent.parent / "mission_mysat1" / "SimpleCounter.fmu"


class _PassthroughSync(SyncProtocol):
    def reset(self) -> None: pass
    def publish_ready(self, model_id: str, t: float) -> None: pass
    def wait_for_ready(self, expected: list[str], timeout: float) -> bool: return True


@pytest.fixture
def store() -> ParameterStore:
    return ParameterStore()


@pytest.fixture
def cmd_store() -> CommandStore:
    return CommandStore()


@pytest.fixture
def sync() -> _PassthroughSync:
    return _PassthroughSync()


# ── NativeEquipment tests ─────────────────────────────────────────────────────

@pytest.mark.requirement("SVF-DEV-015", "EQP-010")
def test_native_equipment_step(
    store: ParameterStore,
    cmd_store: CommandStore,
    sync: _PassthroughSync,
) -> None:
    """NativeEquipment step function is called correctly."""
    results: list[float] = []

    def step(eq: NativeEquipment, t: float, dt: float) -> None:
        results.append(round(t + dt, 9))
        eq.write_port("value", round(t + dt, 9))

    eq = NativeEquipment(
        equipment_id="rec",
        ports=[PortDefinition("value", PortDirection.OUT)],
        step_fn=step,
        sync_protocol=sync,
        store=store,
        command_store=cmd_store,
    )
    eq.initialise()
    eq.on_tick(t=0.0, dt=0.1)
    assert results == [pytest.approx(0.1)]
    assert store.read("value") is not None
    assert store.read("value").value == pytest.approx(0.1)  # type: ignore[union-attr]


# ── FmuEquipment tests ────────────────────────────────────────────────────────

@pytest.mark.requirement("SVF-DEV-014")
def test_fmu_equipment_initialises(
    store: ParameterStore,
    cmd_store: CommandStore,
    sync: _PassthroughSync,
) -> None:
    """FmuEquipment loads and initialises without error."""
    eq = FmuEquipment(
        fmu_path=FMU_PATH,
        equipment_id="counter",
        sync_protocol=sync,
        store=store,
        command_store=cmd_store,
    )
    eq.initialise()
    assert "counter" in eq.ports
    eq.teardown()


@pytest.mark.requirement("SVF-DEV-014", "EQP-006")
def test_fmu_equipment_on_tick_writes_store(
    store: ParameterStore,
    cmd_store: CommandStore,
    sync: _PassthroughSync,
) -> None:
    """FmuEquipment on_tick writes output to ParameterStore."""
    eq = FmuEquipment(
        fmu_path=FMU_PATH,
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


@pytest.mark.requirement("SVF-DEV-007")
def test_fmu_equipment_missing_fmu(
    store: ParameterStore,
    cmd_store: CommandStore,
    sync: _PassthroughSync,
) -> None:
    """FmuEquipment raises FileNotFoundError for missing FMU."""
    with pytest.raises(FileNotFoundError, match="FMU not found"):
        FmuEquipment(
            fmu_path="nonexistent.fmu",
            equipment_id="bad",
            sync_protocol=sync,
            store=store,
        )


# ── SimulationMaster tests ────────────────────────────────────────────────────

@pytest.mark.requirement("SVF-DEV-009", "SVF-DEV-002", "SVF-DEV-006", "SVF-DEV-013", "SVF-DEV-016", "SVF-DEV-001")
def test_simulation_master_runs(
    store: ParameterStore,
    cmd_store: CommandStore,
    sync: _PassthroughSync,
) -> None:
    """SimulationMaster completes a 10-step run."""
    results: list[float] = []

    def step(eq: NativeEquipment, t: float, dt: float) -> None:
        results.append(round(t + dt, 9))
        eq.write_port("value", round(t + dt, 9))

    master = SimulationMaster(
        tick_source=SoftwareTickSource(),
        sync_protocol=sync,
        models=[NativeEquipment(
            "rec",
            [PortDefinition("value", PortDirection.OUT)],
            step,
            sync,
            store,
            cmd_store,
        )],
        dt=0.1,
        stop_time=1.0,
    )
    master.run()
    assert len(results) == 10
    assert results[-1] == pytest.approx(1.0)


@pytest.mark.requirement("SVF-DEV-002", "SVF-DEV-014")
def test_simulation_master_with_fmu(
    store: ParameterStore,
    cmd_store: CommandStore,
    sync: _PassthroughSync,
) -> None:
    """SimulationMaster runs correctly with FmuEquipment."""
    master = SimulationMaster(
        tick_source=SoftwareTickSource(),
        sync_protocol=sync,
        models=[FmuEquipment(FMU_PATH, "counter", sync, store, cmd_store)],
        dt=0.1,
        stop_time=1.0,
    )
    master.run()
    assert master.time == pytest.approx(0.9)
    entry = store.read("counter")
    assert entry is not None
    assert entry.value == pytest.approx(1.0)


@pytest.mark.requirement("SVF-DEV-016")
def test_simulation_master_no_models(sync: _PassthroughSync) -> None:
    """SimulationMaster raises SimulationError if no models provided."""
    with pytest.raises(SimulationError, match="at least one"):
        SimulationMaster(
            tick_source=SoftwareTickSource(),
            sync_protocol=sync,
            models=[],
            dt=0.1,
            stop_time=1.0,
        )


@pytest.mark.requirement("SVF-DEV-006")
def test_simulation_master_context_manager(
    store: ParameterStore,
    cmd_store: CommandStore,
    sync: _PassthroughSync,
) -> None:
    """SimulationMaster tears down cleanly via context manager."""
    def step(eq: NativeEquipment, t: float, dt: float) -> None:
        eq.write_port("value", round(t + dt, 9))

    with SimulationMaster(
        tick_source=SoftwareTickSource(),
        sync_protocol=sync,
        models=[NativeEquipment(
            "simple",
            [PortDefinition("value", PortDirection.OUT)],
            step,
            sync,
            store,
            cmd_store,
        )],
        dt=0.1,
        stop_time=0.5,
    ) as master:
        master.run()
    assert master.time == pytest.approx(0.4)


# ── CsvLogger tests ───────────────────────────────────────────────────────────

@pytest.mark.requirement("SVF-DEV-005")
def test_csv_logger_creates_file(tmp_path: Path) -> None:
    """CsvLogger creates a CSV file with correct headers."""
    csv_logger = CsvLogger(output_dir=tmp_path, run_id="test")
    csv_logger.open(["counter"])
    csv_logger.record(time=0.1, outputs={"counter": 0.1})
    csv_logger.close()
    files = list(tmp_path.glob("test_*.csv"))
    assert len(files) == 1
    content = files[0].read_text()
    assert "time,counter" in content
    assert "0.1,0.1" in content


@pytest.mark.requirement("SVF-DEV-005")
def test_csv_logger_record_before_open() -> None:
    """CsvLogger raises RuntimeError if record called before open."""
    csv_logger = CsvLogger()
    with pytest.raises(RuntimeError, match="not open"):
        csv_logger.record(time=0.1, outputs={"counter": 0.1})
