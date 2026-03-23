"""
SVF Simulation Lifecycle Fixture
Pytest fixtures that start a SimulationMaster before a test and tear it
down cleanly after, regardless of outcome.
Implements: SVF-DEV-040, SVF-DEV-041, SVF-DEV-042
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Generator, Optional, List

import pytest
from cyclonedds.domain import DomainParticipant

from svf.simulation import SimulationMaster, SimulationError
from svf.abstractions import ModelAdapter
from svf.software_tick import SoftwareTickSource
from svf.dds_sync import DdsSyncProtocol
from svf.fmu_adapter import FmuModelAdapter
from svf.parameter_store import ParameterStore
from svf.command_store import CommandStore
from svf.plugin.observable import ObservableFactory
from svf.plugin.verdict import Verdict, VerdictRecorder

logger = logging.getLogger(__name__)


@dataclass
class FmuConfig:
    """Configuration for a single FMU in a simulation session."""
    fmu_path: str | Path
    model_id: str


@dataclass
class SimulationSession:
    """
    Holds all resources for a single test simulation run.

    Attributes:
        observe:   ObservableFactory for telemetry assertions
        store:     ParameterStore for direct parameter access
        verdicts:  VerdictRecorder populated after the test completes
        error:     Any SimulationError raised during the run
    """
    observe: ObservableFactory
    store: ParameterStore
    verdicts: VerdictRecorder
    _cmd_store: CommandStore = field(default_factory=CommandStore, repr=False)
    error: Optional[Exception] = None
    _master: Optional[SimulationMaster] = field(default=None, repr=False)

    def inject(
        self,
        name: str,
        value: float,
        source_id: str = "test_procedure",
    ) -> None:
        """
        Inject a command into the simulation.

        The command is written to the CommandStore and consumed by the
        relevant model adapter before its next tick.

        Args:
            name:      Target parameter or command name
            value:     Commanded value
            source_id: ID of the issuing entity (default: test_procedure)
        """
        self._cmd_store.inject(
            name=name,
            value=value,
            t=0.0,
            source_id=source_id,
        )
        logger.info(f"Injected command: {name}={value} from {source_id}")

    def stop(self) -> None:
        """Signal the simulation to stop early."""
        if self._master is not None:
            self._master.stop()


def _run_in_thread(
    master: SimulationMaster,
    session: SimulationSession,
) -> None:
    """Run the simulation master in a background thread."""
    try:
        master.run()
    except SimulationError as e:
        session.error = e
        logger.error(f"Simulation error: {e}")
    except Exception as e:
        session.error = e
        logger.error(f"Unexpected simulation error: {e}")


@pytest.fixture
def svf_participant() -> DomainParticipant:
    """Shared DDS domain participant for a test session."""
    return DomainParticipant()


@pytest.fixture
def svf_session(
    svf_participant: DomainParticipant,
    request: pytest.FixtureRequest,
) -> Generator[SimulationSession, None, None]:
    """
    Simulation lifecycle fixture.

    Starts a SimulationMaster in a background thread before the test,
    provides observe(), inject(), and direct store access,
    and tears down cleanly after.

    Configure via pytest marks:

        @pytest.mark.svf_fmus([FmuConfig("models/power.fmu", "power")])
        @pytest.mark.svf_dt(0.1)
        @pytest.mark.svf_stop_time(10.0)
        def test_power_model(svf_session):
            svf_session.inject("solar_angle", 45.0)
            svf_session.observe("battery_voltage").exceeds(3.3).within(5.0)
    """
    fmu_marker = request.node.get_closest_marker("svf_fmus")
    dt_marker = request.node.get_closest_marker("svf_dt")
    stop_marker = request.node.get_closest_marker("svf_stop_time")

    fmu_configs: List[FmuConfig] = (
        fmu_marker.args[0] if fmu_marker else []
    )
    dt: float = dt_marker.args[0] if dt_marker else 0.1
    stop_time: float = stop_marker.args[0] if stop_marker else 2.0

    store = ParameterStore()
    cmd_store = CommandStore()
    sync = DdsSyncProtocol(svf_participant)
    observe = ObservableFactory(store)
    verdicts = VerdictRecorder()

    models: List[ModelAdapter] = [
        FmuModelAdapter(
            fmu_path=cfg.fmu_path,
            model_id=cfg.model_id,
            sync_protocol=sync,
            store=store,
            command_store=cmd_store,
        )
        for cfg in fmu_configs
    ]

    if not models:
        default_fmu = (
            Path(__file__).parent.parent.parent.parent
            / "examples"
            / "SimpleCounter.fmu"
        )
        models = [FmuModelAdapter(
            fmu_path=default_fmu,
            model_id="counter",
            sync_protocol=sync,
            store=store,
            command_store=cmd_store,
        )]

    master = SimulationMaster(
        tick_source=SoftwareTickSource(),
        sync_protocol=sync,
        models=models,
        dt=dt,
        stop_time=stop_time,
        sync_timeout=5.0,
    )

    session = SimulationSession(
        observe=observe,
        store=store,
        verdicts=verdicts,
        _cmd_store=cmd_store,
        _master=master,
    )

    thread = threading.Thread(
        target=_run_in_thread,
        args=(master, session),
        daemon=True,
    )
    thread.start()
    time.sleep(0.1)

    yield session

    thread.join(timeout=stop_time + 5.0)

    test_id = request.node.nodeid
    rep = getattr(request.node, "_svf_rep", None)
    if session.error is not None:
        verdict = Verdict.ERROR
    elif rep is not None and rep.failed:
        verdict = Verdict.FAIL
    elif rep is not None and rep.passed:
        verdict = Verdict.PASS
    else:
        verdict = Verdict.INCONCLUSIVE

    verdicts.record(test_id, verdict)
    logger.info(f"Session teardown complete for {test_id}")
