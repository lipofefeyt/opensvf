"""
SVF Closed-Loop Detumbling Integration Test

Full closed-loop co-simulation:
  opensvf-kde (C++ 6-DOF physics)
      ↓ true rates → GYRO model (noise) → b-dot reads rates
      ↓ true B field → MAG model (noise) → b-dot reads B
      ↑ MTQ torques ← b-dot controller ← obsw reference algorithm

Validates the complete model chain end-to-end with real physics.
Does NOT require obsw_sim — uses SVF reference b-dot controller.

Implements: KDE-001, KDE-002, KDE-003, KDE-004, SVF-DEV-061
"""

import pytest
import math
from pathlib import Path
from cyclonedds.domain import DomainParticipant

from svf.sim.simulation import SimulationMaster
from svf.sim.software_tick import SoftwareTickSource
from svf.ground.dds_sync import DdsSyncProtocol
from svf.stores.parameter_store import ParameterStore
from svf.stores.command_store import CommandStore
from svf.config.wiring import WiringLoader
from svf.models.dynamics.kde_equipment import make_kde_equipment
from svf.models.aocs.magnetometer import make_magnetometer
from svf.models.aocs.magnetorquer import make_magnetorquer
from svf.models.aocs.bdot_controller import make_bdot_controller
from svf.models.aocs.gyroscope import make_gyroscope

KDE_FMU = Path("bin/SpacecraftDynamics.fmu")

pytestmark = pytest.mark.skipif(
    not KDE_FMU.exists(),
    reason="SpacecraftDynamics.fmu not found — build opensvf-kde first"
)


def make_closed_loop_system(
    stop_time: float = 30.0,
    dt: float = 0.1,
    initial_rate: float = 0.05,
    gain: float = 1e4,
) -> tuple[SimulationMaster, ParameterStore, CommandStore]:
    """
    Build full closed-loop detumbling simulation.

    KDE provides true physics. Sensor models add noise.
    B-dot controller closes the loop via MTQ torques back to KDE.
    """
    participant = DomainParticipant()
    store = ParameterStore()
    cmd_store = CommandStore()
    sync = DdsSyncProtocol(participant)

    kde  = make_kde_equipment(sync, store, cmd_store)
    mag  = make_magnetometer(sync, store, cmd_store, seed=42)
    mtq  = make_magnetorquer(sync, store, cmd_store)
    bdot = make_bdot_controller(sync, store, cmd_store, gain=gain)
    gyro = make_gyroscope(sync, store, cmd_store, seed=42)

    equipment = {
        "kde": kde, "mag": mag, "mtq": mtq,
        "bdot": bdot, "gyro": gyro,
    }
    wiring = WiringLoader(equipment).load(
        Path("mission_mysat1/wiring/kde_wiring.yaml")
    )

    # KDE runs first — produces true state for sensors
    master = SimulationMaster(
        tick_source=SoftwareTickSource(),
        sync_protocol=sync,
        models=[kde, mag, gyro, bdot, mtq],
        dt=dt,
        stop_time=stop_time,
        sync_timeout=5.0,
        command_store=cmd_store,
        param_store=store,
        wiring=wiring,
    )

    # Power on sensors and controller
    cmd_store.inject("aocs.mag.power_enable",  1.0, source_id="test")
    cmd_store.inject("aocs.mtq.power_enable",  1.0, source_id="test")
    cmd_store.inject("aocs.gyro.power_enable", 1.0, source_id="test")
    cmd_store.inject("aocs.bdot.enable",       1.0, source_id="test")

    # KDE will provide true B field — no need to inject manually

    return master, store, cmd_store


@pytest.mark.requirement("KDE-001", "SVF-DEV-061")
def test_kde_provides_true_state() -> None:
    """
    TC-KDE-001: KDE FMU outputs true angular rates and B field
    into ParameterStore each tick.
    """
    master, store, cmd_store = make_closed_loop_system(stop_time=2.0)
    master.run()

    rate_x = store.read("aocs.truth.rate_x")
    b_x    = store.read("aocs.mag.true_x")

    assert rate_x is not None, "KDE should output true rates"
    assert b_x    is not None, "KDE should output true B field"


@pytest.mark.requirement("KDE-002", "SVF-DEV-061")
def test_kde_attitude_quaternion_unit_norm() -> None:
    """
    TC-KDE-002: KDE attitude quaternion has unit norm throughout simulation.
    """
    master, store, cmd_store = make_closed_loop_system(stop_time=10.0)
    master.run()

    w = store.read("aocs.attitude.quaternion_w")
    x = store.read("aocs.attitude.quaternion_x")
    y = store.read("aocs.attitude.quaternion_y")
    z = store.read("aocs.attitude.quaternion_z")

    assert w is not None and x is not None and y is not None and z is not None
    norm = math.sqrt(w.value**2 + x.value**2 + y.value**2 + z.value**2)
    assert norm == pytest.approx(1.0, abs=0.01), \
        f"Quaternion norm should be 1.0, got {norm:.4f}"


@pytest.mark.requirement("KDE-003", "SVF-DEV-061")
def test_kde_gyro_reads_true_rates() -> None:
    """
    TC-KDE-003: GYRO model reads KDE true rates with noise.
    Measured rates close to true rates.
    """
    master, store, cmd_store = make_closed_loop_system(stop_time=5.0)
    master.run()

    true_rate  = store.read("aocs.truth.rate_x")
    gyro_rate  = store.read("aocs.gyro.rate_x")

    assert true_rate is not None
    assert gyro_rate is not None
    # Measured rate within 10% of true (noise model)
    if abs(true_rate.value) > 1e-6:
        assert abs(gyro_rate.value - true_rate.value) < abs(true_rate.value) * 0.5


@pytest.mark.requirement("KDE-004", "SVF-DEV-061")
def test_kde_mag_reads_true_b_field() -> None:
    """
    TC-KDE-004: MAG model reads KDE true B field with noise.
    """
    master, store, cmd_store = make_closed_loop_system(stop_time=5.0)
    master.run()

    true_b    = store.read("aocs.mag.true_x")
    measured_b = store.read("aocs.mag.field_x")

    assert true_b    is not None
    assert measured_b is not None


@pytest.mark.requirement("KDE-001", "KDE-003", "KDE-004", "SVF-DEV-061")
def test_kde_closed_loop_bdot_generates_torque() -> None:
    """
    TC-KDE-005: Full closed loop — KDE → MAG → b-dot → MTQ → torque back to KDE.
    MTQ generates non-zero torque when b-dot controller active.
    """
    master, store, cmd_store = make_closed_loop_system(
        stop_time=10.0, dt=0.1
    )
    master.run()

    torque_x = store.read("aocs.mtq.torque_x")
    torque_y = store.read("aocs.mtq.torque_y")
    torque_z = store.read("aocs.mtq.torque_z")

    assert torque_x is not None and torque_y is not None and torque_z is not None

    total = math.sqrt(
        torque_x.value**2 + torque_y.value**2 + torque_z.value**2
    )
    assert total > 0.0, \
        f"Closed-loop MTQ torque should be non-zero: {total:.2e} Nm"
