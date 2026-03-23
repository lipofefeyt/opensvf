"""
Tests for the observable assertion API.
Implements: SVF-DEV-043
"""

import pytest
import threading
from cyclonedds.domain import DomainParticipant

from svf.plugin.observable import ObservableFactory, ConditionNotMet
from svf.simulation import SimulationMaster
from svf.software_tick import SoftwareTickSource
from svf.dds_sync import DdsSyncProtocol
from svf.native_adapter import NativeModelAdapter


@pytest.fixture
def participant() -> DomainParticipant:
    return DomainParticipant()


@pytest.fixture
def sync(participant: DomainParticipant) -> DdsSyncProtocol:
    return DdsSyncProtocol(participant)


def _run_simulation(
    participant: DomainParticipant,
    sync: DdsSyncProtocol,
    stop_time: float = 2.0,
) -> None:
    """Run a simple counter simulation in the background."""
    class _CounterModel:
        def step(self, t: float, dt: float) -> dict[str, float]:
            return {"counter": round(t + dt, 9)}

    master = SimulationMaster(
        tick_source=SoftwareTickSource(),
        sync_protocol=sync,
        models=[NativeModelAdapter(
            _CounterModel(), "counter", ["counter"], participant, sync
        )],
        dt=0.1,
        stop_time=stop_time,
        sync_timeout=5.0,
    )
    master.run()


def test_observe_reaches(
    participant: DomainParticipant, sync: DdsSyncProtocol
) -> None:
    """observe().reaches() detects when a variable hits a target value."""
    observe = ObservableFactory(participant)

    thread = threading.Thread(
        target=_run_simulation, args=(participant, sync, 2.0)
    )
    thread.start()

    result = observe("counter").reaches(1.0).within(5.0)
    thread.join()

    assert abs(result - 1.0) < 1e-6


def test_observe_exceeds(
    participant: DomainParticipant, sync: DdsSyncProtocol
) -> None:
    """observe().exceeds() detects when a variable crosses a threshold."""
    observe = ObservableFactory(participant)

    thread = threading.Thread(
        target=_run_simulation, args=(participant, sync, 2.0)
    )
    thread.start()

    result = observe("counter").exceeds(0.5).within(5.0)
    thread.join()

    assert result > 0.5


def test_observe_drops_below(
    participant: DomainParticipant, sync: DdsSyncProtocol
) -> None:
    """observe().drops_below() detects when a variable goes below threshold."""
    observe = ObservableFactory(participant)

    # Model that counts down
    class _CountdownModel:
        def __init__(self) -> None:
            self.value = 1.0

        def step(self, t: float, dt: float) -> dict[str, float]:
            self.value = round(1.0 - (t + dt), 9)
            return {"countdown": self.value}

    countdown_sync = DdsSyncProtocol(participant)
    master = SimulationMaster(
        tick_source=SoftwareTickSource(),
        sync_protocol=countdown_sync,
        models=[NativeModelAdapter(
            _CountdownModel(), "countdown", ["countdown"], participant, countdown_sync
        )],
        dt=0.1,
        stop_time=2.0,
        sync_timeout=5.0,
    )

    thread = threading.Thread(target=master.run)
    thread.start()

    result = observe("countdown").drops_below(0.5).within(5.0)
    thread.join()

    assert result < 0.5


def test_observe_timeout(
    participant: DomainParticipant, sync: DdsSyncProtocol
) -> None:
    """observe() raises ConditionNotMet if condition never satisfied."""
    observe = ObservableFactory(participant)

    thread = threading.Thread(
        target=_run_simulation, args=(participant, sync, 0.5)
    )
    thread.start()

    with pytest.raises(ConditionNotMet, match="not met within"):
        # Counter only reaches 0.5, never 999.0
        observe("counter").reaches(999.0).within(2.0)

    thread.join()


def test_observe_satisfies(
    participant: DomainParticipant, sync: DdsSyncProtocol
) -> None:
    """observe().satisfies() works with arbitrary condition functions."""
    observe = ObservableFactory(participant)

    thread = threading.Thread(
        target=_run_simulation, args=(participant, sync, 2.0)
    )
    thread.start()

    result = observe("counter").satisfies(
        lambda v: v > 0.7, description="exceeds 0.7"
    ).within(5.0)
    thread.join()

    assert result > 0.7
