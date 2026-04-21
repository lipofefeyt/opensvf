"""
SVF Integration Test — Full Lockstep Loop
Exercises the complete stack with Equipment-based models.
Implements: SVF-DEV-010, SVF-DEV-012, SVF-DEV-014, SVF-DEV-015, SVF-DEV-016
"""

import pytest
from pathlib import Path

from cyclonedds.domain import DomainParticipant

from svf.sim.simulation import SimulationMaster, SimulationError
from svf.core.abstractions import SyncProtocol
from svf.sim.software_tick import SoftwareTickSource
from svf.ground.dds_sync import DdsSyncProtocol
from svf.core.fmu_equipment import FmuEquipment
from svf.core.native_equipment import NativeEquipment
from svf.core.equipment import PortDefinition, PortDirection
from svf.stores.parameter_store import ParameterStore
from svf.stores.command_store import CommandStore

FMU_PATH = Path(__file__).parent.parent.parent / "examples" / "SimpleCounter.fmu"


@pytest.fixture
def participant() -> DomainParticipant:
    return DomainParticipant()


@pytest.fixture
def store() -> ParameterStore:
    return ParameterStore()


@pytest.fixture
def cmd_store() -> CommandStore:
    return CommandStore()


@pytest.fixture
def sync(participant: DomainParticipant) -> DdsSyncProtocol:
    return DdsSyncProtocol(participant)


@pytest.mark.requirement(
    "SVF-DEV-010", "SVF-DEV-012", 
    "SVF-DEV-020", "SVF-DEV-021", "SVF-DEV-022", "SVF-DEV-023", "SVF-DEV-026", "SVF-DEV-028",
    "SVF-DEV-040", "SVF-DEV-047"
)
def test_lockstep_single_fmu(
    store: ParameterStore,
    cmd_store: CommandStore,
    sync: DdsSyncProtocol,
) -> None:
    """Full lockstep with FmuEquipment."""
    master = SimulationMaster(
        tick_source=SoftwareTickSource(),
        sync_protocol=sync,
        models=[FmuEquipment(FMU_PATH, "counter", sync, store, cmd_store)],
        dt=0.1,
        stop_time=1.0,
        sync_timeout=5.0,
    )
    master.run()
    assert master.time == pytest.approx(0.9)
    entry = store.read("counter")
    assert entry is not None
    assert entry.value == pytest.approx(1.0)


@pytest.mark.requirement("SVF-DEV-010", "SVF-DEV-012")
def test_lockstep_multiple_models(
    store: ParameterStore,
    cmd_store: CommandStore,
    sync: DdsSyncProtocol,
) -> None:
    """Full lockstep with FmuEquipment + NativeEquipment."""
    tick_log: list[float] = []

    def step(eq: NativeEquipment, t: float, dt: float) -> None:
        tick_log.append(round(t + dt, 9))
        eq.write_port("logged_time", round(t + dt, 9))

    master = SimulationMaster(
        tick_source=SoftwareTickSource(),
        sync_protocol=sync,
        models=[
            FmuEquipment(FMU_PATH, "counter", sync, store, cmd_store),
            NativeEquipment(
                "logger",
                [PortDefinition("logged_time", PortDirection.OUT)],
                step,
                sync,
                store,
                cmd_store,
            ),
        ],
        dt=0.1,
        stop_time=0.5,
        sync_timeout=5.0,
    )
    master.run()
    assert len(tick_log) == 5
    assert tick_log[0] == pytest.approx(0.1)
    assert tick_log[-1] == pytest.approx(0.5)
    assert store.read("counter") is not None
    assert store.read("logged_time") is not None


@pytest.mark.requirement("SVF-DEV-011")
def test_lockstep_sync_timeout(
    store: ParameterStore,
    cmd_store: CommandStore,
) -> None:
    """SimulationMaster raises SimulationError if sync times out."""

    class _HungSync(SyncProtocol):
        def reset(self) -> None: pass
        def publish_ready(self, model_id: str, t: float) -> None: pass
        def wait_for_ready(self, expected: list[str], timeout: float) -> bool:
            return False

    hung_sync = _HungSync()

    def step(eq: NativeEquipment, t: float, dt: float) -> None:
        eq.write_port("value", t)

    master = SimulationMaster(
        tick_source=SoftwareTickSource(),
        sync_protocol=hung_sync,
        models=[NativeEquipment(
            "simple",
            [PortDefinition("value", PortDirection.OUT)],
            step,
            hung_sync,
            store,
            cmd_store,
        )],
        dt=0.1,
        stop_time=1.0,
        sync_timeout=0.01,
    )
    with pytest.raises(SimulationError, match="Sync timeout"):
        master.run()


@pytest.mark.requirement("SVF-DEV-007")
def test_lockstep_model_failure(
    store: ParameterStore,
    cmd_store: CommandStore,
    sync: DdsSyncProtocol,
) -> None:
    """SimulationMaster raises SimulationError if a model faults."""

    def step(eq: NativeEquipment, t: float, dt: float) -> None:
        if round(t + dt, 9) == pytest.approx(0.3):
            raise RuntimeError("Simulated fault at t=0.3")
        eq.write_port("value", t)

    master = SimulationMaster(
        tick_source=SoftwareTickSource(),
        sync_protocol=sync,
        models=[NativeEquipment(
            "faulty",
            [PortDefinition("value", PortDirection.OUT)],
            step,
            sync,
            store,
            cmd_store,
        )],
        dt=0.1,
        stop_time=1.0,
        sync_timeout=5.0,
    )
    with pytest.raises(SimulationError, match="failed on tick"):
        master.run()


@pytest.mark.requirement("SVF-DEV-031", "SVF-DEV-033")
def test_parameter_store_populated_after_run(
    store: ParameterStore,
    cmd_store: CommandStore,
    sync: DdsSyncProtocol,
) -> None:
    """ParameterStore contains correct values after simulation run."""
    master = SimulationMaster(
        tick_source=SoftwareTickSource(),
        sync_protocol=sync,
        models=[FmuEquipment(FMU_PATH, "counter", sync, store, cmd_store)],
        dt=0.1,
        stop_time=0.5,
        sync_timeout=5.0,
    )
    master.run()
    entry = store.read("counter")
    assert entry is not None
    assert entry.value == pytest.approx(0.5)
    assert entry.model_id == "counter"
