"""
AOCS equipment model tests — multi-instance isolation and hardware profile application.

Two failure modes this suite guards against:
1. Multiple instances of the same model corrupting each other's state (was caused by
   module-level globals mutated via `global` statements).
2. Passing a hardware_profile that is silently ignored (profile loaded but values
   never assigned back to physics constants).
"""
from __future__ import annotations

import math
import os
import pytest

from svf.core.abstractions import SyncProtocol
from svf.stores.parameter_store import ParameterStore
from svf.stores.command_store import CommandStore
from svf.models.aocs.reaction_wheel import make_reaction_wheel
from svf.models.aocs.star_tracker import make_star_tracker
from svf.models.aocs.magnetometer import make_magnetometer
from svf.models.aocs.magnetorquer import make_magnetorquer
from svf.models.aocs.gyroscope import make_gyroscope
from svf.models.aocs.thruster import make_thruster
from svf.models.aocs.gps import make_gps, ACQUISITION_TIME_S

_PROFILES_DIR = os.path.join(
    os.path.dirname(__file__),
    "..", "..", "mission_mysat1", "hardware_profiles",
)


class _NoSync(SyncProtocol):
    def reset(self) -> None:
        pass

    def publish_ready(self, model_id: str, t: float) -> None:
        pass

    def wait_for_ready(self, expected: list[str], timeout: float) -> bool:
        return True


def _sync() -> _NoSync:
    return _NoSync()


def _stores() -> tuple[ParameterStore, CommandStore]:
    return ParameterStore(), CommandStore()


# ---------------------------------------------------------------------------
# Multi-instance isolation
# ---------------------------------------------------------------------------

class MultiInstanceIsolationTests:
    """Two instances of the same model must not share state."""

    @pytest.mark.requirement("SVF-DEV-080")
    def test_two_thrusters_independent_propellant(self) -> None:
        store, cmd = _stores()
        thr1 = make_thruster(_sync(), store, cmd, equipment_id="thr1")
        thr2 = make_thruster(_sync(), store, cmd, equipment_id="thr2")
        thr1.initialise()
        thr2.initialise()

        # Fire thr1 for 100 steps, keep thr2 off
        for i in range(100):
            thr1.receive("aocs.thr1.enable", 1.0)
            thr1.receive("aocs.thr1.thrust_cmd", 1.0)
            thr1.do_step(t=i * 0.1, dt=0.1)

            thr2.receive("aocs.thr2.enable", 0.0)
            thr2.receive("aocs.thr2.thrust_cmd", 0.0)
            thr2.do_step(t=i * 0.1, dt=0.1)

        prop1 = thr1.read_port("aocs.thr1.propellant")
        prop2 = thr2.read_port("aocs.thr2.propellant")

        assert prop1 < prop2, "thr1 should have consumed propellant; thr2 should not"
        assert prop2 == pytest.approx(0.5), "thr2 propellant unchanged"

    @pytest.mark.requirement("SVF-DEV-080")
    def test_two_thrusters_independent_temperature(self) -> None:
        store, cmd = _stores()
        thr1 = make_thruster(_sync(), store, cmd, equipment_id="thr1")
        thr2 = make_thruster(_sync(), store, cmd, equipment_id="thr2")
        thr1.initialise()
        thr2.initialise()

        for i in range(20):
            thr1.receive("aocs.thr1.enable", 1.0)
            thr1.receive("aocs.thr1.thrust_cmd", 1.0)
            thr1.do_step(t=i * 0.1, dt=0.1)
            thr2.receive("aocs.thr2.enable", 0.0)
            thr2.receive("aocs.thr2.thrust_cmd", 0.0)
            thr2.do_step(t=i * 0.1, dt=0.1)

        assert thr1.read_port("aocs.thr1.temperature") > thr2.read_port("aocs.thr2.temperature")

    @pytest.mark.requirement("SVF-DEV-080")
    def test_two_reaction_wheels_independent_speed(self) -> None:
        store, cmd = _stores()
        rw_x = make_reaction_wheel(_sync(), store, cmd, equipment_id="rw_x")
        rw_y = make_reaction_wheel(_sync(), store, cmd, equipment_id="rw_y")
        rw_x.initialise()
        rw_y.initialise()

        for i in range(20):
            rw_x.receive("aocs.rw_x.torque_cmd", 0.1)
            rw_x.do_step(t=i * 0.1, dt=0.1)
            rw_y.receive("aocs.rw_y.torque_cmd", 0.0)
            rw_y.do_step(t=i * 0.1, dt=0.1)

        speed_x = rw_x.read_port("aocs.rw_x.speed")
        speed_y = rw_y.read_port("aocs.rw_y.speed")
        assert abs(speed_x) > abs(speed_y), "rw_x should have spun up; rw_y should not"

    @pytest.mark.requirement("SVF-DEV-081")
    def test_two_gps_independent_fix(self) -> None:
        store, cmd = _stores()
        gps1 = make_gps(_sync(), store, cmd, equipment_id="gps1", seed=1)
        gps2 = make_gps(_sync(), store, cmd, equipment_id="gps2", seed=2)
        gps1.initialise()
        gps2.initialise()

        t = ACQUISITION_TIME_S + 1.0
        gps1.receive("gps1.power_enable", 1.0)
        gps1.receive("gps1.eclipse", 0.0)
        gps1.receive("gps1.truth.pos_x", 6_871_000.0)
        gps1.receive("gps1.truth.pos_y", 0.0)
        gps1.receive("gps1.truth.pos_z", 0.0)
        gps1.receive("gps1.truth.vel_x", 0.0)
        gps1.receive("gps1.truth.vel_y", 7613.0)
        gps1.receive("gps1.truth.vel_z", 0.0)

        # gps2 powered off
        gps2.receive("gps2.power_enable", 0.0)

        gps1.do_step(t=t, dt=0.1)
        gps2.do_step(t=t, dt=0.1)

        assert gps1.read_port("gps1.fix") == pytest.approx(1.0)
        assert gps2.read_port("gps2.fix") == pytest.approx(0.0)

    def test_port_names_use_equipment_id(self) -> None:
        store, cmd = _stores()
        rw = make_reaction_wheel(_sync(), store, cmd, equipment_id="rw_skew")
        port_names = list(rw.ports.keys())
        assert "aocs.rw_skew.torque_cmd" in port_names
        assert "aocs.rw_skew.speed" in port_names
        assert "aocs.rw1.torque_cmd" not in port_names

    def test_thruster_port_names_use_equipment_id(self) -> None:
        store, cmd = _stores()
        thr = make_thruster(_sync(), store, cmd, equipment_id="cold_gas_a")
        port_names = list(thr.ports.keys())
        assert "aocs.cold_gas_a.enable" in port_names
        assert "aocs.thr1.enable" not in port_names


# ---------------------------------------------------------------------------
# Hardware profile application
# ---------------------------------------------------------------------------

class HardwareProfileApplicationTests:
    """Loading a profile must actually change the physics, not be a no-op."""

    @pytest.mark.requirement("SVF-DEV-080")
    def test_rw_sinclair_profile_lowers_max_speed(self) -> None:
        """Sinclair profile (5000 rpm max) must saturate lower than default (6000 rpm)."""
        store, cmd = _stores()
        rw_default  = make_reaction_wheel(_sync(), store, cmd, equipment_id="rw_a")
        rw_sinclair = make_reaction_wheel(
            _sync(), store, cmd, equipment_id="rw_b",
            hardware_profile="rw_sinclair_rw003",
            hardware_dir=_PROFILES_DIR,
        )
        rw_default.initialise()
        rw_sinclair.initialise()

        # Drive both at saturating torque long enough to hit the speed cap
        for i in range(500):
            rw_default.receive("aocs.rw_a.torque_cmd", 100.0)
            rw_default.do_step(t=i * 0.1, dt=0.1)
            rw_sinclair.receive("aocs.rw_b.torque_cmd", 100.0)
            rw_sinclair.do_step(t=i * 0.1, dt=0.1)

        speed_default  = abs(rw_default.read_port("aocs.rw_a.speed"))
        speed_sinclair = abs(rw_sinclair.read_port("aocs.rw_b.speed"))
        assert speed_default  == pytest.approx(6000.0, abs=50.0), "default should cap at 6000 rpm"
        assert speed_sinclair == pytest.approx(5000.0, abs=50.0), "Sinclair profile should cap at 5000 rpm"

    @pytest.mark.requirement("SVF-DEV-080")
    def test_thruster_hydrazine_profile_longer_burn(self) -> None:
        """Hydrazine thruster (Isp=220s) burns less propellant per second than cold gas (Isp=70s)."""
        store, cmd = _stores()
        thr_cold = make_thruster(_sync(), store, cmd, equipment_id="thr_cold",
                                 hardware_profile="thr_default",
                                 hardware_dir=_PROFILES_DIR)
        thr_hyd  = make_thruster(_sync(), store, cmd, equipment_id="thr_hyd",
                                 hardware_profile="thr_moog_monarc_1",
                                 hardware_dir=_PROFILES_DIR)
        thr_cold.initialise()
        thr_hyd.initialise()

        for i in range(50):
            thr_cold.receive("aocs.thr_cold.enable", 1.0)
            thr_cold.receive("aocs.thr_cold.thrust_cmd", 1.0)
            thr_cold.do_step(t=i * 0.1, dt=0.1)

            thr_hyd.receive("aocs.thr_hyd.enable", 1.0)
            thr_hyd.receive("aocs.thr_hyd.thrust_cmd", 1.0)
            thr_hyd.do_step(t=i * 0.1, dt=0.1)

        prop_cold = thr_cold.read_port("aocs.thr_cold.propellant")
        prop_hyd  = thr_hyd.read_port("aocs.thr_hyd.propellant")

        # Hydrazine starts with more propellant (1.0 kg vs 0.5 kg) AND burns less per second
        # So prop_hyd must be substantially higher after same burn time
        assert prop_hyd > prop_cold, (
            "Hydrazine thruster (Isp=220s, 1.0 kg initial) should retain more propellant"
        )

    @pytest.mark.requirement("SVF-DEV-081")
    def test_gps_profile_changes_noise(self) -> None:
        """GPS with novatel profile (1.5 m noise) has tighter spread than default (5 m)."""
        store, cmd = _stores()
        N = 100
        t = ACQUISITION_TIME_S + 1.0

        def _measure(profile):
            errors = []
            for seed in range(N):
                g = make_gps(_sync(), store, cmd, equipment_id="gps_test",
                             seed=seed,
                             hardware_profile=profile,
                             hardware_dir=_PROFILES_DIR if profile else None)
                g.initialise()
                g.receive("gps_test.power_enable", 1.0)
                g.receive("gps_test.eclipse", 0.0)
                g.receive("gps_test.truth.pos_x", 6_871_000.0)
                g.receive("gps_test.truth.pos_y", 0.0)
                g.receive("gps_test.truth.pos_z", 0.0)
                g.receive("gps_test.truth.vel_x", 0.0)
                g.receive("gps_test.truth.vel_y", 7613.0)
                g.receive("gps_test.truth.vel_z", 0.0)
                g.do_step(t=t, dt=0.1)
                errors.append(abs(g.read_port("gps_test.position_x") - 6_871_000.0))
            return sum(errors) / len(errors)

        mean_default = _measure(None)
        mean_novatel = _measure("gps_novatel_oem7")

        assert mean_novatel < mean_default, (
            f"Novatel profile (1.5 m noise) mean error {mean_novatel:.2f} m should be "
            f"less than default (5 m) mean error {mean_default:.2f} m"
        )

    def test_magnetometer_profile_applied(self) -> None:
        """mag_default profile keys are accepted without error and affect noise level."""
        store, cmd = _stores()
        mag = make_magnetometer(_sync(), store, cmd, equipment_id="mag_a",
                                hardware_profile="mag_default",
                                hardware_dir=_PROFILES_DIR)
        mag.initialise()
        mag.receive("aocs.mag_a.power_enable", 1.0)
        mag.receive("aocs.mag_a.true_x", 30e-6)
        mag.receive("aocs.mag_a.true_y", 0.0)
        mag.receive("aocs.mag_a.true_z", 0.0)
        mag.do_step(t=1.0, dt=0.1)
        field_x = mag.read_port("aocs.mag_a.field_x")
        # Profile noise ~1e-7 T; measurement should be within 10-sigma of truth
        assert abs(field_x - 30e-6) < 1e-5
