"""
Tests for AOCS sensor and actuator models:
MAG, MTQ, CSS, GYRO, ST
Implements: SVF-DEV-038
"""

import pytest
import math
from svf.abstractions import SyncProtocol
from svf.parameter_store import ParameterStore
from svf.command_store import CommandStore
from svf.native_equipment import NativeEquipment
from svf.models.magnetometer import make_magnetometer
from svf.models.magnetorquer import make_magnetorquer, MAX_DIPOLE_AM2
from svf.models.css import make_css
from svf.models.gyroscope import make_gyroscope
from svf.models.star_tracker import (
    make_star_tracker, SUN_EXCLUSION_DEG, ACQUISITION_TIME_S,
    AMBIENT_TEMP_C, MODE_OFF, MODE_ACQUIRING, MODE_TRACKING,
)


class _NoSync(SyncProtocol):
    def reset(self) -> None: pass
    def publish_ready(self, model_id: str, t: float) -> None: pass
    def wait_for_ready(self, expected: list[str], timeout: float) -> bool:
        return True


@pytest.fixture
def sync() -> _NoSync: return _NoSync()

@pytest.fixture
def store() -> ParameterStore: return ParameterStore()

@pytest.fixture
def cmd() -> CommandStore: return CommandStore()

@pytest.fixture
def st() -> NativeEquipment:
    eq = make_star_tracker(_NoSync(), ParameterStore(), CommandStore(), seed=42)
    eq.initialise()
    return eq


# ── Magnetometer ──────────────────────────────────────────────────────────────

@pytest.mark.requirement("SVF-DEV-038")
def test_mag_off_by_default(sync: _NoSync, store: ParameterStore, cmd: CommandStore) -> None:
    """MAG outputs zero when unpowered."""
    mag = make_magnetometer(sync, store, cmd, seed=42)
    mag.initialise()
    mag.do_step(t=0.0, dt=1.0)
    assert mag.read_port("aocs.mag.status") == pytest.approx(0.0)
    assert mag.read_port("aocs.mag.field_x") == pytest.approx(0.0)


@pytest.mark.requirement("SVF-DEV-038")
def test_mag_measures_true_field(sync: _NoSync, store: ParameterStore, cmd: CommandStore) -> None:
    """MAG outputs measured field close to true field when powered."""
    mag = make_magnetometer(sync, store, cmd, seed=42)
    mag.initialise()
    mag.receive("aocs.mag.power_enable", 1.0)
    mag.receive("aocs.mag.true_x", 3e-5)
    mag.receive("aocs.mag.true_y", 1e-5)
    mag.receive("aocs.mag.true_z", -4e-5)
    mag.do_step(t=0.0, dt=1.0)
    assert mag.read_port("aocs.mag.status") == pytest.approx(1.0)
    assert mag.read_port("aocs.mag.field_x") == pytest.approx(3e-5, abs=1e-6)
    assert mag.read_port("aocs.mag.field_y") == pytest.approx(1e-5, abs=1e-6)


# ── Magnetorquer ──────────────────────────────────────────────────────────────

@pytest.mark.requirement("SVF-DEV-038")
def test_mtq_off_when_unpowered(sync: _NoSync, store: ParameterStore, cmd: CommandStore) -> None:
    """MTQ outputs zero torque when unpowered."""
    mtq = make_magnetorquer(sync, store, cmd)
    mtq.initialise()
    mtq.do_step(t=0.0, dt=1.0)
    assert mtq.read_port("aocs.mtq.status") == pytest.approx(0.0)
    assert mtq.read_port("aocs.mtq.torque_x") == pytest.approx(0.0)


@pytest.mark.requirement("SVF-DEV-038")
def test_mtq_torque_is_cross_product(sync: _NoSync, store: ParameterStore, cmd: CommandStore) -> None:
    """MTQ torque = m × B (cross product)."""
    mtq = make_magnetorquer(sync, store, cmd)
    mtq.initialise()
    mtq.receive("aocs.mtq.power_enable", 1.0)
    mtq.receive("aocs.mtq.dipole_x", 1.0)
    mtq.receive("aocs.mtq.dipole_y", 0.0)
    mtq.receive("aocs.mtq.dipole_z", 0.0)
    mtq.receive("aocs.mag.field_x", 0.0)
    mtq.receive("aocs.mag.field_y", 0.0)
    mtq.receive("aocs.mag.field_z", 1e-4)
    mtq.do_step(t=0.0, dt=1.0)
    assert mtq.read_port("aocs.mtq.torque_x") == pytest.approx(0.0, abs=1e-10)
    assert mtq.read_port("aocs.mtq.torque_y") == pytest.approx(-1e-4, abs=1e-10)
    assert mtq.read_port("aocs.mtq.torque_z") == pytest.approx(0.0, abs=1e-10)


@pytest.mark.requirement("SVF-DEV-038")
def test_mtq_dipole_saturated(sync: _NoSync, store: ParameterStore, cmd: CommandStore) -> None:
    """MTQ dipole saturated at MAX_DIPOLE_AM2."""
    mtq = make_magnetorquer(sync, store, cmd)
    mtq.initialise()
    mtq.receive("aocs.mtq.power_enable", 1.0)
    mtq.receive("aocs.mtq.dipole_x", 999.0)
    mtq.receive("aocs.mag.field_z", 1e-4)
    mtq.do_step(t=0.0, dt=1.0)
    assert abs(mtq.read_port("aocs.mtq.torque_y")) == pytest.approx(
        MAX_DIPOLE_AM2 * 1e-4, abs=1e-10
    )


# ── Coarse Sun Sensor ─────────────────────────────────────────────────────────

@pytest.mark.requirement("SVF-DEV-038")
def test_css_invalid_in_eclipse(sync: _NoSync, store: ParameterStore, cmd: CommandStore) -> None:
    """CSS validity=0 in eclipse."""
    css = make_css(sync, store, cmd, seed=42)
    css.initialise()
    css.receive("aocs.css.illumination", 0.0)
    css.do_step(t=0.0, dt=1.0)
    assert css.read_port("aocs.css.validity") == pytest.approx(0.0)
    assert css.read_port("aocs.css.sun_x") == pytest.approx(0.0)


@pytest.mark.requirement("SVF-DEV-038")
def test_css_valid_in_sunlight(sync: _NoSync, store: ParameterStore, cmd: CommandStore) -> None:
    """CSS validity=1 in sunlight, sun vector has unit norm."""
    css = make_css(sync, store, cmd, seed=42)
    css.initialise()
    css.receive("aocs.css.illumination", 1.0)
    css.do_step(t=0.0, dt=1.0)
    assert css.read_port("aocs.css.validity") == pytest.approx(1.0)
    sx = css.read_port("aocs.css.sun_x")
    sy = css.read_port("aocs.css.sun_y")
    sz = css.read_port("aocs.css.sun_z")
    norm = math.sqrt(sx*sx + sy*sy + sz*sz)
    assert norm == pytest.approx(1.0, abs=0.05)


@pytest.mark.requirement("SVF-DEV-038")
def test_css_sun_vector_rotates_with_body_rate(
    sync: _NoSync, store: ParameterStore, cmd: CommandStore
) -> None:
    """Sun vector rotates when body rates applied."""
    css = make_css(sync, store, cmd, seed=42)
    css.initialise()
    css.receive("aocs.css.illumination", 1.0)
    css.do_step(t=0.0, dt=1.0)
    sz_initial = css.read_port("aocs.css.sun_z")

    css.receive("aocs.truth.rate_x", 0.1)
    for i in range(10):
        css.do_step(t=float(i), dt=1.0)

    sz_final = css.read_port("aocs.css.sun_z")
    assert sz_final != pytest.approx(sz_initial, abs=0.01)


# ── Gyroscope ─────────────────────────────────────────────────────────────────

@pytest.mark.requirement("SVF-DEV-038")
def test_gyro_off_by_default(sync: _NoSync, store: ParameterStore, cmd: CommandStore) -> None:
    """GYRO outputs zero when unpowered."""
    gyro = make_gyroscope(sync, store, cmd, seed=42)
    gyro.initialise()
    gyro.do_step(t=0.0, dt=1.0)
    assert gyro.read_port("aocs.gyro.status") == pytest.approx(0.0)
    assert gyro.read_port("aocs.gyro.rate_x") == pytest.approx(0.0)


@pytest.mark.requirement("SVF-DEV-038")
def test_gyro_measures_true_rate(sync: _NoSync, store: ParameterStore, cmd: CommandStore) -> None:
    """GYRO output close to true rate when powered."""
    gyro = make_gyroscope(sync, store, cmd, seed=42)
    gyro.initialise()
    gyro.receive("aocs.gyro.power_enable", 1.0)
    gyro.receive("aocs.truth.rate_x", 0.05)
    gyro.receive("aocs.truth.rate_y", -0.02)
    gyro.receive("aocs.truth.rate_z", 0.01)
    gyro.do_step(t=0.0, dt=0.1)
    assert gyro.read_port("aocs.gyro.status") == pytest.approx(1.0)
    assert gyro.read_port("aocs.gyro.rate_x") == pytest.approx(0.05, abs=0.01)
    assert gyro.read_port("aocs.gyro.rate_y") == pytest.approx(-0.02, abs=0.01)


@pytest.mark.requirement("SVF-DEV-038")
def test_gyro_temperature_rises_when_powered(
    sync: _NoSync, store: ParameterStore, cmd: CommandStore
) -> None:
    """GYRO temperature rises when powered on."""
    gyro = make_gyroscope(sync, store, cmd, seed=42)
    gyro.initialise()
    gyro.receive("aocs.gyro.power_enable", 1.0)
    for i in range(100):
        gyro.do_step(t=float(i), dt=1.0)
    assert gyro.read_port("aocs.gyro.temperature") > 20.0


# ── Star Tracker ──────────────────────────────────────────────────────────────

def power_on(st: NativeEquipment) -> None:
    st.receive("aocs.str1.power_enable", 1.0)
    st.receive("aocs.str1.sun_angle", 90.0)


def step_n(st: NativeEquipment, n: int, dt: float = 1.0) -> None:
    for i in range(n):
        st.do_step(t=float(i) * dt, dt=dt)


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


@pytest.mark.requirement("SVF-DEV-038")
def test_st_blinded_when_sun_angle_below_exclusion(st: NativeEquipment) -> None:
    """Validity goes to 0 when sun_angle < SUN_EXCLUSION_DEG."""
    power_on(st)
    step_n(st, int(ACQUISITION_TIME_S) + 2)
    assert st.read_port("aocs.str1.validity") == pytest.approx(1.0)
    st.receive("aocs.str1.sun_angle", SUN_EXCLUSION_DEG - 1.0)
    st.do_step(t=float(ACQUISITION_TIME_S) + 2, dt=1.0)
    assert st.read_port("aocs.str1.validity") == pytest.approx(0.0)


@pytest.mark.requirement("SVF-DEV-038")
def test_st_reacquires_after_blinding(st: NativeEquipment) -> None:
    """ST re-enters ACQUIRING after sun blinding clears."""
    power_on(st)
    step_n(st, int(ACQUISITION_TIME_S) + 2)
    st.receive("aocs.str1.sun_angle", 5.0)
    st.do_step(t=15.0, dt=1.0)
    st.receive("aocs.str1.sun_angle", 90.0)
    st.do_step(t=16.0, dt=1.0)
    assert st.read_port("aocs.str1.mode") == pytest.approx(MODE_ACQUIRING)


@pytest.mark.requirement("SVF-DEV-038")
def test_st_quaternion_unit_norm_when_tracking(st: NativeEquipment) -> None:
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
    st.do_step(t=0.0, dt=1.0)
    assert st.read_port("aocs.str1.quaternion_w") == pytest.approx(0.0)
    assert st.read_port("aocs.str1.quaternion_x") == pytest.approx(0.0)


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
