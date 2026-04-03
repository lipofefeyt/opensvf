"""
SVF Reaction Wheel Failure Test Procedures
Exercises RW failure modes and boundary conditions.

TC-RW-FAIL-001: Over-temperature — torque derated above 80°C
TC-RW-FAIL-002: Speed saturation — clamp at MAX_SPEED_RPM
TC-RW-FAIL-003: Bearing friction — wheel coasts to stop
TC-RW-FAIL-004: Negative torque — wheel decelerates and reverses
TC-RW-FAIL-005: Zero torque from over-speed — friction stops wheel
TC-RW-FAIL-006: Temperature recovers after spindown

Implements: RW-001 through RW-006
"""

import pytest
from svf.abstractions import SyncProtocol
from svf.parameter_store import ParameterStore
from svf.command_store import CommandStore
from svf.models.reaction_wheel import (
    make_reaction_wheel, MAX_SPEED_RPM, MAX_TEMP_C, AMBIENT_TEMP_C,
)
from svf.native_equipment import NativeEquipment


class _NoSync(SyncProtocol):
    def reset(self) -> None: pass
    def publish_ready(self, model_id: str, t: float) -> None: pass
    def wait_for_ready(self, expected: list[str], timeout: float) -> bool:
        return True


@pytest.fixture
def rw() -> NativeEquipment:
    eq = make_reaction_wheel(_NoSync(), ParameterStore(), CommandStore())
    eq.initialise()
    return eq


@pytest.mark.requirement("RW-005", "RW-006")
def test_tc_rw_fail_001_over_temperature_derates_torque(
    rw: NativeEquipment,
) -> None:
    """
    TC-RW-FAIL-001: Over-temperature — effective torque halved above 80°C.

    Two identical steps — one at nominal temp, one at over-temp.
    Over-temp step should produce less speed increase.
    """
    rw.receive("aocs.rw1.torque_cmd", 0.1)
    rw.do_step(t=0.0, dt=1.0)
    nominal_speed = rw.read_port("aocs.rw1.speed")

    # Reset speed, force over-temperature
    rw._port_values["aocs.rw1.speed"] = 0.0
    rw._port_values["aocs.rw1.temperature"] = MAX_TEMP_C + 1.0
    rw.receive("aocs.rw1.torque_cmd", 0.1)
    rw.do_step(t=1.0, dt=1.0)
    derated_speed = rw.read_port("aocs.rw1.speed")

    assert derated_speed < nominal_speed
    assert rw.read_port("aocs.rw1.status") == pytest.approx(0.0)


@pytest.mark.requirement("RW-002")
def test_tc_rw_fail_002_speed_clamped_at_max(
    rw: NativeEquipment,
) -> None:
    """
    TC-RW-FAIL-002: Speed cannot exceed MAX_SPEED_RPM regardless of torque.
    """
    rw.receive("aocs.rw1.torque_cmd", 0.2)
    for i in range(1000):
        rw.do_step(t=float(i), dt=1.0)

    assert rw.read_port("aocs.rw1.speed") <= MAX_SPEED_RPM
    assert rw.read_port("aocs.rw1.speed") > 0.0  # just verify it spins


@pytest.mark.requirement("RW-002")
def test_tc_rw_fail_003_negative_speed_clamped_at_min(
    rw: NativeEquipment,
) -> None:
    """
    TC-RW-FAIL-003: Speed cannot exceed -MAX_SPEED_RPM in reverse.
    """
    rw.receive("aocs.rw1.torque_cmd", -0.2)
    for i in range(1000):
        rw.do_step(t=float(i), dt=1.0)

    assert rw.read_port("aocs.rw1.speed") >= -MAX_SPEED_RPM


@pytest.mark.requirement("RW-003")
def test_tc_rw_fail_004_friction_stops_wheel(
    rw: NativeEquipment,
) -> None:
    """
    TC-RW-FAIL-004: Bearing friction decelerates wheel to near-zero
    when torque removed.
    """
    # Spin up
    rw.receive("aocs.rw1.torque_cmd", 0.1)
    for i in range(100):
        rw.do_step(t=float(i), dt=1.0)
    assert rw.read_port("aocs.rw1.speed") > 100.0

    # Remove torque — friction should decelerate
    rw.receive("aocs.rw1.torque_cmd", 0.0)
    for i in range(100, 600):
        rw.do_step(t=float(i), dt=1.0)

    assert abs(rw.read_port("aocs.rw1.speed")) < 50.0


@pytest.mark.requirement("RW-001")
def test_tc_rw_fail_005_negative_torque_reverses_wheel(
    rw: NativeEquipment,
) -> None:
    """
    TC-RW-FAIL-005: Negative torque decelerates and reverses wheel direction.
    """
    # Spin up positive
    rw.receive("aocs.rw1.torque_cmd", 0.1)
    for i in range(50):
        rw.do_step(t=float(i), dt=1.0)
    assert rw.read_port("aocs.rw1.speed") > 0.0

    # Apply negative torque
    rw.receive("aocs.rw1.torque_cmd", -0.2)
    for i in range(50, 200):
        rw.do_step(t=float(i), dt=1.0)

    assert rw.read_port("aocs.rw1.speed") < 0.0


@pytest.mark.requirement("RW-004")
def test_tc_rw_fail_006_temperature_recovers_after_spindown(
    rw: NativeEquipment,
) -> None:
    """
    TC-RW-FAIL-006: Temperature drops towards ambient after wheel stops.
    """
    # Spin up and heat
    rw.receive("aocs.rw1.torque_cmd", 0.2)
    for i in range(500):
        rw.do_step(t=float(i), dt=1.0)
    hot_temp = rw.read_port("aocs.rw1.temperature")
    assert hot_temp > AMBIENT_TEMP_C

    # Stop wheel
    rw.receive("aocs.rw1.torque_cmd", 0.0)
    for i in range(500, 1500):
        rw.do_step(t=float(i), dt=1.0)

    cool_temp = rw.read_port("aocs.rw1.temperature")
    assert cool_temp < hot_temp
