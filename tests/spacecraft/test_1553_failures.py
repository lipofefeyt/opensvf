"""
SVF MIL-STD-1553 Bus Failure Test Procedures
Exercises 1553 fault injection and FDIR scenarios.

TC-1553-FAIL-001: NO_RESPONSE permanent — RT silent for duration
TC-1553-FAIL-002: NO_RESPONSE timed — RT recovers after fault clears
TC-1553-FAIL-003: BUS_ERROR — automatic switchover to bus B
TC-1553-FAIL-004: Broadcast during fault — unaffected RTs still receive
TC-1553-FAIL-005: Multiple simultaneous RT faults
TC-1553-FAIL-006: Fault injection via svf_command_schedule

Implements: 1553-007, 1553-008, 1553-009
"""

import pytest
from cyclonedds.domain import DomainParticipant

from svf.simulation import SimulationMaster
from svf.software_tick import SoftwareTickSource
from svf.dds_sync import DdsSyncProtocol
from svf.parameter_store import ParameterStore
from svf.command_store import CommandStore
from svf.mil1553 import Mil1553Bus, SubaddressMapping, BROADCAST_RT
from svf.bus import BusFault, FaultType
from svf.models.aocs.reaction_wheel import make_reaction_wheel


def make_1553_system(
    stop_time: float = 10.0,
    dt: float = 0.1,
    rt_count: int = 5,
    extra_mappings: list[SubaddressMapping] | None = None,
) -> tuple[SimulationMaster, ParameterStore, CommandStore, Mil1553Bus]:
    """Build 1553 bus + RW simulation."""
    participant = DomainParticipant()
    store = ParameterStore()
    cmd_store = CommandStore()
    sync = DdsSyncProtocol(participant)

    mappings = [
        SubaddressMapping(5, 1, "aocs.rw1.torque_cmd", "BC_to_RT"),
        SubaddressMapping(5, 2, "aocs.rw1.speed",      "RT_to_BC"),
    ]
    if extra_mappings:
        mappings.extend(extra_mappings)

    bus = Mil1553Bus(
        bus_id="platform_1553",
        rt_count=rt_count,
        mappings=mappings,
        sync_protocol=sync,
        store=store,
        command_store=cmd_store,
    )
    rw = make_reaction_wheel(sync, store, cmd_store)

    master = SimulationMaster(
        tick_source=SoftwareTickSource(),
        sync_protocol=sync,
        models=[bus, rw],
        dt=dt,
        stop_time=stop_time,
        sync_timeout=5.0,
        command_store=cmd_store,
        param_store=store,
    )
    return master, store, cmd_store, bus


@pytest.mark.requirement("1553-007", "1553-008")
def test_tc_1553_fail_001_no_response_permanent_blocks_rt() -> None:
    """
    TC-1553-FAIL-001: Permanent NO_RESPONSE fault — RT stays silent.
    Torque command written but never reaches RW.
    """
    master, store, cmd_store, bus = make_1553_system(stop_time=10.0)

    bus.inject_fault(BusFault(FaultType.NO_RESPONSE, "rt5", 0.0, 0.0))
    store.write("aocs.rw1.torque_cmd", 0.1, t=0.0, model_id="obc")
    master.run()

    speed = store.read("aocs.rw1.speed")
    assert speed is not None
    assert abs(speed.value) < 10.0


@pytest.mark.requirement("1553-007", "1553-008")
def test_tc_1553_fail_002_no_response_timed_rt_recovers() -> None:
    """
    TC-1553-FAIL-002: Timed NO_RESPONSE fault — RT recovers after expiry.
    Speed should increase after fault clears.
    """
    master, store, cmd_store, bus = make_1553_system(stop_time=20.0)

    bus.inject_fault(BusFault(FaultType.NO_RESPONSE, "rt5", 5.0, 0.0))
    store.write("aocs.rw1.torque_cmd", 0.1, t=0.0, model_id="obc")
    master.run()

    speed = store.read("aocs.rw1.speed")
    assert speed is not None
    assert speed.value > 50.0


@pytest.mark.requirement("1553-006", "1553-007")
def test_tc_1553_fail_003_bus_error_triggers_switchover() -> None:
    """
    TC-1553-FAIL-003: BUS_ERROR triggers automatic switchover to bus B.
    """
    master, store, cmd_store, bus = make_1553_system(stop_time=5.0)

    assert bus.active_bus == "A"
    bus.inject_fault(BusFault(FaultType.BUS_ERROR, "all", 0.0, 0.0))
    master.run()

    assert bus.active_bus == "B"
    active = store.read("bus.platform_1553.active_bus")
    assert active is not None
    assert active.value == pytest.approx(2.0)


@pytest.mark.requirement("1553-005", "1553-007")
def test_tc_1553_fail_004_broadcast_unaffected_by_single_rt_fault() -> None:
    """
    TC-1553-FAIL-004: Broadcast command reaches all RTs even when
    one specific RT has NO_RESPONSE fault.
    Broadcast uses RT31 — fault on rt5 should not block it.
    """
    broadcast_mapping = SubaddressMapping(
        rt_address=BROADCAST_RT, subaddress=3,
        parameter="aocs.all.mode_cmd",
        direction="BC_to_RT",
    )
    master, store, cmd_store, bus = make_1553_system(
        stop_time=5.0,
        extra_mappings=[broadcast_mapping],
    )

    # Fault only on rt5 — broadcast should still work
    bus.inject_fault(BusFault(FaultType.NO_RESPONSE, "rt5", 0.0, 0.0))
    store.write("aocs.all.mode_cmd", 2.0, t=0.0, model_id="obc")
    master.run()

    entry = cmd_store.peek("aocs.all.mode_cmd")
    assert entry is not None
    assert entry.value == pytest.approx(2.0)


@pytest.mark.requirement("1553-007", "1553-008")
def test_tc_1553_fail_005_multiple_simultaneous_faults() -> None:
    """
    TC-1553-FAIL-005: Multiple simultaneous RT faults all block correctly.
    """
    master, store, cmd_store, bus = make_1553_system(
        stop_time=5.0, rt_count=5
    )

    # Fault all RTs simultaneously
    bus.inject_fault(BusFault(FaultType.NO_RESPONSE, "all", 0.0, 0.0))
    store.write("aocs.rw1.torque_cmd", 0.1, t=0.0, model_id="obc")
    master.run()

    speed = store.read("aocs.rw1.speed")
    assert speed is not None
    assert abs(speed.value) < 10.0


@pytest.mark.requirement("1553-009")
def test_tc_1553_fail_006_fault_injected_via_command_store() -> None:
    """
    TC-1553-FAIL-006: Fault injection via CommandStore naming convention.
    bus.{id}.fault.{target}.{type} = duration
    """
    master, store, cmd_store, bus = make_1553_system(stop_time=10.0)

    # Inject fault via CommandStore
    cmd_store.inject(
        "bus.platform_1553.fault.rt5.no_response",
        value=0.0,  # permanent
        source_id="test",
    )
    store.write("aocs.rw1.torque_cmd", 0.1, t=0.0, model_id="obc")
    master.run()

    speed = store.read("aocs.rw1.speed")
    assert speed is not None
    assert abs(speed.value) < 10.0


@pytest.mark.requirement("1553-008")
def test_tc_1553_fail_007_fault_expires_and_rt_resumes() -> None:
    """
    TC-1553-FAIL-007: After timed fault expires RT resumes normally.
    Speed near zero during fault, increases after.
    """
    master, store, cmd_store, bus = make_1553_system(stop_time=20.0)

    bus.inject_fault(BusFault(FaultType.NO_RESPONSE, "rt5", 3.0, 0.0))
    store.write("aocs.rw1.torque_cmd", 0.1, t=0.0, model_id="obc")
    master.run()

    speed = store.read("aocs.rw1.speed")
    assert speed is not None
    assert speed.value > 100.0
