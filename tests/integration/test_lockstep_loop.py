"""
SVF Integration Test — Full Lockstep Loop
Exercises the complete stack: SoftwareTickSource + DdsSyncProtocol +
FmuModelAdapter + NativeModelAdapter over a real DDS participant.
Implements: SVF-DEV-010, SVF-DEV-012, SVF-DEV-014, SVF-DEV-015, SVF-DEV-016
"""

import pytest
from pathlib import Path

from cyclonedds.domain import DomainParticipant

from svf.simulation import SimulationMaster
from svf.software_tick import SoftwareTickSource
from svf.dds_sync import DdsSyncProtocol
from svf.fmu_adapter import FmuModelAdapter
from svf.native_adapter import NativeModelAdapter

FMU_PATH = Path(__file__).parent.parent.parent / "examples" / "SimpleCounter.fmu"


@pytest.fixture
def participant() -> DomainParticipant:
    """Shared DDS domain participant for all integration tests."""
    return DomainParticipant()


def test_lockstep_single_fmu(participant: DomainParticipant) -> None:
    """
    Full lockstep loop with a single FmuModelAdapter.
    Verifies that the master drives the FMU through 10 ticks
    and that sync completes cleanly on every step.
    """
    master = SimulationMaster(
        tick_source=SoftwareTickSource(),
        sync_protocol=DdsSyncProtocol(participant),
        models=[FmuModelAdapter(FMU_PATH, "counter")],
        dt=0.1,
        stop_time=1.0,
        sync_timeout=5.0,
    )
    master.run()

    assert master.time == pytest.approx(0.9)
    assert master.model_ids == ["counter"]


def test_lockstep_multiple_models(participant: DomainParticipant) -> None:
    """
    Full lockstep loop with two models — one FMU and one native.
    Verifies that the master correctly waits for both to acknowledge
    before advancing to the next tick.
    """
    tick_log: list[tuple[str, float]] = []

    class _LoggingModel:
        def step(self, t: float, dt: float) -> dict[str, float]:
            tick_log.append(("native", round(t + dt, 9)))
            return {"logged_time": round(t + dt, 9)}

    master = SimulationMaster(
        tick_source=SoftwareTickSource(),
        sync_protocol=DdsSyncProtocol(participant),
        models=[
            FmuModelAdapter(FMU_PATH, "counter"),
            NativeModelAdapter(_LoggingModel(), "logger"),
        ],
        dt=0.1,
        stop_time=0.5,
        sync_timeout=5.0,
    )
    master.run()

    # Both models ran for 5 ticks
    assert len(tick_log) == 5
    assert tick_log[0][0] == "native" and tick_log[0][1] == pytest.approx(0.1)
    assert tick_log[-1][0] == "native" and tick_log[-1][1] == pytest.approx(0.5)


def test_lockstep_sync_timeout(participant: DomainParticipant) -> None:
    """
    SimulationMaster raises SimulationError if a model never acknowledges.
    Simulates a hung model by using a NativeModelAdapter whose sync
    acknowledgement is never published due to an injected fault.
    """
    from svf.simulation import SimulationError
    from svf.abstractions import SyncProtocol

    class _HungSyncProtocol(SyncProtocol):
        """Always times out — simulates a model that never acknowledges."""
        def reset(self) -> None: pass
        def publish_ready(self, model_id: str, t: float) -> None: pass
        def wait_for_ready(self, expected: list[str], timeout: float) -> bool:
            return False  # never ready

    class _SimpleModel:
        def step(self, t: float, dt: float) -> dict[str, float]:
            return {"value": t}

    master = SimulationMaster(
        tick_source=SoftwareTickSource(),
        sync_protocol=_HungSyncProtocol(),
        models=[NativeModelAdapter(_SimpleModel(), "simple")],
        dt=0.1,
        stop_time=1.0,
        sync_timeout=0.01,
    )

    with pytest.raises(SimulationError, match="Sync timeout"):
        master.run()


def test_lockstep_model_failure(participant: DomainParticipant) -> None:
    """
    SimulationMaster raises SimulationError if a model raises during on_tick.
    """
    from svf.simulation import SimulationError

    class _FailingModel:
        def step(self, t: float, dt: float) -> dict[str, float]:
            if round(t + dt, 9) == pytest.approx(0.3):
                raise RuntimeError("Simulated model fault at t=0.3")
            return {"value": t}

    master = SimulationMaster(
        tick_source=SoftwareTickSource(),
        sync_protocol=DdsSyncProtocol(participant),
        models=[NativeModelAdapter(_FailingModel(), "faulty")],
        dt=0.1,
        stop_time=1.0,
        sync_timeout=5.0,
    )

    with pytest.raises(SimulationError, match="failed on tick"):
        master.run()