"""Tests for variable-timestep execution in SimulationMaster."""
from __future__ import annotations
import pytest
from typing import Optional
from svf.core.abstractions import SyncProtocol
from svf.core.native_equipment import NativeEquipment
from svf.stores.parameter_store import ParameterStore
from svf.stores.command_store import CommandStore
from svf.core.equipment import PortDefinition, PortDirection
from svf.sim.simulation import SimulationMaster
from svf.sim.software_tick import SoftwareTickSource


class _NoSync(SyncProtocol):
    def reset(self) -> None: pass
    def publish_ready(self, model_id: str, t: float) -> None: pass
    def wait_for_ready(self, expected: list[str], timeout: float) -> bool:
        return True


def make_simple_eq(sync: SyncProtocol,
                   store: ParameterStore,
                   suggested: Optional[float] = None) -> NativeEquipment:
    """NativeEquipment with optional suggested_dt override."""
    steps: list[float] = []

    def _step(eq: NativeEquipment, t: float, dt: float) -> None:
        steps.append(dt)

    eq = NativeEquipment(
        equipment_id="simple",
        ports=[],
        step_fn=_step,
        sync_protocol=sync,
        store=store,
        command_store=CommandStore(),
    )
    eq._recorded_steps = steps  # type: ignore[attr-defined]

    if suggested is not None:
        eq.suggested_dt = lambda: suggested  # type: ignore[method-assign]

    return eq


class TestVariableTimestepSuite:

    @pytest.mark.requirement("SVF-DEV-003")
    def test_fixed_dt_used_when_no_suggestion(self) -> None:
        """SimulationMaster uses fixed dt when no model suggests otherwise."""
        store = ParameterStore()
        sync = _NoSync()
        eq = make_simple_eq(sync, store)
        eq.initialise()

        master = SimulationMaster(
            tick_source=SoftwareTickSource(),
            sync_protocol=sync,
            models=[eq],
            dt=0.1,
            stop_time=0.5,
            sync_timeout=1.0,
            command_store=CommandStore(),
            param_store=store,
        )
        master.run()
        steps = eq._recorded_steps  # type: ignore[attr-defined]
        assert len(steps) == 5
        assert all(abs(s - 0.1) < 1e-9 for s in steps)

    @pytest.mark.requirement("SVF-DEV-003")
    def test_suggested_dt_smaller_is_used(self) -> None:
        """SimulationMaster uses suggested_dt when smaller than fixed dt."""
        store = ParameterStore()
        sync = _NoSync()
        eq = make_simple_eq(sync, store, suggested=0.05)
        eq.initialise()

        master = SimulationMaster(
            tick_source=SoftwareTickSource(),
            sync_protocol=sync,
            models=[eq],
            dt=0.1,
            stop_time=0.5,
            sync_timeout=1.0,
            command_store=CommandStore(),
            param_store=store,
        )
        master.run()
        steps = eq._recorded_steps  # type: ignore[attr-defined]
        assert all(abs(s - 0.05) < 1e-9 for s in steps)

    @pytest.mark.requirement("SVF-DEV-003")
    def test_suggested_dt_larger_is_ignored(self) -> None:
        """SimulationMaster ignores suggested_dt when larger than fixed dt."""
        store = ParameterStore()
        sync = _NoSync()
        eq = make_simple_eq(sync, store, suggested=0.5)
        eq.initialise()

        master = SimulationMaster(
            tick_source=SoftwareTickSource(),
            sync_protocol=sync,
            models=[eq],
            dt=0.1,
            stop_time=0.5,
            sync_timeout=1.0,
            command_store=CommandStore(),
            param_store=store,
        )
        master.run()
        steps = eq._recorded_steps  # type: ignore[attr-defined]
        assert all(abs(s - 0.1) < 1e-9 for s in steps)

    @pytest.mark.requirement("SVF-DEV-003")
    def test_min_of_multiple_suggestions(self) -> None:
        """SimulationMaster uses minimum suggested_dt across all models."""
        store = ParameterStore()
        sync = _NoSync()
        eq1 = make_simple_eq(sync, store, suggested=0.05)
        eq2 = make_simple_eq(sync, store, suggested=0.02)
        eq2._equipment_id = "simple2"  # type: ignore[attr-defined]
        eq1.initialise()
        eq2.initialise()

        master = SimulationMaster(
            tick_source=SoftwareTickSource(),
            sync_protocol=sync,
            models=[eq1, eq2],
            dt=0.1,
            stop_time=0.2,
            sync_timeout=1.0,
            command_store=CommandStore(),
            param_store=store,
        )
        master.run()
        steps = eq1._recorded_steps  # type: ignore[attr-defined]
        assert all(abs(s - 0.02) < 1e-9 for s in steps)
