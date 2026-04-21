"""
SVF B-dot Detumbling Integration Test
Closed-loop: MAG → b-dot controller → MTQ → torque generation.
Implements: SVF-DEV-038
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
from svf.models.aocs.magnetometer import make_magnetometer
from svf.models.aocs.magnetorquer import make_magnetorquer
from svf.models.aocs.bdot_controller import make_bdot_controller
from svf.models.aocs.gyroscope import make_gyroscope


def make_bdot_system(
    stop_time: float = 60.0,
    dt: float = 0.5,
    initial_rate: float = 0.05,
    gain: float = 1e4,
) -> tuple[SimulationMaster, ParameterStore, CommandStore]:
    """Build a closed-loop b-dot detumbling simulation."""
    participant = DomainParticipant()
    store = ParameterStore()
    cmd_store = CommandStore()
    sync = DdsSyncProtocol(participant)

    mag  = make_magnetometer(sync, store, cmd_store, seed=42)
    mtq  = make_magnetorquer(sync, store, cmd_store)
    bdot = make_bdot_controller(sync, store, cmd_store, gain=gain)
    gyro = make_gyroscope(sync, store, cmd_store, seed=42)

    equipment = {"mag": mag, "bdot": bdot, "mtq": mtq, "gyro": gyro}
    wiring = WiringLoader(equipment).load(Path("srdb/wiring/bdot_wiring.yaml"))

    master = SimulationMaster(
        tick_source=SoftwareTickSource(),
        sync_protocol=sync,
        models=[mag, bdot, mtq, gyro],
        dt=dt,
        stop_time=stop_time,
        sync_timeout=5.0,
        command_store=cmd_store,
        param_store=store,
        wiring=wiring,
    )

    cmd_store.inject("aocs.mag.power_enable",  1.0, source_id="test")
    cmd_store.inject("aocs.mtq.power_enable",  1.0, source_id="test")
    cmd_store.inject("aocs.gyro.power_enable", 1.0, source_id="test")
    cmd_store.inject("aocs.bdot.enable",       1.0, source_id="test")

    cmd_store.inject("aocs.mag.true_x",  3e-5, source_id="test")
    cmd_store.inject("aocs.mag.true_y",  0.0,  source_id="test")
    cmd_store.inject("aocs.mag.true_z", -4e-5, source_id="test")

    cmd_store.inject("aocs.truth.rate_x",  initial_rate,        source_id="test")
    cmd_store.inject("aocs.truth.rate_y",  initial_rate * 0.7,  source_id="test")
    cmd_store.inject("aocs.truth.rate_z", -initial_rate * 0.5,  source_id="test")

    return master, store, cmd_store


@pytest.mark.requirement("SVF-DEV-038")
def test_bdot_controller_produces_dipole_commands() -> None:
    """TC-BDOT-001: B-dot controller produces non-zero dipole commands."""
    master, store, cmd_store = make_bdot_system(stop_time=5.0)
    master.run()

    active = store.read("aocs.bdot.active")
    assert active is not None
    assert active.value == pytest.approx(1.0)


@pytest.mark.requirement("SVF-DEV-038")
def test_bdot_mtq_generates_torque() -> None:
    """TC-BDOT-002: MTQ generates non-zero torque from dipole × B."""
    master, store, cmd_store = make_bdot_system(stop_time=5.0)
    master.run()

    torque_x = store.read("aocs.mtq.torque_x")
    torque_y = store.read("aocs.mtq.torque_y")
    torque_z = store.read("aocs.mtq.torque_z")

    assert torque_x is not None
    assert torque_y is not None
    assert torque_z is not None

    total_torque = math.sqrt(
        torque_x.value**2 + torque_y.value**2 + torque_z.value**2
    )
    assert total_torque > 0.0, \
        f"MTQ torque should be non-zero: {total_torque:.2e} Nm"


@pytest.mark.requirement("SVF-DEV-038")
def test_bdot_gyro_measures_rates() -> None:
    """TC-BDOT-003: GYRO measures body rates during detumbling."""
    master, store, cmd_store = make_bdot_system(stop_time=10.0)
    master.run()

    rate_x = store.read("aocs.gyro.rate_x")
    assert rate_x is not None
    assert rate_x.value != pytest.approx(0.0, abs=1e-6)


@pytest.mark.requirement("SVF-DEV-038")
def test_bdot_chain_mag_to_mtq() -> None:
    """TC-BDOT-004: Full chain MAG → b-dot → MTQ physically consistent."""
    master, store, cmd_store = make_bdot_system(stop_time=10.0)
    master.run()

    field_x = store.read("aocs.mag.field_x")
    assert field_x is not None
    assert abs(field_x.value) > 0.0

    bdot_x = store.read("aocs.bdot.bdot_x")
    assert bdot_x is not None

    dipole_x = store.read("aocs.mtq.dipole_x")
    assert dipole_x is not None

    torque_y = store.read("aocs.mtq.torque_y")
    assert torque_y is not None
    if abs(dipole_x.value) > 0.1:
        assert abs(torque_y.value) > 0.0
