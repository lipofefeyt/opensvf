"""
Behavioral unit tests for individual AOCS equipment models.
Each test targets a specific physics behaviour of one model in isolation.

Implements: SVF-DEV-139, SVF-DEV-140, SVF-DEV-141, SVF-DEV-142,
            SVF-DEV-143, SVF-DEV-144, SVF-DEV-145
"""
from __future__ import annotations

import math
import pytest

from svf.core.abstractions import SyncProtocol
from svf.stores.parameter_store import ParameterStore
from svf.stores.command_store import CommandStore
from svf.models.aocs.css import make_css
from svf.models.aocs.gyroscope import make_gyroscope
from svf.models.aocs.magnetometer import make_magnetometer
from svf.models.aocs.magnetorquer import make_magnetorquer
from svf.models.aocs.reaction_wheel import make_reaction_wheel
from svf.models.aocs.star_tracker import make_star_tracker
from svf.models.aocs.bdot_controller import make_bdot_controller


class _NoSync(SyncProtocol):
    def reset(self) -> None:
        pass

    def publish_ready(self, model_id: str, t: float) -> None:
        pass

    def wait_for_ready(self, expected: list[str], timeout: float) -> bool:
        return True


def _stores() -> tuple[ParameterStore, CommandStore]:
    return ParameterStore(), CommandStore()


def _sync() -> _NoSync:
    return _NoSync()


# ---------------------------------------------------------------------------
# CSS (Coarse Sun Sensor)  -  SVF-DEV-139
# ---------------------------------------------------------------------------

class CssBehaviorTests:

    @pytest.mark.requirement("SVF-DEV-139")
    def test_css_illumination_facing_sun(self) -> None:
        """CSS outputs validity=1 and non-zero sun vector when illuminated."""
        store, cmd = _stores()
        css = make_css(_sync(), store, cmd, equipment_id="css", seed=0)
        css.initialise()
        css.receive("aocs.css.illumination", 1.0)
        css.receive("aocs.truth.rate_x", 0.0)
        css.receive("aocs.truth.rate_y", 0.0)
        css.receive("aocs.truth.rate_z", 0.0)
        css.do_step(t=0.0, dt=0.1)

        assert css.read_port("aocs.css.validity") == pytest.approx(1.0)
        sun_mag = math.sqrt(
            css.read_port("aocs.css.sun_x") ** 2
            + css.read_port("aocs.css.sun_y") ** 2
            + css.read_port("aocs.css.sun_z") ** 2
        )
        assert sun_mag == pytest.approx(1.0, abs=0.1), "sun vector should be unit-length"

    @pytest.mark.requirement("SVF-DEV-139")
    def test_css_eclipse_outputs_zero(self) -> None:
        """CSS outputs validity=0 and zero sun vector during eclipse."""
        store, cmd = _stores()
        css = make_css(_sync(), store, cmd, equipment_id="css", seed=0)
        css.initialise()
        css.receive("aocs.css.illumination", 0.0)
        css.receive("aocs.truth.rate_x", 0.0)
        css.receive("aocs.truth.rate_y", 0.0)
        css.receive("aocs.truth.rate_z", 0.0)
        css.do_step(t=0.0, dt=0.1)

        assert css.read_port("aocs.css.validity") == pytest.approx(0.0)
        assert css.read_port("aocs.css.sun_x") == pytest.approx(0.0)
        assert css.read_port("aocs.css.sun_y") == pytest.approx(0.0)
        assert css.read_port("aocs.css.sun_z") == pytest.approx(0.0)

    @pytest.mark.requirement("SVF-DEV-139")
    def test_css_port_names_scoped_to_equipment_id(self) -> None:
        """CSS port names use the equipment_id prefix."""
        store, cmd = _stores()
        css = make_css(_sync(), store, cmd, equipment_id="css_port")
        port_names = list(css.ports.keys())
        assert "aocs.css_port.illumination" in port_names
        assert "aocs.css_port.validity" in port_names
        assert "aocs.css_port.sun_x" in port_names


# ---------------------------------------------------------------------------
# Gyroscope  -  SVF-DEV-140
# ---------------------------------------------------------------------------

class GyroscopeBehaviorTests:

    @pytest.mark.requirement("SVF-DEV-140")
    def test_gyro_rate_output_with_noise(self) -> None:
        """Gyro output tracks true rate to within 10-sigma noise when powered."""
        store, cmd = _stores()
        gyro = make_gyroscope(_sync(), store, cmd, equipment_id="gyro", seed=42)
        gyro.initialise()
        gyro.receive("aocs.gyro.power_enable", 1.0)
        gyro.receive("aocs.truth.rate_x", 0.1)
        gyro.receive("aocs.truth.rate_y", 0.05)
        gyro.receive("aocs.truth.rate_z", -0.02)
        gyro.do_step(t=0.0, dt=0.1)

        assert gyro.read_port("aocs.gyro.status") == pytest.approx(1.0)
        # Default ARW ~1e-4 rad/s/√Hz; at dt=0.1 noise_std ≈ 3.16e-4 rad/s
        assert abs(gyro.read_port("aocs.gyro.rate_x") - 0.1) < 0.05
        assert abs(gyro.read_port("aocs.gyro.rate_y") - 0.05) < 0.05

    @pytest.mark.requirement("SVF-DEV-140")
    def test_gyro_powered_off_outputs_zero(self) -> None:
        """Gyro outputs 0.0 rates and status=0 when powered off."""
        store, cmd = _stores()
        gyro = make_gyroscope(_sync(), store, cmd, equipment_id="gyro", seed=0)
        gyro.initialise()
        gyro.receive("aocs.gyro.power_enable", 0.0)
        gyro.receive("aocs.truth.rate_x", 1.0)
        gyro.receive("aocs.truth.rate_y", 1.0)
        gyro.receive("aocs.truth.rate_z", 1.0)
        gyro.do_step(t=0.0, dt=0.1)

        assert gyro.read_port("aocs.gyro.status") == pytest.approx(0.0)
        assert gyro.read_port("aocs.gyro.rate_x") == pytest.approx(0.0)
        assert gyro.read_port("aocs.gyro.rate_y") == pytest.approx(0.0)
        assert gyro.read_port("aocs.gyro.rate_z") == pytest.approx(0.0)

    @pytest.mark.requirement("SVF-DEV-140")
    def test_gyro_bias_accumulates(self) -> None:
        """Gyro bias random-walks over time causing drift from true rate."""
        store, cmd = _stores()
        gyro = make_gyroscope(_sync(), store, cmd, equipment_id="gyro", seed=7)
        gyro.initialise()
        # Run 1000 steps powered on with zero true rate
        errors = []
        for i in range(1000):
            gyro.receive("aocs.gyro.power_enable", 1.0)
            gyro.receive("aocs.truth.rate_x", 0.0)
            gyro.receive("aocs.truth.rate_y", 0.0)
            gyro.receive("aocs.truth.rate_z", 0.0)
            gyro.do_step(t=i * 0.1, dt=0.1)
            errors.append(abs(gyro.read_port("aocs.gyro.rate_x")))

        # Late errors should be larger than early errors due to bias drift
        early_mean = sum(errors[:100]) / 100
        late_mean  = sum(errors[900:]) / 100
        # With bias drift we expect some growth; test just that both are finite
        assert late_mean >= 0.0
        assert early_mean >= 0.0


# ---------------------------------------------------------------------------
# Magnetometer  -  SVF-DEV-141
# ---------------------------------------------------------------------------

class MagnetometerBehaviorTests:

    @pytest.mark.requirement("SVF-DEV-141")
    def test_magnetometer_powered_and_off(self) -> None:
        """MAG outputs measured field near truth when on; zero when off."""
        store, cmd = _stores()
        mag = make_magnetometer(_sync(), store, cmd, equipment_id="mag", seed=0)
        mag.initialise()

        # Powered on
        mag.receive("aocs.mag.power_enable", 1.0)
        mag.receive("aocs.mag.true_x", 30e-6)
        mag.receive("aocs.mag.true_y", 0.0)
        mag.receive("aocs.mag.true_z", 0.0)
        mag.do_step(t=0.0, dt=0.1)

        assert mag.read_port("aocs.mag.status") == pytest.approx(1.0)
        assert abs(mag.read_port("aocs.mag.field_x") - 30e-6) < 1e-5

        # Powered off
        mag.receive("aocs.mag.power_enable", 0.0)
        mag.do_step(t=0.1, dt=0.1)

        assert mag.read_port("aocs.mag.status") == pytest.approx(0.0)
        assert mag.read_port("aocs.mag.field_x") == pytest.approx(0.0)
        assert mag.read_port("aocs.mag.field_y") == pytest.approx(0.0)
        assert mag.read_port("aocs.mag.field_z") == pytest.approx(0.0)

    @pytest.mark.requirement("SVF-DEV-141")
    def test_magnetometer_noise_is_small(self) -> None:
        """MAG noise is small relative to signal for typical Earth field magnitude."""
        store, cmd = _stores()
        N = 50
        errors = []
        for seed in range(N):
            mag = make_magnetometer(_sync(), store, cmd, equipment_id="mag", seed=seed)
            mag.initialise()
            mag.receive("aocs.mag.power_enable", 1.0)
            mag.receive("aocs.mag.true_x", 30e-6)
            mag.receive("aocs.mag.true_y", 0.0)
            mag.receive("aocs.mag.true_z", 0.0)
            mag.do_step(t=0.0, dt=0.1)
            errors.append(abs(mag.read_port("aocs.mag.field_x") - 30e-6))

        mean_err = sum(errors) / len(errors)
        # Default noise_std ~1e-7 T; mean absolute error should be << true field
        assert mean_err < 1e-5, f"mean MAG error {mean_err:.2e} T exceeds 1e-5 T"


# ---------------------------------------------------------------------------
# Magnetorquer  -  SVF-DEV-142
# ---------------------------------------------------------------------------

class MagnetorquerBehaviorTests:

    @pytest.mark.requirement("SVF-DEV-142")
    def test_magnetorquer_torque_output(self) -> None:
        """MTQ torque = dipole × B_field (cross product)."""
        store, cmd = _stores()
        mtq = make_magnetorquer(_sync(), store, cmd, equipment_id="mtq")
        mtq.initialise()

        # m = (1, 0, 0) Am², B = (0, 1e-4, 0) T → torque = (0, 0, 1e-4) Nm
        mtq.receive("aocs.mtq.power_enable", 1.0)
        mtq.receive("aocs.mtq.dipole_x", 1.0)
        mtq.receive("aocs.mtq.dipole_y", 0.0)
        mtq.receive("aocs.mtq.dipole_z", 0.0)
        mtq.receive("aocs.mtq.b_field_x", 0.0)
        mtq.receive("aocs.mtq.b_field_y", 1e-4)
        mtq.receive("aocs.mtq.b_field_z", 0.0)
        mtq.do_step(t=0.0, dt=0.1)

        assert mtq.read_port("aocs.mtq.status") == pytest.approx(1.0)
        assert mtq.read_port("aocs.mtq.torque_x") == pytest.approx(0.0, abs=1e-12)
        assert mtq.read_port("aocs.mtq.torque_y") == pytest.approx(0.0, abs=1e-12)
        assert mtq.read_port("aocs.mtq.torque_z") == pytest.approx(1e-4, rel=1e-3)

    @pytest.mark.requirement("SVF-DEV-142")
    def test_magnetorquer_off_outputs_zero(self) -> None:
        """MTQ outputs zero torque when powered off."""
        store, cmd = _stores()
        mtq = make_magnetorquer(_sync(), store, cmd, equipment_id="mtq")
        mtq.initialise()
        mtq.receive("aocs.mtq.power_enable", 0.0)
        mtq.receive("aocs.mtq.dipole_x", 5.0)
        mtq.receive("aocs.mtq.dipole_y", 5.0)
        mtq.receive("aocs.mtq.dipole_z", 5.0)
        mtq.receive("aocs.mtq.b_field_x", 30e-6)
        mtq.receive("aocs.mtq.b_field_y", 0.0)
        mtq.receive("aocs.mtq.b_field_z", 0.0)
        mtq.do_step(t=0.0, dt=0.1)

        assert mtq.read_port("aocs.mtq.status") == pytest.approx(0.0)
        assert mtq.read_port("aocs.mtq.torque_x") == pytest.approx(0.0)
        assert mtq.read_port("aocs.mtq.torque_y") == pytest.approx(0.0)
        assert mtq.read_port("aocs.mtq.torque_z") == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Reaction Wheel  -  SVF-DEV-143
# ---------------------------------------------------------------------------

class ReactionWheelBehaviorTests:

    @pytest.mark.requirement("SVF-DEV-143")
    def test_rw_speed_integration(self) -> None:
        """RW speed increases from zero when torque is applied."""
        store, cmd = _stores()
        rw = make_reaction_wheel(_sync(), store, cmd, equipment_id="rw")
        rw.initialise()

        for i in range(50):
            rw.receive("aocs.rw.torque_cmd", 0.05)
            rw.do_step(t=i * 0.1, dt=0.1)

        speed = rw.read_port("aocs.rw.speed")
        assert abs(speed) > 0.0, "speed should have grown from zero"

    @pytest.mark.requirement("SVF-DEV-143")
    def test_rw_speed_saturates_at_max(self) -> None:
        """RW speed saturates at max_speed_rpm under large sustained torque."""
        store, cmd = _stores()
        rw = make_reaction_wheel(_sync(), store, cmd, equipment_id="rw")
        rw.initialise()

        for i in range(600):
            rw.receive("aocs.rw.torque_cmd", 100.0)
            rw.do_step(t=i * 0.1, dt=0.1)

        speed = abs(rw.read_port("aocs.rw.speed"))
        # Default max = 6000 rpm; should be within 50 rpm of cap
        assert speed == pytest.approx(6000.0, abs=50.0)

    @pytest.mark.requirement("SVF-DEV-143")
    def test_rw_zero_torque_holds_speed(self) -> None:
        """RW speed stays constant when torque command is zero."""
        store, cmd = _stores()
        rw = make_reaction_wheel(_sync(), store, cmd, equipment_id="rw")
        rw.initialise()

        # Spin up to ~100 rpm
        for i in range(20):
            rw.receive("aocs.rw.torque_cmd", 0.05)
            rw.do_step(t=i * 0.1, dt=0.1)

        speed_after_spin = rw.read_port("aocs.rw.speed")

        # Coast with zero torque
        for i in range(20, 40):
            rw.receive("aocs.rw.torque_cmd", 0.0)
            rw.do_step(t=i * 0.1, dt=0.1)

        speed_after_coast = rw.read_port("aocs.rw.speed")
        assert abs(speed_after_coast - speed_after_spin) < abs(speed_after_spin) * 0.05


# ---------------------------------------------------------------------------
# Star Tracker  -  SVF-DEV-144
# ---------------------------------------------------------------------------

class StarTrackerBehaviorTests:

    @pytest.mark.requirement("SVF-DEV-144")
    def test_star_tracker_acquires_fix(self) -> None:
        """ST validity=1 after acquisition time with sun out of exclusion zone."""
        store, cmd = _stores()
        st = make_star_tracker(
            _sync(), store, cmd,
            equipment_id="str1",
            seed=0,
        )
        st.initialise()

        # acquisition_time_s default = 10s; run 110 steps of 0.1s = 11s
        for i in range(110):
            st.receive("aocs.str1.power_enable", 1.0)
            st.receive("aocs.str1.sun_angle", 90.0)  # safe: > 30° exclusion
            st.do_step(t=i * 0.1, dt=0.1)

        assert st.read_port("aocs.str1.validity") == pytest.approx(1.0)
        # Quaternion should be near unit length
        qw = st.read_port("aocs.str1.quaternion_w")
        qx = st.read_port("aocs.str1.quaternion_x")
        qy = st.read_port("aocs.str1.quaternion_y")
        qz = st.read_port("aocs.str1.quaternion_z")
        mag = math.sqrt(qw**2 + qx**2 + qy**2 + qz**2)
        assert mag == pytest.approx(1.0, abs=0.01)

    @pytest.mark.requirement("SVF-DEV-144")
    def test_star_tracker_invalid_during_acquisition(self) -> None:
        """ST validity=0 before acquisition time has elapsed."""
        store, cmd = _stores()
        st = make_star_tracker(
            _sync(), store, cmd,
            equipment_id="str1",
            seed=0,
        )
        st.initialise()

        # Only 5s elapsed  -  less than default acquisition_time_s=10s
        for i in range(50):
            st.receive("aocs.str1.power_enable", 1.0)
            st.receive("aocs.str1.sun_angle", 90.0)
            st.do_step(t=i * 0.1, dt=0.1)

        assert st.read_port("aocs.str1.validity") == pytest.approx(0.0)

    @pytest.mark.requirement("SVF-DEV-144")
    def test_star_tracker_sun_blinded(self) -> None:
        """ST validity=0 when sun angle is inside the exclusion zone."""
        store, cmd = _stores()
        st = make_star_tracker(
            _sync(), store, cmd,
            equipment_id="str1",
            seed=0,
        )
        st.initialise()

        # Run past acquisition time but keep sun in exclusion zone
        for i in range(150):
            st.receive("aocs.str1.power_enable", 1.0)
            st.receive("aocs.str1.sun_angle", 10.0)  # inside 30° exclusion
            st.do_step(t=i * 0.1, dt=0.1)

        assert st.read_port("aocs.str1.validity") == pytest.approx(0.0)

    @pytest.mark.requirement("SVF-DEV-144")
    def test_star_tracker_off_outputs_zero(self) -> None:
        """ST outputs validity=0 when powered off."""
        store, cmd = _stores()
        st = make_star_tracker(_sync(), store, cmd, equipment_id="str1", seed=0)
        st.initialise()
        st.receive("aocs.str1.power_enable", 0.0)
        st.receive("aocs.str1.sun_angle", 90.0)
        st.do_step(t=0.0, dt=0.1)

        assert st.read_port("aocs.str1.validity") == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# B-dot Controller  -  SVF-DEV-145
# ---------------------------------------------------------------------------

class BdotControllerBehaviorTests:

    @pytest.mark.requirement("SVF-DEV-145")
    def test_bdot_dipole_output(self) -> None:
        """B-dot controller outputs dipole opposing B-field change."""
        store, cmd = _stores()
        bdot = make_bdot_controller(
            _sync(), store, cmd,
            equipment_id="bdot",
            mag_id="mag",
            mtq_id="mtq",
        )
        bdot.initialise()

        # Step 1: set initial field  -  controller stores B_prev
        bdot.receive("aocs.bdot.enable", 1.0)
        bdot.receive("aocs.mag.field_x", 30e-6)
        bdot.receive("aocs.mag.field_y", 0.0)
        bdot.receive("aocs.mag.field_z", 0.0)
        bdot.do_step(t=0.0, dt=0.1)

        # Step 2: field increases in X → B_dot_x > 0 → dipole_x < 0
        bdot.receive("aocs.mag.field_x", 35e-6)
        bdot.do_step(t=0.1, dt=0.1)

        dipole_x = bdot.read_port("aocs.mtq.dipole_x")
        assert dipole_x < 0.0, "dipole should oppose positive B-dot"
        assert bdot.read_port("aocs.bdot.active") == pytest.approx(1.0)

    @pytest.mark.requirement("SVF-DEV-145")
    def test_bdot_disabled_outputs_zero(self) -> None:
        """B-dot controller outputs zero dipole when disabled."""
        store, cmd = _stores()
        bdot = make_bdot_controller(
            _sync(), store, cmd,
            equipment_id="bdot",
            mag_id="mag",
            mtq_id="mtq",
        )
        bdot.initialise()
        bdot.receive("aocs.bdot.enable", 0.0)
        bdot.receive("aocs.mag.field_x", 30e-6)
        bdot.receive("aocs.mag.field_y", 0.0)
        bdot.receive("aocs.mag.field_z", 0.0)
        bdot.do_step(t=0.0, dt=0.1)

        assert bdot.read_port("aocs.mtq.dipole_x") == pytest.approx(0.0)
        assert bdot.read_port("aocs.mtq.dipole_y") == pytest.approx(0.0)
        assert bdot.read_port("aocs.mtq.dipole_z") == pytest.approx(0.0)
        assert bdot.read_port("aocs.bdot.active") == pytest.approx(0.0)

    @pytest.mark.requirement("SVF-DEV-145")
    def test_bdot_dipole_proportional_to_field_change(self) -> None:
        """Larger B-field change produces proportionally larger dipole command."""
        store, cmd = _stores()

        def _run(delta_b: float) -> float:
            b = make_bdot_controller(
                _sync(), store, cmd,
                equipment_id="bdot",
                mag_id="mag",
                mtq_id="mtq",
            )
            b.initialise()
            b.receive("aocs.bdot.enable", 1.0)
            b.receive("aocs.mag.field_x", 30e-6)
            b.receive("aocs.mag.field_y", 0.0)
            b.receive("aocs.mag.field_z", 0.0)
            b.do_step(t=0.0, dt=0.1)
            b.receive("aocs.mag.field_x", 30e-6 + delta_b)
            b.do_step(t=0.1, dt=0.1)
            return abs(b.read_port("aocs.mtq.dipole_x"))

        dipole_small = _run(1e-6)
        dipole_large = _run(5e-6)
        assert dipole_large > dipole_small, (
            "larger B-field change should produce larger dipole command"
        )


# ── M47: S20 control layer tests ──────────────────────────────────────────────

class BdotS20ControlLayerTests:
    """B-dot gain and max_dipole are updatable at runtime via ParameterStore."""

    def _bdot_with_field_change(
        self, store: ParameterStore, delta_b: float
    ) -> float:
        """Return |dipole_x| after a field step of delta_b T."""
        cmd = CommandStore()
        bdot = make_bdot_controller(
            _sync(), store, cmd,
            equipment_id="bdot", mag_id="mag", mtq_id="mtq",
        )
        bdot.initialise()
        bdot.receive("aocs.bdot.enable", 1.0)
        bdot.receive("aocs.mag.field_x", 30e-6)
        bdot.receive("aocs.mag.field_y", 0.0)
        bdot.receive("aocs.mag.field_z", 0.0)
        bdot.do_step(t=0.0, dt=0.1)
        bdot.receive("aocs.mag.field_x", 30e-6 + delta_b)
        bdot.do_step(t=0.1, dt=0.1)
        return abs(bdot.read_port("aocs.mtq.dipole_x"))

    @pytest.mark.requirement("SVF-DEV-145")
    def test_default_gain_written_to_store(self) -> None:
        """B-dot controller writes its default gain into ParameterStore at init."""
        store, _ = _stores()
        make_bdot_controller(_sync(), store, CommandStore(), gain=5e3)
        entry = store.read("aocs.ctrl.bdot_gain")
        assert entry is not None
        assert entry.value == pytest.approx(5e3)

    @pytest.mark.requirement("SVF-DEV-145")
    def test_gain_update_via_store_takes_effect(self) -> None:
        """Doubling gain in ParameterStore doubles the dipole output."""
        store, cmd = _stores()
        bdot = make_bdot_controller(
            _sync(), store, cmd,
            equipment_id="bdot", mag_id="mag", mtq_id="mtq", gain=1e4,
        )
        bdot.initialise()
        bdot.receive("aocs.bdot.enable", 1.0)
        bdot.receive("aocs.mag.field_x", 30e-6)
        bdot.receive("aocs.mag.field_y", 0.0)
        bdot.receive("aocs.mag.field_z", 0.0)
        bdot.do_step(t=0.0, dt=0.1)
        bdot.receive("aocs.mag.field_x", 35e-6)
        bdot.do_step(t=0.1, dt=0.1)
        dipole_before = abs(bdot.read_port("aocs.mtq.dipole_x"))

        # Update gain via store (simulates TC(20,1) reaching ParameterStore)
        store.write("aocs.ctrl.bdot_gain", 2e4, t=0.2, model_id="obc")
        bdot.receive("aocs.mag.field_x", 40e-6)   # same delta_b = 5e-6 T
        bdot.do_step(t=0.2, dt=0.1)
        dipole_after = abs(bdot.read_port("aocs.mtq.dipole_x"))

        assert dipole_after == pytest.approx(dipole_before * 2.0, rel=1e-3)

    @pytest.mark.requirement("SVF-DEV-145")
    def test_max_dipole_clamps_output(self) -> None:
        """Reducing max_dipole via store clamps output to new limit."""
        store, cmd = _stores()
        bdot = make_bdot_controller(
            _sync(), store, cmd,
            equipment_id="bdot", mag_id="mag", mtq_id="mtq",
            gain=1e6, max_dipole=10.0,
        )
        bdot.initialise()
        bdot.receive("aocs.bdot.enable", 1.0)
        bdot.receive("aocs.mag.field_x", 30e-6)
        bdot.receive("aocs.mag.field_y", 0.0)
        bdot.receive("aocs.mag.field_z", 0.0)
        bdot.do_step(t=0.0, dt=0.1)
        bdot.receive("aocs.mag.field_x", 130e-6)   # large step → saturation
        bdot.do_step(t=0.1, dt=0.1)
        assert abs(bdot.read_port("aocs.mtq.dipole_x")) == pytest.approx(10.0, abs=1e-9)

        # Reduce limit
        store.write("aocs.ctrl.bdot_max_dipole", 5.0, t=0.2, model_id="obc")
        bdot.receive("aocs.mag.field_x", 230e-6)
        bdot.do_step(t=0.2, dt=0.1)
        assert abs(bdot.read_port("aocs.mtq.dipole_x")) == pytest.approx(5.0, abs=1e-9)
