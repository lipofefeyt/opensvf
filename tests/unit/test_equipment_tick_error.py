"""
Tests for EquipmentTickError and on_tick_error callback in SimulationMaster.
Implements: SVF-DEV-156
"""
from __future__ import annotations

from typing import Optional

import pytest

from svf.core.abstractions import SyncProtocol
from svf.core.equipment import PortDefinition, PortDirection
from svf.core.native_equipment import NativeEquipment
from svf.sim.simulation import (
    EquipmentTickError,
    SimulationError,
    SimulationMaster,
)
from svf.sim.software_tick import SoftwareTickSource
from svf.stores.command_store import CommandStore
from svf.stores.parameter_store import ParameterStore


# ── shared fixtures ───────────────────────────────────────────────────────────

class _Sync(SyncProtocol):
    def reset(self) -> None: pass
    def publish_ready(self, model_id: str, t: float) -> None: pass
    def wait_for_ready(self, expected: list[str], timeout: float) -> bool: return True


def _make_master(
    models: list[NativeEquipment],
    on_tick_error: object = None,
    stop_time: float = 0.05,
) -> SimulationMaster:
    kwargs = {}
    if on_tick_error is not None:
        kwargs["on_tick_error"] = on_tick_error  # type: ignore[assignment]
    return SimulationMaster(
        tick_source=SoftwareTickSource(),
        sync_protocol=_Sync(),
        models=models,  # type: ignore[arg-type]
        dt=0.05,
        stop_time=stop_time,
        **kwargs,
    )


def _good_model(sync: _Sync, store: ParameterStore, cmd: CommandStore) -> NativeEquipment:
    def step(eq: NativeEquipment, t: float, dt: float) -> None:
        pass
    return NativeEquipment(
        equipment_id="good_model",
        ports=[],
        step_fn=step,
        sync_protocol=sync,
        store=store,
    )


def _bad_model(
    sync: _Sync,
    store: ParameterStore,
    cmd: CommandStore,
    error: Exception,
) -> NativeEquipment:
    def step(eq: NativeEquipment, t: float, dt: float) -> None:
        raise error
    return NativeEquipment(
        equipment_id="bad_model",
        ports=[],
        step_fn=step,
        sync_protocol=sync,
        store=store,
    )


# ── EquipmentTickError structure ──────────────────────────────────────────────

@pytest.mark.requirement("SVF-DEV-156")
def test_equipment_tick_error_stores_fields() -> None:
    cause = ValueError("sensor overrange")
    err = EquipmentTickError("gyro1", 42.5, cause)
    assert err.equipment_id == "gyro1"
    assert err.obt == 42.5
    assert err.cause is cause


@pytest.mark.requirement("SVF-DEV-156")
def test_equipment_tick_error_context_dict() -> None:
    cause = RuntimeError("bus timeout")
    err = EquipmentTickError("rw1", 10.0, cause)
    assert err.context["equipment_id"] == "rw1"
    assert err.context["obt"] == 10.0
    assert err.context["cause_type"] == "RuntimeError"
    assert "bus timeout" in err.context["cause_message"]


@pytest.mark.requirement("SVF-DEV-156")
def test_equipment_tick_error_message_contains_id_and_obt() -> None:
    err = EquipmentTickError("mag1", 3.14, ValueError("x"))
    msg = str(err)
    assert "mag1" in msg
    assert "3.14" in msg


# ── default behaviour: re-raise as SimulationError ───────────────────────────

@pytest.mark.requirement("SVF-DEV-156")
def test_default_handler_reraises_as_simulation_error() -> None:
    sync, store, cmd = _Sync(), ParameterStore(), CommandStore()
    model = _bad_model(sync, store, cmd, ValueError("boom"))
    master = _make_master([model])

    with pytest.raises(SimulationError) as exc_info:
        master.run()

    assert "bad_model" in str(exc_info.value)


@pytest.mark.requirement("SVF-DEV-156")
def test_default_handler_chains_original_cause() -> None:
    sync, store, cmd = _Sync(), ParameterStore(), CommandStore()
    cause = ValueError("original cause")
    model = _bad_model(sync, store, cmd, cause)
    master = _make_master([model])

    with pytest.raises(SimulationError) as exc_info:
        master.run()

    assert exc_info.value.__cause__ is cause


# ── custom on_tick_error callback ─────────────────────────────────────────────

@pytest.mark.requirement("SVF-DEV-156")
def test_custom_handler_receives_correct_equipment_id_and_obt() -> None:
    sync, store, cmd = _Sync(), ParameterStore(), CommandStore()
    model = _bad_model(sync, store, cmd, RuntimeError("overtemp"))

    received: list[EquipmentTickError] = []

    def record_and_continue(err: EquipmentTickError) -> None:
        received.append(err)

    master = _make_master([model], on_tick_error=record_and_continue)
    master.run()  # must not raise

    assert len(received) == 1
    assert received[0].equipment_id == "bad_model"
    assert received[0].obt >= 0.0


@pytest.mark.requirement("SVF-DEV-156")
def test_custom_handler_context_has_expected_keys() -> None:
    sync, store, cmd = _Sync(), ParameterStore(), CommandStore()
    model = _bad_model(sync, store, cmd, ValueError("v"))

    captured: list[EquipmentTickError] = []

    def handler(err: EquipmentTickError) -> None:
        captured.append(err)

    master = _make_master([model], on_tick_error=handler)
    master.run()

    ctx = captured[0].context
    assert "equipment_id" in ctx
    assert "obt" in ctx
    assert "cause_type" in ctx
    assert "cause_message" in ctx


@pytest.mark.requirement("SVF-DEV-156")
def test_handler_that_raises_aborts_simulation() -> None:
    sync, store, cmd = _Sync(), ParameterStore(), CommandStore()
    model = _bad_model(sync, store, cmd, RuntimeError("sensor fail"))

    def strict_handler(err: EquipmentTickError) -> None:
        raise SimulationError(f"strict: {err}")

    master = _make_master([model], on_tick_error=strict_handler)

    with pytest.raises(SimulationError, match="strict:"):
        master.run()


@pytest.mark.requirement("SVF-DEV-156")
def test_record_and_continue_collects_multiple_ticks() -> None:
    sync, store, cmd = _Sync(), ParameterStore(), CommandStore()
    model = _bad_model(sync, store, cmd, ValueError("noise"))

    errors: list[EquipmentTickError] = []
    master = _make_master([model], on_tick_error=errors.append, stop_time=0.3)
    master.run()

    # Multiple ticks should have been recorded (stop_time / dt = 6 ticks)
    assert len(errors) >= 2
    # OBT values should be increasing
    obts = [e.obt for e in errors]
    assert obts == sorted(obts)


@pytest.mark.requirement("SVF-DEV-156")
def test_good_model_unaffected_when_other_fails_with_continue() -> None:
    sync, store, cmd = _Sync(), ParameterStore(), CommandStore()
    ticks_seen: list[float] = []

    def counting_step(eq: NativeEquipment, t: float, dt: float) -> None:
        ticks_seen.append(t)

    good = NativeEquipment(
        equipment_id="counter",
        ports=[],
        step_fn=counting_step,
        sync_protocol=sync,
        store=store,
    )
    bad = _bad_model(sync, store, cmd, RuntimeError("bad"))

    master = _make_master(
        [good, bad],
        on_tick_error=lambda _: None,
        stop_time=0.3,
    )
    master.run()

    # Good model must have ticked even though bad model failed every tick
    assert len(ticks_seen) >= 2
