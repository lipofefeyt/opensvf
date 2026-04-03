"""
SVF Platform Validation Test Procedures
Exercises all M8 equipment models together in realistic scenarios.

Scenario: spacecraft operations sequence
  TC-PLAT-001: OBC boots in SAFE mode, OBT increments
  TC-PLAT-002: Watchdog triggers warning when not kicked
  TC-PLAT-003: RW commanded via PUS TC, speed increases
  TC-PLAT-004: ST acquires attitude after power-on
  TC-PLAT-005: SBT acquires carrier lock on strong signal
  TC-PLAT-006: OBC mode transition SAFE -> NOMINAL via PUS TC

Implements: SVF-DEV-050, SVF-DEV-051
"""

import pytest
import struct
from cyclonedds.domain import DomainParticipant

from svf.simulation import SimulationMaster
from svf.software_tick import SoftwareTickSource
from svf.dds_sync import DdsSyncProtocol
from svf.parameter_store import ParameterStore
from svf.command_store import CommandStore
from svf.models.obc import ObcEquipment, ObcConfig, MODE_SAFE, MODE_NOMINAL
from svf.models.ttc import TtcEquipment
from svf.models.reaction_wheel import make_reaction_wheel
from svf.models.star_tracker import make_star_tracker, ACQUISITION_TIME_S
from svf.models.sbt import make_sbt, LOCK_THRESHOLD_DBM, LOCK_TIME_S, MODE_TC_RX
from svf.bus import BusFault, FaultType
from svf.mil1553 import Mil1553Bus, SubaddressMapping
from svf.pus.tc import PusTcPacket
from svf.pus.services import HkReportDefinition


RW_PARAM_MAP = {
    0x2021: "aocs.rw1.torque_cmd",
    0x2022: "aocs.rw1.speed",
    0x4002: "dhs.obc.mode_cmd",
}


def make_platform(
    stop_time: float = 30.0,
    dt: float = 0.1,
) -> tuple:
    """Build full platform: OBC + TTC + 1553 + RW + ST + SBT."""
    participant = DomainParticipant()
    store = ParameterStore()
    cmd_store = CommandStore()
    sync = DdsSyncProtocol(participant)

    config = ObcConfig(
        apid=0x101,
        param_id_map=RW_PARAM_MAP,
        watchdog_period_s=20.0,
        initial_mode=MODE_SAFE,
        essential_hk=[
            HkReportDefinition(
                report_id=1,
                parameter_names=["aocs.rw1.speed", "dhs.obc.obt"],
                period_s=1.0,
            )
        ],
    )

    obc = ObcEquipment(config, sync, store, cmd_store)
    ttc = TtcEquipment(obc, sync, store, cmd_store)
    rw  = make_reaction_wheel(sync, store, cmd_store)
    st  = make_star_tracker(sync, store, cmd_store, seed=42)
    sbt = make_sbt(sync, store, cmd_store)

    mappings = [
        SubaddressMapping(5, 1, "aocs.rw1.torque_cmd", "BC_to_RT"),
        SubaddressMapping(5, 2, "aocs.rw1.speed",      "RT_to_BC"),
    ]
    bus = Mil1553Bus(
        bus_id="platform_1553",
        rt_count=5,
        mappings=mappings,
        sync_protocol=sync,
        store=store,
        command_store=cmd_store,
    )

    master = SimulationMaster(
        tick_source=SoftwareTickSource(),
        sync_protocol=sync,
        models=[ttc, obc, bus, rw, st, sbt],
        dt=dt,
        stop_time=stop_time,
        sync_timeout=5.0,
        command_store=cmd_store,
        param_store=store,
    )

    return master, store, cmd_store, obc, ttc, rw, st, sbt, bus


@pytest.mark.requirement("OBC-001", "OBC-004")
def test_tc_plat_001_obc_boots_safe_obt_increments() -> None:
    """
    TC-PLAT-001: OBC boots in SAFE mode and OBT increments.
    Expected: mode=SAFE, OBT > 0 after simulation.
    """
    master, store, *_ = make_platform(stop_time=5.0)
    master.run()

    mode = store.read("dhs.obc.mode")
    obt  = store.read("dhs.obc.obt")
    assert mode is not None
    assert mode.value == pytest.approx(MODE_SAFE)
    assert obt is not None
    assert obt.value > 0.0


@pytest.mark.requirement("OBC-005")
def test_tc_plat_002_watchdog_warning_without_kick() -> None:
    """
    TC-PLAT-002: Watchdog warning generated when not kicked.
    Expected: TM(5,2) low severity event after watchdog period.
    """
    master, store, cmd_store, obc, *_ = make_platform(
        stop_time=45.0, dt=1.0
    )
    master.run()

    # Check watchdog status
    wdg = store.read("dhs.obc.watchdog_status")
    assert wdg is not None
    assert wdg.value >= 1.0  # WARNING or RESET


@pytest.mark.requirement("OBC-001", "PUS-010", "RW-001")
def test_tc_plat_003_rw_commanded_via_pus_tc() -> None:
    """
    TC-PLAT-003: RW torque commanded via PUS TC, speed increases.
    Ground sends TC(20,1) -> OBC routes -> 1553 -> RW.
    """
    master, store, cmd_store, obc, *_ = make_platform(stop_time=30.0)

    # Inject TC before simulation
    from svf.pus.tc import PusTcBuilder
    tc = PusTcPacket(
        apid=0x100, sequence_count=1,
        service=20, subservice=1,
        app_data=struct.pack(">Hf", 0x2021, 0.1),
    )
    obc.receive_tc(PusTcBuilder().build(tc), t=0.0)
    master.run()

    speed = store.read("aocs.rw1.speed")
    assert speed is not None
    assert speed.value > 100.0


@pytest.mark.requirement("ST-001", "ST-002")
def test_tc_plat_004_st_acquires_attitude() -> None:
    """
    TC-PLAT-004: Star tracker acquires valid attitude after power-on.
    Expected: validity=1 after ACQUISITION_TIME_S.
    """
    master, store, cmd_store, obc, ttc, rw, st, *_ = make_platform(
        stop_time=ACQUISITION_TIME_S + 5.0
    )

    # Power on ST before simulation
    cmd_store.inject("aocs.str1.power_enable", 1.0, source_id="test")
    cmd_store.inject("aocs.str1.sun_angle", 90.0, source_id="test")
    master.run()

    validity = store.read("aocs.str1.validity")
    assert validity is not None
    assert validity.value == pytest.approx(1.0)


@pytest.mark.requirement("SBT-001", "SBT-002")
def test_tc_plat_005_sbt_acquires_carrier_lock() -> None:
    """
    TC-PLAT-005: SBT acquires carrier lock on strong signal.
    Expected: uplink_lock=1 after LOCK_TIME_S.
    """
    master, store, cmd_store, obc, ttc, rw, st, sbt, bus = make_platform(
        stop_time=LOCK_TIME_S + 5.0
    )

    # Power on SBT with strong signal
    cmd_store.inject("ttc.sbt.power_enable", 1.0, source_id="test")
    cmd_store.inject(
        "ttc.sbt.uplink_signal_level",
        LOCK_THRESHOLD_DBM + 20.0,
        source_id="test"
    )
    cmd_store.inject("ttc.sbt.mode_cmd", float(MODE_TC_RX), source_id="test")
    master.run()

    lock = store.read("ttc.sbt.uplink_lock")
    assert lock is not None
    assert lock.value == pytest.approx(1.0)


@pytest.mark.requirement("OBC-001", "OBC-002", "OBC-003", "PUS-010")
def test_tc_plat_006_obc_mode_transition_via_pus() -> None:
    """
    TC-PLAT-006: OBC transitions SAFE -> NOMINAL via PUS TC(20,1).
    Expected: mode=NOMINAL after TC processed.
    """
    master, store, cmd_store, obc, *_ = make_platform(stop_time=5.0)

    from svf.pus.tc import PusTcBuilder
    tc = PusTcPacket(
        apid=0x100, sequence_count=1,
        service=20, subservice=1,
        app_data=struct.pack(">Hf", 0x4002, float(MODE_NOMINAL)),
    )
    obc.receive_tc(PusTcBuilder().build(tc), t=0.0)
    master.run()

    mode = store.read("dhs.obc.mode")
    assert mode is not None
    assert mode.value == pytest.approx(MODE_NOMINAL)

    # Verify S5 mode transition event was generated
    events = obc.get_tm_by_service(5, 1)
    assert len(events) > 0


# ── FDIR scenarios ────────────────────────────────────────────────────────────

@pytest.mark.requirement("1553-007", "1553-008", "OBC-001")
def test_tc_plat_007_rw_fault_visible_in_obc_hk() -> None:
    """
    TC-PLAT-007: 1553 NO_RESPONSE fault on RW — OBC HK shows zero speed.
    When RT5 has NO_RESPONSE, speed telemetry stops updating.
    OBC HK report should reflect last known value.
    """
    master, store, cmd_store, obc, ttc, rw, st, sbt, bus = make_platform(
        stop_time=10.0
    )
    bus.inject_fault(BusFault(
        fault_type=FaultType.NO_RESPONSE,
        target="rt5",
        duration_s=0.0,
        injected_at=0.0,
    ))
    store.write("aocs.rw1.torque_cmd", 0.1, t=0.0, model_id="obc")
    master.run()

    speed = store.read("aocs.rw1.speed")
    assert speed is not None
    assert abs(speed.value) < 10.0  # fault blocked all commands


@pytest.mark.requirement("ST-003", "OBC-001")
def test_tc_plat_008_st_blinding_during_platform_ops() -> None:
    """
    TC-PLAT-008: ST blinded during platform operations.
    Validity drops to 0 when sun enters exclusion zone.
    """
    master, store, cmd_store, obc, ttc, rw, st, sbt, bus = make_platform(
        stop_time=ACQUISITION_TIME_S + 5.0
    )
    cmd_store.inject("aocs.str1.power_enable", 1.0, source_id="test")
    cmd_store.inject("aocs.str1.sun_angle", 90.0, source_id="test")
    master.run()

    # Now blind the ST
    from svf.models.star_tracker import SUN_EXCLUSION_DEG
    st._port_values["aocs.str1.sun_angle"] = SUN_EXCLUSION_DEG - 1.0
    st.do_step(t=ACQUISITION_TIME_S + 5.0, dt=1.0)

    validity = st.read_port("aocs.str1.validity")
    assert validity == pytest.approx(0.0)


@pytest.mark.requirement("SBT-003", "OBC-001")
def test_tc_plat_009_sbt_link_loss_during_contact() -> None:
    """
    TC-PLAT-009: SBT loses carrier lock mid-contact pass.
    Lock drops when signal falls below threshold.
    """
    master, store, cmd_store, obc, ttc, rw, st, sbt, bus = make_platform(
        stop_time=LOCK_TIME_S + 5.0
    )
    cmd_store.inject("ttc.sbt.power_enable", 1.0, source_id="test")
    cmd_store.inject(
        "ttc.sbt.uplink_signal_level",
        LOCK_THRESHOLD_DBM + 20.0,
        source_id="test"
    )
    cmd_store.inject("ttc.sbt.mode_cmd", float(MODE_TC_RX), source_id="test")
    master.run()

    # Verify lock acquired
    lock = store.read("ttc.sbt.uplink_lock")
    assert lock is not None
    assert lock.value == pytest.approx(1.0)

    # Signal drops — lock lost
    sbt._port_values["ttc.sbt.uplink_signal_level"] = LOCK_THRESHOLD_DBM - 10.0
    sbt.do_step(t=LOCK_TIME_S + 5.0, dt=1.0)
    assert sbt.read_port("ttc.sbt.uplink_lock") == pytest.approx(0.0)


@pytest.mark.requirement("OBC-005", "OBC-001")
def test_tc_plat_010_obc_watchdog_recovery() -> None:
    """
    TC-PLAT-010: OBC watchdog triggers — mode returns to SAFE.
    Without watchdog kick, OBC resets after 2x watchdog period.
    """
    master, store, cmd_store, obc, ttc, rw, st, sbt, bus = make_platform(
        stop_time=45.0, dt=1.0
    )
    # Start in NOMINAL
    obc._mode = MODE_NOMINAL
    master.run()

    mode = store.read("dhs.obc.mode")
    assert mode is not None
    assert mode.value == pytest.approx(MODE_SAFE)  # reset to SAFE
    assert obc.reset_count >= 1
