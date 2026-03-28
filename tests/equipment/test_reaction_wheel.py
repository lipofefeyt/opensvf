"""
Tests for ReactionWheel model — M8 extensions.
Bearing friction, temperature, over-temperature protection.
Implements: SVF-DEV-038
"""

import pytest
from svf.abstractions import SyncProtocol
from svf.parameter_store import ParameterStore
from svf.command_store import CommandStore
from svf.models.reaction_wheel import (
    make_reaction_wheel, MAX_SPEED_RPM, MAX_TEMP_C,
    AMBIENT_TEMP_C, TEMP_DERATING_FACTOR
)
from svf.native_equipment import NativeEquipment


class _NoSync(SyncProtocol):
    def reset(self) -> None: pass
    def publish_ready(self, model_id: str, t: float) -> None: pass
    def wait_for_ready(self, expected: list[str], timeout: float) -> bool:
        return True


@pytest.fixture
def rw() -> NativeEquipment:
    sync = _NoSync()
    store = ParameterStore()
    cmd_store = CommandStore()
    eq = make_reaction_wheel(sync, store, cmd_store)
    eq.initialise()
    return eq


# ── Basic physics ─────────────────────────────────────────────────────────────

@pytest.mark.requirement("SVF-DEV-038")
def test_rw_speed_increases_with_torque(rw: NativeEquipment) -> None:
    """Speed increases when positive torque commanded."""
    rw.receive("aocs.rw1.torque_cmd", 0.1)
    rw.do_step(t=0.0, dt=1.0)
    assert rw.read_port("aocs.rw1.speed") > 0.0


@pytest.mark.requirement("SVF-DEV-038")
def test_rw_speed_clamped_at_max(rw: NativeEquipment) -> None:
    """Speed cannot exceed MAX_SPEED_RPM."""
    rw.receive("aocs.rw1.torque_cmd", 0.2)
    for i in range(1000):
        rw.do_step(t=float(i), dt=1.0)
    assert rw.read_port("aocs.rw1.speed") <= MAX_SPEED_RPM


@pytest.mark.requirement("SVF-DEV-038")
def test_rw_initial_temperature_is_ambient(rw: NativeEquipment) -> None:
    """Initial bearing temperature is ambient."""
    assert rw.read_port("aocs.rw1.temperature") == pytest.approx(AMBIENT_TEMP_C)


# ── Bearing friction ──────────────────────────────────────────────────────────

@pytest.mark.requirement("SVF-DEV-038")
def test_rw_decelerates_without_torque(rw: NativeEquipment) -> None:
    """Wheel decelerates due to friction when torque=0."""
    # Spin up first
    rw.receive("aocs.rw1.torque_cmd", 0.1)
    for i in range(100):
        rw.do_step(t=float(i), dt=1.0)
    speed_at_100 = rw.read_port("aocs.rw1.speed")

    # Remove torque — friction should decelerate
    rw.receive("aocs.rw1.torque_cmd", 0.0)
    for i in range(100, 200):
        rw.do_step(t=float(i), dt=1.0)
    speed_at_200 = rw.read_port("aocs.rw1.speed")

    assert speed_at_200 < speed_at_100


# ── Temperature ───────────────────────────────────────────────────────────────

@pytest.mark.requirement("SVF-DEV-038")
def test_rw_temperature_rises_under_load(rw: NativeEquipment) -> None:
    """Temperature rises when wheel spins at high speed."""
    rw.receive("aocs.rw1.torque_cmd", 0.2)
    for i in range(500):
        rw.do_step(t=float(i), dt=1.0)
    assert rw.read_port("aocs.rw1.temperature") > AMBIENT_TEMP_C


@pytest.mark.requirement("SVF-DEV-038")
def test_rw_temperature_cools_when_idle(rw: NativeEquipment) -> None:
    """Temperature drops towards ambient when wheel is idle."""
    # Heat up first
    rw.receive("aocs.rw1.torque_cmd", 0.2)
    for i in range(500):
        rw.do_step(t=float(i), dt=1.0)
    hot_temp = rw.read_port("aocs.rw1.temperature")

    # Stop wheel and let cool
    rw.receive("aocs.rw1.torque_cmd", 0.0)
    for i in range(500, 1000):
        rw.do_step(t=float(i), dt=1.0)
    cool_temp = rw.read_port("aocs.rw1.temperature")

    assert cool_temp < hot_temp


# ── Over-temperature protection ───────────────────────────────────────────────

@pytest.mark.requirement("SVF-DEV-038")
def test_rw_status_zero_when_over_temperature(rw: NativeEquipment) -> None:
    """Status flag goes to 0 when temperature exceeds MAX_TEMP_C."""
    # Force temperature above threshold
    rw._port_values["aocs.rw1.temperature"] = MAX_TEMP_C + 1.0
    rw.receive("aocs.rw1.torque_cmd", 0.1)
    rw.do_step(t=0.0, dt=1.0)
    assert rw.read_port("aocs.rw1.status") == pytest.approx(0.0)


@pytest.mark.requirement("SVF-DEV-038")
def test_rw_torque_derated_when_over_temperature(rw: NativeEquipment) -> None:
    """Speed increase is reduced when over-temperature protection active."""
    # Normal operation
    rw.receive("aocs.rw1.torque_cmd", 0.1)
    rw.do_step(t=0.0, dt=1.0)
    normal_speed = rw.read_port("aocs.rw1.speed")

    # Reset and apply over-temperature
    rw._port_values["aocs.rw1.speed"] = 0.0
    rw._port_values["aocs.rw1.temperature"] = MAX_TEMP_C + 1.0
    rw.receive("aocs.rw1.torque_cmd", 0.1)
    rw.do_step(t=1.0, dt=1.0)
    derated_speed = rw.read_port("aocs.rw1.speed")

    assert derated_speed < normal_speed
