"""
SVF Integration Test — Full Lockstep Loop
Exercises the complete stack: SoftwareTickSource + DdsSyncProtocol +
FmuModelAdapter + NativeModelAdapter with ParameterStore.
Implements: SVF-DEV-010, SVF-DEV-012, SVF-DEV-014, SVF-DEV-015, SVF-DEV-016,
            SVF-DEV-031, SVF-DEV-033
"""

import pytest
from pathlib import Path

from cyclonedds.domain import DomainParticipant

from svf.simulation import SimulationMaster, SimulationError
from svf.abstractions import SyncProtocol
from svf.software_tick import SoftwareTickSource
from svf.dds_sync import DdsSyncProtocol
from svf.fmu_adapter import FmuModelAdapter
from svf.native_adapter import NativeModelAdapter
from svf.parameter_store import ParameterStore

FMU_PATH = Path(__file__).parent.parent.parent / "examples" / "SimpleCounter.fmu"


@pytest.fixture
def participant() -> DomainParticipant:
    return DomainParticipant()


@pytest.fixture
def store() -> ParameterStore:
    return ParameterStore()


@pytest.fixture
def sync(participant: DomainParticipant) -> DdsSyncProtocol:
    return DdsSyncProtocol(participant)


def test_lockstep_single_fmu(
    store: ParameterStore, sync: DdsSyncProtocol
) -> None:
    """Full lockstep loop with a single FmuModelAdapter."""
    master = SimulationMaster(
        tick_source=SoftwareTickSource(),
        sync_protocol=sync,
        models=[FmuModelAdapter(FMU_PATH, "counter", sync, store)],
        dt=0.1,
        stop_time=1.0,
        sync_timeout=5.0,
    )
    master.run()
    assert master.time == pytest.approx(0.9)
    assert master.model_ids == ["counter"]
    entry = store.read("counter")
    assert entry is not None
    assert entry.value == pytest.approx(1.0)


def test_lockstep_multiple_models(
    store: ParameterStore, sync: DdsSyncProtocol
) -> None:
    """Full lockstep loop with two models — one FMU and one native."""
    tick_log: list[tuple[str, float]] = []

    class _LoggingModel:
        def step(self, t: float, dt: float) -> dict[str, float]:
            tick_log.append(("native", round(t + dt, 9)))
            return {"logged_time": round(t + dt, 9)}

    master = SimulationMaster(
        tick_source=SoftwareTickSource(),
        sync_protocol=sync,
        models=[
            FmuModelAdapter(FMU_PATH, "counter", sync, store),
            NativeModelAdapter(
                _LoggingModel(), "logger", ["logged_time"], sync, store
            ),
        ],
        dt=0.1,
        stop_time=0.5,
        sync_timeout=5.0,
    )
    master.run()

    assert len(tick_log) == 5
    assert tick_log[0][0] == "native"
    assert tick_log[0][1] == pytest.approx(0.1)
    assert tick_log[-1][1] == pytest.approx(0.5)
    assert store.read("counter") is not None
    assert store.read("logged_time") is not None


def test_lockstep_sync_timeout(
    store: ParameterStore, participant: DomainParticipant
) -> None:
    """SimulationMaster raises SimulationError if sync times out."""

    class _HungSyncProtocol(SyncProtocol):
        def reset(self) -> None: pass
        def publish_ready(self, model_id: str, t: float) -> None: pass
        def wait_for_ready(self, expected: list[str], timeout: float) -> bool:
            return False

    class _SimpleModel:
        def step(self, t: float, dt: float) -> dict[str, float]:
            return {"value": t}

    hung_sync = _HungSyncProtocol()
    master = SimulationMaster(
        tick_source=SoftwareTickSource(),
        sync_protocol=hung_sync,
        models=[NativeModelAdapter(
            _SimpleModel(), "simple", ["value"], hung_sync, store
        )],
        dt=0.1,
        stop_time=1.0,
        sync_timeout=0.01,
    )

    with pytest.raises(SimulationError, match="Sync timeout"):
        master.run()


def test_lockstep_model_failure(
    store: ParameterStore, sync: DdsSyncProtocol
) -> None:
    """SimulationMaster raises SimulationError if a model faults."""

    class _FailingModel:
        def step(self, t: float, dt: float) -> dict[str, float]:
            if round(t + dt, 9) == pytest.approx(0.3):
                raise RuntimeError("Simulated model fault at t=0.3")
            return {"value": t}

    master = SimulationMaster(
        tick_source=SoftwareTickSource(),
        sync_protocol=sync,
        models=[NativeModelAdapter(
            _FailingModel(), "faulty", ["value"], sync, store
        )],
        dt=0.1,
        stop_time=1.0,
        sync_timeout=5.0,
    )

    with pytest.raises(SimulationError, match="failed on tick"):
        master.run()


def test_parameter_store_populated_after_run(
    store: ParameterStore, sync: DdsSyncProtocol
) -> None:
    """ParameterStore contains correct final values after simulation run."""
    master = SimulationMaster(
        tick_source=SoftwareTickSource(),
        sync_protocol=sync,
        models=[FmuModelAdapter(FMU_PATH, "counter", sync, store)],
        dt=0.1,
        stop_time=0.5,
        sync_timeout=5.0,
    )
    master.run()

    entry = store.read("counter")
    assert entry is not None
    assert entry.value == pytest.approx(0.5)
    assert entry.model_id == "counter"
    assert entry.t == pytest.approx(0.5)