"""
Real-Time Detumbling Campaign Tests

Runs b-dot detumbling at wall-clock speed using RealtimeTickSource.
Designed to be observable in YAMCS: start YAMCS, run this test,
watch angular rate decrease in TM display in real time.

Requires: obsw_sim + SpacecraftDynamics.fmu
"""
from __future__ import annotations

import math
from pathlib import Path

import pytest
from cyclonedds.domain import DomainParticipant

from svf.sim.simulation import SimulationMaster
from svf.sim.software_tick import RealtimeTickSource
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
        Path("models/fmu/SpacecraftDynamics.fmu"),
    ] if p.exists()),
    _root / "models/fmu/SpacecraftDynamics.fmu"
)

pytestmark = pytest.mark.skipif(
    not OBSW_SIM.exists() or not KDE_FMU.exists(),
    reason="obsw_sim or SpacecraftDynamics.fmu not found"
)


def make_realtime_system(
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
        tick_source=RealtimeTickSource(),
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

    for name in [
        "aocs.mag.power_enable",
        "aocs.gyro.power_enable",
        "aocs.str1.power_enable",
        "aocs.mtq.power_enable",
    ]:
        cmd_store.inject(name, 1.0, source_id="test")
    cmd_store.inject("aocs.str1.sun_angle", 90.0, source_id="test")

    return master, store, cmd_store


@pytest.mark.timeout(60)
@pytest.mark.requirement("SVF-DEV-010", "KDE-001")
def test_realtime_bdot_observable_in_yamcs() -> None:
    """
    TC-RT-001: B-dot detumbling runs at wall-clock speed.

    30s simulation takes ~30s wall clock. Angular rate observable
    in YAMCS TM display in real time as it decreases.

    To observe in YAMCS:
      1. yamcs-start
      2. Open http://localhost:8090
      3. Run this test
      4. Watch /aocs/truth/rate_x/y/z parameters decrease
    """
    import time
    master, store, cmd_store = make_realtime_system(stop_time=30.0, dt=0.1)

    t_start = time.monotonic()
    master.run()
    elapsed = time.monotonic() - t_start

    # Wall clock should be ~30s (allow 20% tolerance for slow CI)
    assert 25.0 <= elapsed <= 40.0, (
        f"Realtime simulation took {elapsed:.1f}s — expected ~30s"
    )

    # Angular rate should have decreased (b-dot active)
    rate_x = store.read("aocs.truth.rate_x")
    rate_y = store.read("aocs.truth.rate_y")
    rate_z = store.read("aocs.truth.rate_z")
    assert rate_x is not None and rate_y is not None and rate_z is not None
    final_rate = math.sqrt(
        rate_x.value**2 + rate_y.value**2 + rate_z.value**2
    )
    assert final_rate < 1.0, (
        f"Angular rate {final_rate:.3f} rad/s — b-dot not effective"
    )


@pytest.mark.timeout(15)
@pytest.mark.requirement("SVF-DEV-010")
def test_realtime_tick_overrun_warning() -> None:
    """
    TC-RT-002: RealtimeTickSource logs overrun warning when tick is slow.

    Validates that the overrun detection mechanism works — a tick
    that takes longer than dt triggers a warning log.
    """
    import time
    from svf.sim.software_tick import RealtimeTickSource

    overruns: list[str] = []
    import logging

    class OverrunCapture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            if "overrun" in record.getMessage().lower():
                overruns.append(record.getMessage())

    handler = OverrunCapture()
    logging.getLogger("svf.software_tick").addHandler(handler)

    tick_count = 0

    def slow_tick(t: float) -> None:
        nonlocal tick_count
        tick_count += 1
        if tick_count == 3:
            time.sleep(0.15)  # deliberate overrun on tick 3

    source = RealtimeTickSource(warn_overrun=True)
    source.start(slow_tick, dt=0.1, stop_time=0.5)

    logging.getLogger("svf.software_tick").removeHandler(handler)
    assert len(overruns) >= 1, "Expected at least one overrun warning"
