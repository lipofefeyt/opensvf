"""
SVF Star Tracker Failure Test Procedures
Exercises ST failure modes and boundary conditions.

TC-ST-FAIL-001: Sun blinding — validity drops, re-acquisition triggered
TC-ST-FAIL-002: Power cycle — cold start acquisition from scratch
TC-ST-FAIL-003: Sustained blinding — validity stays 0 while sun in FOV
TC-ST-FAIL-004: Power off mid-tracking — validity drops immediately
TC-ST-FAIL-005: Blinding clears — ST re-acquires and becomes valid again

Implements: ST-001 through ST-008
"""

import pytest
import math
from svf.abstractions import SyncProtocol
from svf.parameter_store import ParameterStore
from svf.command_store import CommandStore
from svf.models.aocs.star_tracker import (
    make_star_tracker, SUN_EXCLUSION_DEG, ACQUISITION_TIME_S,
    AMBIENT_TEMP_C, MODE_OFF, MODE_ACQUIRING, MODE_TRACKING,
)
from svf.native_equipment import NativeEquipment


class _NoSync(SyncProtocol):
    def reset(self) -> None: pass
    def publish_ready(self, model_id: str, t: float) -> None: pass
    def wait_for_ready(self, expected: list[str], timeout: float) -> bool:
        return True


@pytest.fixture
def st() -> NativeEquipment:
    eq = make_star_tracker(_NoSync(), ParameterStore(), CommandStore(), seed=42)
    eq.initialise()
    return eq


def power_on(st: NativeEquipment, sun_angle: float = 90.0) -> None:
    st.receive("aocs.str1.power_enable", 1.0)
    st.receive("aocs.str1.sun_angle", sun_angle)


def step_to_tracking(st: NativeEquipment) -> None:
    """Step until ST reaches TRACKING mode."""
    power_on(st)
    for i in range(int(ACQUISITION_TIME_S) + 2):
        st.do_step(t=float(i), dt=1.0)
    assert st.read_port("aocs.str1.mode") == pytest.approx(MODE_TRACKING)


@pytest.mark.requirement("ST-003")
def test_tc_st_fail_001_sun_blinding_drops_validity(
    st: NativeEquipment,
) -> None:
    """
    TC-ST-FAIL-001: Sun blinding — validity drops when sun enters FOV.
    ST should re-enter ACQUIRING mode.
    """
    step_to_tracking(st)
    assert st.read_port("aocs.str1.validity") == pytest.approx(1.0)

    # Sun enters exclusion zone
    st.receive("aocs.str1.sun_angle", SUN_EXCLUSION_DEG - 1.0)
    st.do_step(t=float(ACQUISITION_TIME_S) + 2, dt=1.0)

    assert st.read_port("aocs.str1.validity") == pytest.approx(0.0)
    assert st.read_port("aocs.str1.mode") == pytest.approx(MODE_ACQUIRING)


@pytest.mark.requirement("ST-001", "ST-002")
def test_tc_st_fail_002_power_cycle_resets_acquisition(
    st: NativeEquipment,
) -> None:
    """
    TC-ST-FAIL-002: Power cycle forces cold start — acquisition restarts.
    """
    step_to_tracking(st)
    assert st.read_port("aocs.str1.validity") == pytest.approx(1.0)

    # Power off
    st.receive("aocs.str1.power_enable", 0.0)
    st.do_step(t=float(ACQUISITION_TIME_S) + 3, dt=1.0)
    assert st.read_port("aocs.str1.mode") == pytest.approx(MODE_OFF)
    assert st.read_port("aocs.str1.validity") == pytest.approx(0.0)

    # Power on again — must re-acquire from scratch
    st.receive("aocs.str1.power_enable", 1.0)
    st.receive("aocs.str1.sun_angle", 90.0)
    st.do_step(t=float(ACQUISITION_TIME_S) + 4, dt=1.0)
    assert st.read_port("aocs.str1.mode") == pytest.approx(MODE_ACQUIRING)
    assert st.read_port("aocs.str1.validity") == pytest.approx(0.0)


@pytest.mark.requirement("ST-003")
def test_tc_st_fail_003_sustained_blinding_stays_invalid(
    st: NativeEquipment,
) -> None:
    """
    TC-ST-FAIL-003: Validity stays 0 while sun remains in exclusion zone.
    """
    step_to_tracking(st)

    # Keep sun in exclusion zone
    st.receive("aocs.str1.sun_angle", 5.0)
    for i in range(int(ACQUISITION_TIME_S) + 20):
        st.do_step(t=float(ACQUISITION_TIME_S) + 2 + float(i), dt=1.0)

    assert st.read_port("aocs.str1.validity") == pytest.approx(0.0)


@pytest.mark.requirement("ST-001", "ST-002")
def test_tc_st_fail_004_power_off_mid_tracking_drops_validity(
    st: NativeEquipment,
) -> None:
    """
    TC-ST-FAIL-004: Powering off during tracking immediately invalidates output.
    """
    step_to_tracking(st)
    assert st.read_port("aocs.str1.validity") == pytest.approx(1.0)

    st.receive("aocs.str1.power_enable", 0.0)
    st.do_step(t=float(ACQUISITION_TIME_S) + 3, dt=1.0)

    assert st.read_port("aocs.str1.validity") == pytest.approx(0.0)
    assert st.read_port("aocs.str1.mode") == pytest.approx(MODE_OFF)
    assert st.read_port("aocs.str1.quaternion_w") == pytest.approx(0.0)


@pytest.mark.requirement("ST-003", "ST-001")
def test_tc_st_fail_005_blinding_clears_st_reacquires(
    st: NativeEquipment,
) -> None:
    """
    TC-ST-FAIL-005: After blinding clears ST re-acquires and becomes valid.
    """
    step_to_tracking(st)

    # Blind
    t = float(ACQUISITION_TIME_S) + 2
    st.receive("aocs.str1.sun_angle", 5.0)
    st.do_step(t=t, dt=1.0)
    assert st.read_port("aocs.str1.validity") == pytest.approx(0.0)

    # Clear blinding — step through acquisition
    st.receive("aocs.str1.sun_angle", 90.0)
    for i in range(int(ACQUISITION_TIME_S) + 3):
        t += 1.0
        st.do_step(t=t, dt=1.0)

    assert st.read_port("aocs.str1.validity") == pytest.approx(1.0)
    assert st.read_port("aocs.str1.mode") == pytest.approx(MODE_TRACKING)


@pytest.mark.requirement("ST-005")
def test_tc_st_fail_006_quaternion_unit_norm_after_blinding_recovery(
    st: NativeEquipment,
) -> None:
    """
    TC-ST-FAIL-006: Quaternion has unit norm after blinding recovery.
    """
    step_to_tracking(st)

    # Blind then recover
    t = float(ACQUISITION_TIME_S) + 2
    st.receive("aocs.str1.sun_angle", 5.0)
    st.do_step(t=t, dt=1.0)
    st.receive("aocs.str1.sun_angle", 90.0)
    for i in range(int(ACQUISITION_TIME_S) + 3):
        t += 1.0
        st.do_step(t=t, dt=1.0)

    w = st.read_port("aocs.str1.quaternion_w")
    x = st.read_port("aocs.str1.quaternion_x")
    y = st.read_port("aocs.str1.quaternion_y")
    z = st.read_port("aocs.str1.quaternion_z")
    norm = math.sqrt(w*w + x*x + y*y + z*z)
    assert norm == pytest.approx(1.0, abs=0.01)
