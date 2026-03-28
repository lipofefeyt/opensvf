"""
Tests for Star Tracker model.
Quaternion output, noise, blinding, acquisition.
Implements: SVF-DEV-038
"""

import pytest
import math
from svf.abstractions import SyncProtocol
from svf.parameter_store import ParameterStore
from svf.command_store import CommandStore
from svf.models.star_tracker import (
    make_star_tracker, SUN_EXCLUSION_DEG,
    ACQUISITION_TIME_S, AMBIENT_TEMP_C, MODE_OFF,
    MODE_ACQUIRING, MODE_TRACKING,
)
from svf.native_equipment import NativeEquipment


class _NoSync(SyncProtocol):
    def reset(self) -> None: pass
    def publish_ready(self, model_id: str, t: float) -> None: pass
    def wait_for_ready(self, expected: list[str], timeout: float) -> bool:
        return True


@pytest.fixture
def st() -> NativeEquipment:
    sync  = _NoSync()
    store = ParameterStore()
    cmd   = CommandStore()
    eq = make_star_tracker(sync, store, cmd, seed=42)
    eq.initialise()
    return eq


def power_on(st: NativeEquipment) -> None:
    st.receive("aocs.str1.power_enable", 1.0)
    st.receive("aocs.str1.sun_angle", 90.0)


def step_n(st: NativeEquipment, n: int, dt: float = 1.0) -> None:
    for i in range(n):
        st.do_step(t=float(i) * dt, dt=dt)


# ── Power and mode ────────────────────────────────────────────────────────────

@pytest.mark.requirement("SVF-DEV-038")
def test_st_off_by_default(st: NativeEquipment) -> None:
    """ST starts in OFF mode, validity=0."""
    st.do_step(t=0.0, dt=1.0)
    assert st.read_port("aocs.str1.mode") == pytest.approx(MODE_OFF)
    assert st.read_port("aocs.str1.validity") == pytest.approx(0.0)


@pytest.mark.requirement("SVF-DEV-038")
def test_st_enters_acquiring_on_power_on(st: NativeEquipment) -> None:
    """ST enters ACQUIRING mode immediately on power on."""
    power_on(st)
    st.do_step(t=0.0, dt=1.0)
    assert st.read_port("aocs.str1.mode") == pytest.approx(MODE_ACQUIRING)


@pytest.mark.requirement("SVF-DEV-038")
def test_st_enters_tracking_after_acquisition(st: NativeEquipment) -> None:
    """ST enters TRACKING after ACQUISITION_TIME_S seconds."""
    power_on(st)
    step_n(st, int(ACQUISITION_TIME_S) + 2)
    assert st.read_port("aocs.str1.mode") == pytest.approx(MODE_TRACKING)
    assert st.read_port("aocs.str1.validity") == pytest.approx(1.0)


@pytest.mark.requirement("SVF-DEV-038")
def test_st_acquisition_progress(st: NativeEquipment) -> None:
    """Acquisition progress goes from 0 to 1 over ACQUISITION_TIME_S."""
    power_on(st)
    st.do_step(t=0.0, dt=1.0)
    progress_early = st.read_port("aocs.str1.acquisition_progress")

    step_n(st, int(ACQUISITION_TIME_S) + 2)
    progress_done = st.read_port("aocs.str1.acquisition_progress")

    assert progress_early < progress_done
    assert progress_done == pytest.approx(1.0)


# ── Sun blinding ──────────────────────────────────────────────────────────────

@pytest.mark.requirement("SVF-DEV-038")
def test_st_blinded_when_sun_angle_below_exclusion(
    st: NativeEquipment,
) -> None:
    """Validity goes to 0 when sun_angle < SUN_EXCLUSION_DEG."""
    power_on(st)
    step_n(st, int(ACQUISITION_TIME_S) + 2)
    assert st.read_port("aocs.str1.validity") == pytest.approx(1.0)

    # Sun enters exclusion zone
    st.receive("aocs.str1.sun_angle", SUN_EXCLUSION_DEG - 1.0)
    st.do_step(t=float(ACQUISITION_TIME_S) + 2, dt=1.0)
    assert st.read_port("aocs.str1.validity") == pytest.approx(0.0)


@pytest.mark.requirement("SVF-DEV-038")
def test_st_reacquires_after_blinding(st: NativeEquipment) -> None:
    """ST re-enters ACQUIRING after sun blinding clears."""
    power_on(st)
    step_n(st, int(ACQUISITION_TIME_S) + 2)

    # Blind then clear
    st.receive("aocs.str1.sun_angle", 5.0)
    st.do_step(t=15.0, dt=1.0)
    st.receive("aocs.str1.sun_angle", 90.0)
    st.do_step(t=16.0, dt=1.0)
    assert st.read_port("aocs.str1.mode") == pytest.approx(MODE_ACQUIRING)


# ── Quaternion output ─────────────────────────────────────────────────────────

@pytest.mark.requirement("SVF-DEV-038")
def test_st_quaternion_unit_norm_when_tracking(
    st: NativeEquipment,
) -> None:
    """Output quaternion has unit norm when tracking."""
    power_on(st)
    step_n(st, int(ACQUISITION_TIME_S) + 2)

    w = st.read_port("aocs.str1.quaternion_w")
    x = st.read_port("aocs.str1.quaternion_x")
    y = st.read_port("aocs.str1.quaternion_y")
    z = st.read_port("aocs.str1.quaternion_z")
    norm = math.sqrt(w*w + x*x + y*y + z*z)
    assert norm == pytest.approx(1.0, abs=0.01)


@pytest.mark.requirement("SVF-DEV-038")
def test_st_quaternion_zero_when_invalid(st: NativeEquipment) -> None:
    """Output quaternion is zero when validity=0."""
    st.do_step(t=0.0, dt=1.0)  # powered off
    assert st.read_port("aocs.str1.quaternion_w") == pytest.approx(0.0)
    assert st.read_port("aocs.str1.quaternion_x") == pytest.approx(0.0)


# ── Temperature ───────────────────────────────────────────────────────────────

@pytest.mark.requirement("SVF-DEV-038")
def test_st_temperature_rises_when_powered(st: NativeEquipment) -> None:
    """Temperature rises towards nominal when powered on."""
    power_on(st)
    step_n(st, 100)
    assert st.read_port("aocs.str1.temperature") > AMBIENT_TEMP_C


@pytest.mark.requirement("SVF-DEV-038")
def test_st_temperature_drops_when_off(st: NativeEquipment) -> None:
    """Temperature drops towards ambient when powered off."""
    power_on(st)
    step_n(st, 100)
    hot_temp = st.read_port("aocs.str1.temperature")

    st.receive("aocs.str1.power_enable", 0.0)
    step_n(st, 100)
    cool_temp = st.read_port("aocs.str1.temperature")

    assert cool_temp < hot_temp
