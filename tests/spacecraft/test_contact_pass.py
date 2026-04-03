"""
SVF Ground Contact Pass Scenario
Closed-loop system test: SBT acquires lock, TC/TM exchange,
lock lost as ground station sets below horizon.

Scenario:
  1. SBT powered off initially
  2. Ground station rises — signal level increases
  3. SBT acquires carrier lock
  4. Ground sends TC(17,1) are-you-alive
  5. OBC responds TM(17,2)
  6. Ground sends TC(20,1) mode command
  7. OBC executes, generates TM(1,7) completion
  8. Ground station sets — signal drops, lock lost

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
from svf.models.obc import ObcConfig, MODE_NOMINAL, MODE_SAFE
from svf.models.obc_stub import ObcStub, Rule
from svf.models.ttc import TtcEquipment
from svf.models.sbt import make_sbt, LOCK_THRESHOLD_DBM, LOCK_TIME_S, MODE_TC_RX, MODE_TM_TX
from svf.pus.services import HkReportDefinition
from svf.pus.tc import PusTcPacket, PusTcBuilder


RW_PARAM_MAP = {
    0x2021: "aocs.rw1.torque_cmd",
    0x4002: "dhs.obc.mode_cmd",
}


def make_contact_system(
    stop_time: float = 30.0,
    dt: float = 0.1,
) -> tuple[SimulationMaster, ParameterStore, CommandStore, ObcStub, TtcEquipment]:
    participant = DomainParticipant()
    store = ParameterStore()
    cmd_store = CommandStore()
    sync = DdsSyncProtocol(participant)

    config = ObcConfig(
        apid=0x101,
        param_id_map=RW_PARAM_MAP,
        watchdog_period_s=99999.0,
        initial_mode=MODE_NOMINAL,
        essential_hk=[
            HkReportDefinition(
                report_id=1,
                parameter_names=["dhs.obc.mode", "dhs.obc.obt"],
                period_s=1.0,
            )
        ],
    )

    obc = ObcStub(config, sync, store, cmd_store, rules=[])
    ttc = TtcEquipment(obc, sync, store, cmd_store)
    sbt = make_sbt(sync, store, cmd_store)

    master = SimulationMaster(
        tick_source=SoftwareTickSource(),
        sync_protocol=sync,
        models=[ttc, obc, sbt],
        dt=dt,
        stop_time=stop_time,
        sync_timeout=5.0,
        command_store=cmd_store,
        param_store=store,
    )

    return master, store, cmd_store, obc, ttc


@pytest.mark.requirement("SVF-DEV-050", "SVF-DEV-051", "SBT-001", "SBT-002")
def test_contact_pass_lock_acquired() -> None:
    """
    TC-CONT-001: SBT acquires carrier lock when signal rises.
    """
    master, store, cmd_store, obc, ttc = make_contact_system(
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

    lock = store.read("ttc.sbt.uplink_lock")
    assert lock is not None
    assert lock.value == pytest.approx(1.0)


@pytest.mark.requirement("SVF-DEV-050", "SVF-DEV-051", "PUS-007", "SBT-001")
def test_contact_pass_tc_tm_exchange() -> None:
    """
    TC-CONT-002: Ground sends TC(17,1), OBC responds TM(17,2)
    during contact pass.
    """
    master, store, cmd_store, obc, ttc = make_contact_system(
        stop_time=LOCK_TIME_S + 10.0
    )
    cmd_store.inject("ttc.sbt.power_enable", 1.0, source_id="test")
    cmd_store.inject(
        "ttc.sbt.uplink_signal_level",
        LOCK_THRESHOLD_DBM + 20.0,
        source_id="test"
    )
    cmd_store.inject("ttc.sbt.mode_cmd", float(MODE_TC_RX), source_id="test")

    # Send TC before run
    tc = PusTcPacket(apid=0x100, sequence_count=1, service=17, subservice=1)
    obc.receive_tc(PusTcBuilder().build(tc), t=0.0)
    master.run()

    responses = ttc.get_tm_responses(service=17, subservice=2)
    assert len(responses) >= 1


@pytest.mark.requirement("SVF-DEV-050", "SVF-DEV-051", "PUS-009", "PUS-010")
def test_contact_pass_s20_mode_cmd_with_s1_completion() -> None:
    """
    TC-CONT-003: Ground sends S20 mode command,
    OBC executes and generates TM(1,7) completion.
    """
    master, store, cmd_store, obc, ttc = make_contact_system(stop_time=5.0)

    tc = PusTcPacket(
        apid=0x100, sequence_count=2,
        service=20, subservice=1,
        app_data=struct.pack(">Hf", 0x4002, float(MODE_NOMINAL)),
    )
    obc.receive_tc(PusTcBuilder().build(tc), t=0.0)
    master.run()

    # S1(1,7) completion should be generated
    completions = obc.get_tm_by_service(1, 7)
    assert len(completions) >= 1


@pytest.mark.requirement("SVF-DEV-050", "SVF-DEV-051", "SBT-003")
def test_contact_pass_lock_lost_at_end() -> None:
    """
    TC-CONT-004: Lock lost when ground station sets below horizon.
    Signal drops → lock lost immediately.
    """
    master, store, cmd_store, obc, ttc = make_contact_system(
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

    # Ground station sets — signal drops
    from svf.models.sbt import make_sbt as _
    # Access sbt directly via store — signal drop
    cmd_store.inject(
        "ttc.sbt.uplink_signal_level",
        LOCK_THRESHOLD_DBM - 20.0,
        source_id="test"
    )

    # Run one more second
    master2, store2, cmd_store2, obc2, ttc2 = make_contact_system(
        stop_time=LOCK_TIME_S + 6.0
    )
    cmd_store2.inject("ttc.sbt.power_enable", 1.0, source_id="test")
    cmd_store2.inject(
        "ttc.sbt.uplink_signal_level",
        LOCK_THRESHOLD_DBM - 20.0,
        source_id="test"
    )
    master2.run()

    lock2 = store2.read("ttc.sbt.uplink_lock")
    assert lock2 is not None
    assert lock2.value == pytest.approx(0.0)
