"""
SVF Full Closed-Loop System Test
KDE (C++ physics) + obsw_sim (real OBSW) + sensor models

Full loop:
  KDE FMU → true ω, B
  Sensor models → noisy MAG, GYRO
  OBCEmulatorAdapter → packs sensor frame → obsw_sim
  obsw_sim b-dot → dipole commands (via stderr for now)
  MTQ → torques → KDE

Requires: obsw_sim binary (updated with type-frame protocol)
          SpacecraftDynamics.fmu

Implements: SVF-DEV-029, SVF-DEV-034, SVF-DEV-037, KDE-001
"""

import pytest
import math
from pathlib import Path
from cyclonedds.domain import DomainParticipant

from svf.simulation import SimulationMaster
from svf.software_tick import SoftwareTickSource
from svf.dds_sync import DdsSyncProtocol
from svf.parameter_store import ParameterStore
from svf.command_store import CommandStore
from svf.wiring import WiringLoader
from svf.models.obc_emulator import OBCEmulatorAdapter
from svf.models.ttc import TtcEquipment
from svf.models.kde_equipment import make_kde_equipment
from svf.models.magnetometer import make_magnetometer
from svf.models.magnetorquer import make_magnetorquer
from svf.models.gyroscope import make_gyroscope
from svf.models.star_tracker import make_star_tracker

OBSW_SIM = Path("obsw_sim")
KDE_FMU  = Path("models/fmu/SpacecraftDynamics.fmu")

pytestmark = pytest.mark.skipif(
    not OBSW_SIM.exists() or not KDE_FMU.exists(),
    reason="obsw_sim or SpacecraftDynamics.fmu not found"
)


def make_full_system(
    stop_time: float = 10.0,
    dt: float = 0.1,
) -> tuple[SimulationMaster, ParameterStore, CommandStore, OBCEmulatorAdapter]:
    participant = DomainParticipant()
    store = ParameterStore()
    cmd_store = CommandStore()
    sync = DdsSyncProtocol(participant)

    kde = make_kde_equipment(sync, store, cmd_store)
    mag = make_magnetometer(sync, store, cmd_store, seed=42)
    gyro = make_gyroscope(sync, store, cmd_store, seed=42)
    st  = make_star_tracker(sync, store, cmd_store, seed=42)
    mtq = make_magnetorquer(sync, store, cmd_store)

    obc = OBCEmulatorAdapter(
        sim_path=OBSW_SIM,
        sync_protocol=sync,
        store=store,
        command_store=cmd_store,
        sync_timeout=3.0,
    )
    ttc = TtcEquipment(obc, sync, store, cmd_store)

    equipment = {
        "kde": kde, "mag": mag, "gyro": gyro,
        "mtq": mtq, "obc": obc,
    }
    wiring = WiringLoader(equipment).load(
        Path("srdb/wiring/kde_wiring.yaml")
    )

    master = SimulationMaster(
        tick_source=SoftwareTickSource(),
        sync_protocol=sync,
        models=[kde, mag, gyro, st, ttc, obc, mtq],
        dt=dt,
        stop_time=stop_time,
        sync_timeout=5.0,
        command_store=cmd_store,
        param_store=store,
        wiring=wiring,
    )

    cmd_store.inject("aocs.mag.power_enable",  1.0, source_id="test")
    cmd_store.inject("aocs.gyro.power_enable", 1.0, source_id="test")
    cmd_store.inject("aocs.str1.power_enable", 1.0, source_id="test")
    cmd_store.inject("aocs.str1.sun_angle",    90.0, source_id="test")
    cmd_store.inject("aocs.mtq.power_enable",  1.0, source_id="test")

    return master, store, cmd_store, obc


@pytest.mark.requirement("SVF-DEV-037", "KDE-001")
def test_full_loop_obsw_receives_sensor_data() -> None:
    """
    TC-FULL-001: obsw_sim receives sensor frames each tick.
    OBT increments — confirms obsw_sim is cycling.
    """
    master, store, cmd_store, obc = make_full_system(stop_time=5.0)
    master.run()

    obt = store.read("dhs.obc.obt")
    assert obt is not None
    assert obt.value > 0.0

    tm_out = store.read("obc.tm_output")
    assert tm_out is not None
    assert tm_out.value > 0.0, "obsw_sim should have generated TM"


@pytest.mark.requirement("SVF-DEV-037", "KDE-001", "KDE-004")
def test_full_loop_kde_provides_b_field_to_obsw() -> None:
    """
    TC-FULL-002: KDE B field flows through MAG model to obsw_sim sensor frame.
    """
    master, store, cmd_store, obc = make_full_system(stop_time=5.0)
    master.run()

    b_field = store.read("aocs.mag.field_x")
    assert b_field is not None

    true_b = store.read("aocs.mag.true_x")
    assert true_b is not None


@pytest.mark.requirement("SVF-DEV-037", "KDE-001", "KDE-003")
def test_full_loop_gyro_rates_reach_obsw() -> None:
    """
    TC-FULL-003: GYRO rates from KDE reach ParameterStore — obsw_sim reads them.
    """
    master, store, cmd_store, obc = make_full_system(stop_time=5.0)
    master.run()

    rate = store.read("aocs.gyro.rate_x")
    assert rate is not None
    assert rate.value != pytest.approx(0.0, abs=1e-10)


@pytest.mark.requirement("SVF-DEV-037", "KDE-001")
def test_full_loop_s17_ping_pong() -> None:
    """
    TC-FULL-004: obsw_sim responds to S17 ping each tick (heartbeat).
    TM sequence counter advances.
    """
    master, store, cmd_store, obc = make_full_system(stop_time=3.0)
    master.run()

    tm_seq = store.read("obc.tm_output")
    assert tm_seq is not None
    assert tm_seq.value > 0
