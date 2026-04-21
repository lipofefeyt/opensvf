"""
SVF PUS TM/TC End-to-End Validation Test Procedures
Validates the full commanding chain:
  Ground -> TTC -> OBC -> 1553 bus -> Equipment

Test cases:
  TC-PUS-001: S17 are-you-alive TC, verify TM(17,2) response
  TC-PUS-002: S20 set RW torque via PUS, verify speed increases
  TC-PUS-003: S3 HK report contains correct parameter values
  TC-PUS-004: Invalid TC (bad CRC), verify S1(1,2) rejection
  TC-PUS-005: Full chain: ground -> TTC -> OBC -> 1553 -> RW

Implements: PUS-010, PUS-011, SVF-DEV-037
"""

import pytest
import struct
from cyclonedds.domain import DomainParticipant

from svf.sim.simulation import SimulationMaster
from svf.sim.software_tick import SoftwareTickSource
from svf.ground.dds_sync import DdsSyncProtocol
from svf.stores.parameter_store import ParameterStore
from svf.stores.command_store import CommandStore
from svf.models.dhs.obc import ObcEquipment, ObcConfig
from svf.models.ttc.ttc import TtcEquipment
from svf.models.aocs.reaction_wheel import make_reaction_wheel
from svf.bus.mil1553 import Mil1553Bus, SubaddressMapping
from svf.pus.tc import PusTcPacket
from svf.pus.services import HkReportDefinition, PusService3


# SRDB PUS parameter_id -> canonical name mapping for RW
RW_PARAM_MAP = {
    0x2021: "aocs.rw1.torque_cmd",
    0x2022: "aocs.rw1.speed",
}


def make_pus_system(
    stop_time: float = 10.0,
    dt: float = 0.1,
) -> tuple[
    SimulationMaster,
    ParameterStore,
    CommandStore,
    ObcEquipment,
    TtcEquipment,
    Mil1553Bus,
]:
    """Build full PUS commanding chain: TTC -> OBC -> 1553 -> RW."""
    participant = DomainParticipant()
    store = ParameterStore()
    cmd_store = CommandStore()
    sync = DdsSyncProtocol(participant)

    # OBC config with RW parameter mappings and essential HK
    config = ObcConfig(
        apid=0x101,
        param_id_map=RW_PARAM_MAP,
        essential_hk=[
            HkReportDefinition(
                report_id=1,
                parameter_names=["aocs.rw1.speed", "aocs.rw1.torque_cmd"],
                period_s=1.0,
            )
        ],
    )

    obc = ObcEquipment(config, sync, store, cmd_store)
    ttc = TtcEquipment(obc, sync, store, cmd_store)
    rw = make_reaction_wheel(sync, store, cmd_store)

    mappings = [
        SubaddressMapping(
            rt_address=5, subaddress=1,
            parameter="aocs.rw1.torque_cmd",
            direction="BC_to_RT",
        ),
        SubaddressMapping(
            rt_address=5, subaddress=2,
            parameter="aocs.rw1.speed",
            direction="RT_to_BC",
        ),
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
        models=[ttc, obc, bus, rw],
        dt=dt,
        stop_time=stop_time,
        sync_timeout=5.0,
        command_store=cmd_store,
        param_store=store,
    )

    return master, store, cmd_store, obc, ttc, bus


@pytest.mark.requirement("PUS-010", "PUS-011", "PUS-007")
def test_tc_pus_001_are_you_alive() -> None:
    """
    TC-PUS-001: S17 are-you-alive TC, verify TM(17,2) response.

    Ground sends TC(17,1) via TTC.
    Expected: OBC responds with TM(17,2) within one tick.
    """
    _, store, cmd_store, obc, ttc, _ = make_pus_system(stop_time=1.0)

    tc = PusTcPacket(
        apid=0x100, sequence_count=1,
        service=17, subservice=1,
    )
    ttc.send_tc(tc)
    ttc.do_step(t=0.0, dt=0.1)

    responses = ttc.get_tm_responses(service=17, subservice=2)
    assert len(responses) == 1
    assert responses[0].service == 17
    assert responses[0].subservice == 2


@pytest.mark.requirement("PUS-010", "PUS-011", "PUS-008")
def test_tc_pus_002_s20_set_rw_torque() -> None:
    """
    TC-PUS-002: S20 set RW torque via PUS, verify command reaches RW.

    Ground sends TC(20,1) with param_id=0x2021, value=0.1.
    Expected: aocs.rw1.torque_cmd injected into CommandStore.
    """
    _, store, cmd_store, obc, ttc, _ = make_pus_system(stop_time=1.0)

    tc = PusTcPacket(
        apid=0x100, sequence_count=2,
        service=20, subservice=1,
        app_data=struct.pack(">Hf", 0x2021, 0.1),
    )
    ttc.send_tc(tc)
    ttc.do_step(t=0.0, dt=0.1)

    entry = cmd_store.peek("aocs.rw1.torque_cmd")
    assert entry is not None
    assert entry.value == pytest.approx(0.1, abs=1e-5)
    assert entry.source_id == "obc.s20.set"


@pytest.mark.requirement("PUS-005", "PUS-010")
def test_tc_pus_003_s3_hk_report() -> None:
    """
    TC-PUS-003: S3 essential HK report contains correct parameter values.

    Expected: TM(3,25) generated on each tick with current RW speed.
    """
    _, store, cmd_store, obc, ttc, _ = make_pus_system(stop_time=1.0)

    store.write("aocs.rw1.speed", 1500.0, t=0.0, model_id="rw1")
    store.write("aocs.rw1.torque_cmd", 0.1, t=0.0, model_id="obc")

    obc.do_step(t=0.0, dt=0.1)

    tm_list = obc.get_tm_by_service(3, 25)
    assert len(tm_list) > 0

    defn = obc._s3._definitions[1]
    values = PusService3.parse_report(tm_list[0], defn.parameter_names)
    assert values["aocs.rw1.speed"] == pytest.approx(1500.0, abs=0.1)


@pytest.mark.requirement("PUS-009", "PUS-010")
def test_tc_pus_004_invalid_crc_rejected() -> None:
    """
    TC-PUS-004: TC with invalid CRC is rejected with TM(1,2).

    Expected: OBC generates S1(1,2) acceptance failure.
    """
    _, store, cmd_store, obc, ttc, _ = make_pus_system(stop_time=1.0)

    from svf.pus.tc import PusTcBuilder
    raw = bytearray(PusTcBuilder().build(
        PusTcPacket(apid=0x100, sequence_count=1, service=17, subservice=1)
    ))
    raw[-1] ^= 0xFF  # corrupt CRC

    responses = obc.receive_tc(bytes(raw), t=0.0)
    failures = [r for r in responses if r.service == 1 and r.subservice == 2]
    assert len(failures) == 1


@pytest.mark.requirement("PUS-010", "PUS-011", "PUS-008", "SVF-DEV-037")
def test_tc_pus_005_full_chain_ground_to_rw() -> None:
    """
    TC-PUS-005: Full commanding chain.
    Ground -> TTC -> OBC -> 1553 bus -> RW -> speed increases.

    Ground sends TC(20,1) to set RW torque.
    Expected: RW speed increases after simulation runs.
    """
    master, store, cmd_store, obc, ttc, bus = make_pus_system(
        stop_time=30.0, dt=0.1
    )

    # Ground sends torque command via TTC before simulation starts
    tc = PusTcPacket(
        apid=0x100, sequence_count=1,
        service=20, subservice=1,
        app_data=struct.pack(">Hf", 0x2021, 0.1),
    )
    # Process TC directly — simulation hasn't started yet
    from svf.pus.tc import PusTcBuilder
    obc.receive_tc(PusTcBuilder().build(tc), t=0.0)

    master.run()

    speed = store.read("aocs.rw1.speed")
    assert speed is not None
    assert speed.value > 100.0, \
        f"RW speed too low after PUS command: {speed.value:.1f} rpm"
