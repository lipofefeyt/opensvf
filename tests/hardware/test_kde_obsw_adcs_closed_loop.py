"""
SVF ADCS Closed-Loop Hardware Tests

Tests the full attitude control loop:
  KDE (C++ physics) → sensors → obsw_sim → actuator frames → SVF

SAFE mode:   b-dot → MTQ dipoles → torque = m×B → KDE (full loop)
NOMINAL mode: ADCS PD → RW torques injected (KDE RW port TBD in M14)

Requires: obsw_sim binary + SpacecraftDynamics.fmu

Implements: SVF-DEV-038, KDE-001, KDE-003, KDE-004
"""
from __future__ import annotations

import time
import math
from pathlib import Path

import pytest
from cyclonedds.domain import DomainParticipant

from svf.sim.simulation import SimulationMaster
from svf.sim.software_tick import SoftwareTickSource
from svf.ground.dds_sync import DdsSyncProtocol
from svf.stores.parameter_store import ParameterStore
from svf.stores.command_store import CommandStore
from svf.config.wiring import WiringLoader
from svf.models.dhs.obc_emulator import OBCEmulatorAdapter
from svf.models.ttc.ttc import TtcEquipment
from svf.models.dynamics.kde_equipment import make_kde_equipment
from svf.models.aocs.magnetometer import make_magnetometer
from svf.models.aocs.magnetorquer import make_magnetorquer
from svf.models.aocs.gyroscope import make_gyroscope
from svf.models.aocs.star_tracker import make_star_tracker

_root = Path(__file__).parent.parent.parent
# Prefer aarch64 binary if OBSW_ARCH=aarch64, else use native
import os as _os
_arch = _os.environ.get("OBSW_ARCH", "x86_64")
if _arch == "aarch64":
    OBSW_SIM = next(
        (p for p in [_root / "obsw_sim_aarch64", Path("obsw_sim_aarch64")] if p.exists()),
        _root / "obsw_sim_aarch64"
    )
else:
    OBSW_SIM = next(
        (p for p in [_root / "obsw_sim", Path("obsw_sim")] if p.exists()),
        _root / "obsw_sim"
    )
KDE_FMU = next(
    (p for p in [
        _root / "models/fmu/SpacecraftDynamics.fmu",
        Path("models/fmu/SpacecraftDynamics.fmu")
    ] if p.exists()),
    _root / "models/fmu/SpacecraftDynamics.fmu"
)

pytestmark = pytest.mark.skipif(
    not OBSW_SIM.exists() or not KDE_FMU.exists(),
    reason="obsw_sim or SpacecraftDynamics.fmu not found"
)


def make_adcs_system(
    stop_time: float = 30.0,
    dt: float = 0.1,
    seed: int = 42,
) -> tuple[SimulationMaster, ParameterStore, CommandStore]:
    participant = DomainParticipant()
    store = ParameterStore()
    cmd_store = CommandStore()
    sync = DdsSyncProtocol(participant)

    kde = make_kde_equipment(sync, store, cmd_store)
    mag = make_magnetometer(sync, store, cmd_store, seed=seed)
    gyro = make_gyroscope(sync, store, cmd_store, seed=seed)
    st = make_star_tracker(sync, store, cmd_store, seed=seed)
    mtq = make_magnetorquer(sync, store, cmd_store)

    obc = OBCEmulatorAdapter(
        sim_path=OBSW_SIM,
        sync_protocol=sync,
        store=store,
        command_store=cmd_store,
        sync_timeout=3.0,
    )
    ttc = TtcEquipment(obc, sync, store, cmd_store)

    equipment = {"kde": kde, "mag": mag, "gyro": gyro, "mtq": mtq, "obc": obc}
    wiring = WiringLoader(equipment).load(
        _root / "srdb/wiring/full_loop_wiring.yaml"
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
        seed=seed,
    )

    # Power on sensors
    for name in [
        "aocs.mag.power_enable",
        "aocs.gyro.power_enable",
        "aocs.str1.power_enable",
        "aocs.mtq.power_enable",
    ]:
        cmd_store.inject(name, 1.0, source_id="test")
    cmd_store.inject("aocs.str1.sun_angle", 90.0, source_id="test")

    return master, store, cmd_store


@pytest.mark.timeout(120)
@pytest.mark.requirement("KDE-001", "KDE-003", "KDE-004")
def test_safe_mode_bdot_reduces_angular_rate() -> None:
    """
    TC-ADCS-001: In SAFE mode, b-dot detumbling reduces angular rate.

    obsw_sim starts in SAFE mode. MAG measurements flow through
    to b-dot controller. MTQ dipoles → torque = m×B → KDE.
    Angular rate magnitude should decrease over 30 seconds.
    """
    master, store, cmd_store = make_adcs_system(stop_time=30.0, dt=0.1)
    master.run()

    rate_x = store.read("aocs.truth.rate_x")
    rate_y = store.read("aocs.truth.rate_y")
    rate_z = store.read("aocs.truth.rate_z")

    assert rate_x is not None
    assert rate_y is not None
    assert rate_z is not None

    final_rate = math.sqrt(
        rate_x.value**2 + rate_y.value**2 + rate_z.value**2
    )
    # KDE starts with non-zero tumble — b-dot should have reduced it
    assert final_rate < 1.0, (
        f"Angular rate {final_rate:.3f} rad/s — b-dot not effective"
    )


@pytest.mark.timeout(60)
@pytest.mark.requirement("KDE-001", "SVF-DEV-038")
def test_bdot_dipoles_reach_mtq() -> None:
    """
    TC-ADCS-002: MTQ dipole commands from obsw_sim reach CommandStore.

    Validates that type-0x03 actuator frames are parsed and injected
    into CommandStore, making dipoles available to MTQ model.
    """
    master, store, cmd_store = make_adcs_system(stop_time=5.0, dt=0.1)
    master.run()

    # After 5s, dipole commands should have been injected
    dipole_x = cmd_store.peek("aocs.mtq.dipole_x")
    assert dipole_x is not None, "MTQ dipole_x never injected by OBCEmulatorAdapter"


@pytest.mark.timeout(120)
@pytest.mark.requirement("KDE-001", "KDE-003")
def test_nominal_mode_adcs_controller_activates() -> None:
    """
    TC-ADCS-003: After SAFE→NOMINAL transition, ADCS PD controller activates.

    Send TC(8,1) recover_nominal at t=5s. After transition, obsw_sim
    should switch from b-dot to ADCS PD (controller=1 in actuator frame).
    Validated via RW torque commands appearing in CommandStore.
    """
    master, store, cmd_store = make_adcs_system(stop_time=20.0, dt=0.1)

    # Schedule NOMINAL recovery at t=5s via mode_cmd
    # OBCEmulatorAdapter will send TC(8,1) to obsw_sim
    import threading
    def inject_nominal() -> None:
        time.sleep(6.0)  # wall clock — simulation runs fast
        cmd_store.inject("dhs.obc.mode_cmd", 1.0, source_id="test")

    t = threading.Thread(target=inject_nominal, daemon=True)
    t.start()
    master.run()
    t.join(timeout=1.0)

    # RW torque commands should appear after NOMINAL transition
    rw_torque = cmd_store.peek("aocs.rw1.torque_cmd")
    assert rw_torque is not None, (
        "RW torque_cmd never injected — ADCS controller did not activate"
    )


@pytest.mark.timeout(60)
@pytest.mark.requirement("KDE-001", "SVF-DEV-038")
def test_sensor_frames_drive_obsw_each_tick() -> None:
    """
    TC-ADCS-004: obsw_sim receives sensor frames and advances OBT each tick.

    Validates that the full sensor injection pipeline works:
    KDE → MAG/GYRO → type-0x02 frame → obsw_sim → OBT increments.
    """
    master, store, cmd_store = make_adcs_system(stop_time=5.0, dt=0.1)
    master.run()

    obt = store.read("dhs.obc.obt")
    assert obt is not None
    assert obt.value > 4.0, f"OBT only {obt.value:.1f}s — obsw_sim not cycling"
