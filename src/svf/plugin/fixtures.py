"""
SVF Simulation Lifecycle Fixture
Pytest fixtures that start a SimulationMaster before a test and tear it
down cleanly after, regardless of outcome.
Implements: SVF-DEV-040, SVF-DEV-041, SVF-DEV-042, SVF-DEV-048
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
from svf.fmu_equipment import FmuEquipment
from svf.parameter_store import ParameterStore
from svf.command_store import CommandStore
from svf.plugin.observable import ObservableFactory
from svf.plugin.verdict import Verdict, VerdictRecorder

logger = logging.getLogger(__name__)


@dataclass
class FmuConfig:
    """Configuration for a single FMU equipment in a simulation session."""
    fmu_path: str | Path
    model_id: str
    parameter_map: dict[str, str] = field(default_factory=dict)


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
    _done: bool = field(default=False, repr=False)

    def inject(
        self,
        name: str,
        value: float,
        source_id: str = "test_procedure",
    ) -> None:
        """Inject a command into the simulation via the CommandStore."""
        self._cmd_store.inject(name=name, value=value, t=0.0, source_id=source_id)
        logger.info(f"Injected command: {name}={value} from {source_id}")

    def stop(self) -> None:
        """Signal the simulation to stop early."""
        if self._master is not None:
            self._master.stop()


def _run_simulation(
    master: SimulationMaster,
    session: SimulationSession,
) -> None:
    """Run the simulation master. Sets session._done when finished."""
    try:
        master.run()
    except SimulationError as e:
        session.error = e
        logger.error(f"Simulation error: {e}")
    except Exception as e:
        session.error = e
        logger.error(f"Unexpected simulation error: {e}")
    finally:
        session._done = True


def _run_scheduler(
    store: ParameterStore,
    cmd_store: CommandStore,
    commands: list[tuple[float, str, float]],
    session: SimulationSession,
) -> None:
    """
    Fire scheduled commands when simulation time is reached.

    Polls svf.sim_time in the ParameterStore. When the current
    simulation time reaches a scheduled command's target time,
    injects the command into the CommandStore.

    Args:
        store:    ParameterStore to read svf.sim_time from
        cmd_store: CommandStore to inject commands into
        commands: List of (sim_time, param_name, value) tuples
        session:  SimulationSession — stops polling when _done is True
    """
    remaining = list(commands)

    while remaining and not session._done:
        entry = store.read("svf.sim_time")
        if entry is not None:
            sim_t = entry.value
            fired = []
            for i, (target_t, name, value) in enumerate(remaining):
                if sim_t >= target_t:
                    cmd_store.inject(
                        name=name,
                        value=value,
                        t=sim_t,
                        source_id="svf_command_schedule",
                    )
                    logger.info(
                        f"[schedule] t={sim_t:.1f}s: {name}={value}"
                    )
                    fired.append(i)
            for i in reversed(fired):
                remaining.pop(i)
        time.sleep(0.001)


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

    Configure via pytest marks:

        @pytest.mark.svf_fmus([FmuConfig("models/eps.fmu", "eps", EPS_MAP)])
        @pytest.mark.svf_dt(1.0)
        @pytest.mark.svf_stop_time(120.0)
        @pytest.mark.svf_initial_commands([("eps.solar_array.illumination", 1.0)])
        @pytest.mark.svf_command_schedule([(60.0, "eps.solar_array.illumination", 0.0)])
        def test_something(svf_session):
            svf_session.observe("eps.battery.soc").exceeds(0.88).within(120.0)
            svf_session.stop()
    """
    # ── Read markers ──────────────────────────────────────────────────────────
    fmu_marker      = request.node.get_closest_marker("svf_fmus")
    dt_marker       = request.node.get_closest_marker("svf_dt")
    stop_marker     = request.node.get_closest_marker("svf_stop_time")
    cmd_marker      = request.node.get_closest_marker("svf_initial_commands")
    schedule_marker = request.node.get_closest_marker("svf_command_schedule")

    fmu_configs: List[FmuConfig] = fmu_marker.args[0] if fmu_marker else []
    dt: float = dt_marker.args[0] if dt_marker else 0.1
    stop_time: float = stop_marker.args[0] if stop_marker else 2.0
    initial_commands: List[tuple[str, float]] = (
        cmd_marker.args[0] if cmd_marker else []
    )
    scheduled_commands: list[tuple[float, str, float]] = (
        schedule_marker.args[0] if schedule_marker else []
    )

    # ── Build infrastructure ──────────────────────────────────────────────────
    store = ParameterStore()
    cmd_store   = CommandStore()
    sync        = DdsSyncProtocol(svf_participant)
    observe     = ObservableFactory(store)
    verdicts    = VerdictRecorder()

    models: List[ModelAdapter] = [
        FmuEquipment(
            fmu_path=cfg.fmu_path,
            equipment_id=cfg.model_id,
            sync_protocol=sync,
            store=store,
            command_store=cmd_store,
            parameter_map=cfg.parameter_map if cfg.parameter_map else None,
        )
        for cfg in fmu_configs
    ]

    if not models:
        default_fmu = (
            Path(__file__).parent.parent.parent.parent
            / "examples" / "SimpleCounter.fmu"
        )
        models = [FmuEquipment(
            fmu_path=default_fmu,
            equipment_id="counter",
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
        wiring=None,
        command_store=cmd_store,
        param_store=store,
    )

    session = SimulationSession(
        observe=observe,
        store=store,
        verdicts=verdicts,
        _cmd_store=cmd_store,
        _master=master,
    )
    observe._session = session

    # ── Pre-inject initial commands ───────────────────────────────────────────
    for name, value in initial_commands:
        cmd_store.inject(name=name, value=value, source_id="initial_conditions")

    # ── Start simulation thread ───────────────────────────────────────────────
    sim_thread = threading.Thread(
        target=_run_simulation,
        args=(master, session),
        daemon=True,
    )
    sim_thread.start()

    # ── Start scheduler thread (only if there are scheduled commands) ─────────
    if scheduled_commands:
        sched_thread = threading.Thread(
            target=_run_scheduler,
            args=(store, cmd_store, scheduled_commands, session),
            daemon=True,
        )
        sched_thread.start()

    time.sleep(0.1)

    yield session

    # ── Teardown ──────────────────────────────────────────────────────────────
    if session._master is not None:
        session._master.stop()

    sim_thread.join(timeout=10.0)
    if sim_thread.is_alive():
        logger.warning("Simulation thread did not stop cleanly")

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