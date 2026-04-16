"""
SVF Nominal Operations Scenario
Closed-loop system test: OBC stub maintains nominal operations
while ground exchanges PUS TC/TM via TTC.

Scenario:
  1. Spacecraft in NOMINAL mode, ST tracking, RW spinning
  2. OBC stub maintains RW speed within bounds
  3. OBC generates HK every second
  4. Ground sends S17 are-you-alive TC
  5. OBC responds with TM(17,2)
  6. Ground sends S20 parameter set to adjust RW torque
  7. OBC routes to RW via 1553 bus

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
from svf.models.dhs.obc import ObcConfig, MODE_NOMINAL
from svf.models.dhs.obc_stub import ObcStub, Rule
from svf.models.ttc.ttc import TtcEquipment
from svf.models.aocs.reaction_wheel import make_reaction_wheel
from svf.models.aocs.star_tracker import make_star_tracker, ACQUISITION_TIME_S
from svf.mil1553 import Mil1553Bus, SubaddressMapping
from svf.pus.services import HkReportDefinition, PusService3
from svf.pus.tc import PusTcPacket, PusTcBuilder


RW_PARAM_MAP = {
    0x2021: "aocs.rw1.torque_cmd",
    0x2022: "aocs.rw1.speed",
}


def make_nominal_system(
    stop_time: float = 30.0,
    dt: float = 0.1,
) -> tuple[SimulationMaster, ParameterStore, CommandStore, ObcStub, TtcEquipment]:
    participant = DomainParticipant()
    store = ParameterStore()
    cmd_store = CommandStore()
    sync = DdsSyncProtocol(participant)

    rules = [
        # Maintain RW at low speed when ST valid
        Rule(
            name="maintain_rw",
            watch="aocs.str1.validity",
            condition=lambda e: e is not None and e.value > 0.5,
            action=lambda cs, t: cs.inject(
                "aocs.rw1.torque_cmd", 0.02,
                t=t, source_id="stub.maintain_rw"
            ),
        ),
    ]

    config = ObcConfig(
        apid=0x101,
        param_id_map=RW_PARAM_MAP,
        watchdog_period_s=99999.0,
        initial_mode=MODE_NOMINAL,
        essential_hk=[
            HkReportDefinition(
                report_id=1,
                parameter_names=["aocs.rw1.speed", "aocs.str1.validity"],
                period_s=1.0,
            )
        ],
    )

    obc = ObcStub(config, sync, store, cmd_store, rules=rules)
    ttc = TtcEquipment(obc, sync, store, cmd_store)
    rw  = make_reaction_wheel(sync, store, cmd_store)
    st  = make_star_tracker(sync, store, cmd_store, seed=42)

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
        models=[ttc, obc, bus, rw, st],
        dt=dt,
        stop_time=stop_time,
        sync_timeout=5.0,
        command_store=cmd_store,
        param_store=store,
    )

    return master, store, cmd_store, obc, ttc


@pytest.mark.requirement("SVF-DEV-050", "SVF-DEV-051", "PUS-007", "PUS-010")
def test_nominal_ops_are_you_alive_roundtrip() -> None:
    """
    TC-NOM-001: Ground sends S17 are-you-alive, OBC responds TM(17,2).
    """
    master, store, cmd_store, obc, ttc = make_nominal_system(stop_time=5.0)

    cmd_store.inject("aocs.str1.power_enable", 1.0, source_id="test")
    cmd_store.inject("aocs.str1.sun_angle", 90.0, source_id="test")

    tc = PusTcPacket(apid=0x100, sequence_count=1, service=17, subservice=1)
    obc.receive_tc(PusTcBuilder().build(tc), t=0.0)
    master.run()

    responses = ttc.get_tm_responses(service=17, subservice=2)
    assert len(responses) >= 1
    assert responses[0].service == 17
    assert responses[0].subservice == 2


@pytest.mark.requirement("SVF-DEV-050", "SVF-DEV-051", "PUS-008", "PUS-010")
def test_nominal_ops_s20_adjusts_rw_torque() -> None:
    """
    TC-NOM-002: Ground sends S20 to set RW torque, RW speed changes.
    Full chain: TC(20,1) → OBC → 1553 → RW.
    """
    master, store, cmd_store, obc, ttc = make_nominal_system(stop_time=30.0)

    # Send TC(20,1) to set torque
    tc = PusTcPacket(
        apid=0x100, sequence_count=2,
        service=20, subservice=1,
        app_data=struct.pack(">Hf", 0x2021, 0.1),
    )
    obc.receive_tc(PusTcBuilder().build(tc), t=0.0)
    master.run()

    speed = store.read("aocs.rw1.speed")
    assert speed is not None
    assert speed.value > 50.0, \
        f"RW should spin after S20 torque command: {speed.value:.1f} rpm"


@pytest.mark.requirement("SVF-DEV-050", "SVF-DEV-051", "PUS-005", "OBC-001")
def test_nominal_ops_hk_generated_periodically() -> None:
    """
    TC-NOM-003: OBC generates TM(3,25) HK reports periodically.
    Essential HK auto-enabled at boot.
    """
    master, store, cmd_store, obc, ttc = make_nominal_system(stop_time=5.0)
    master.run()

    hk = obc.get_tm_by_service(3, 25)
    assert len(hk) > 0, "OBC should generate HK reports"


@pytest.mark.requirement("SVF-DEV-050", "SVF-DEV-051", "SVF-DEV-038")
def test_nominal_ops_stub_maintains_rw_when_st_valid() -> None:
    """
    TC-NOM-004: Stub maintain_rw rule fires when ST becomes valid.
    ST acquires → stub enables RW torque → RW spins.
    """
    master, store, cmd_store, obc, ttc = make_nominal_system(
        stop_time=ACQUISITION_TIME_S + 15.0
    )
    cmd_store.inject("aocs.str1.power_enable", 1.0, source_id="test")
    cmd_store.inject("aocs.str1.sun_angle", 90.0, source_id="test")
    master.run()

    assert obc.rule_fired_count("maintain_rw") > 0
    speed = store.read("aocs.rw1.speed")
    assert speed is not None
    assert speed.value > 0.0
