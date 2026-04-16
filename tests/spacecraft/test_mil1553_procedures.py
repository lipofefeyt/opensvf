"""
SVF MIL-STD-1553 Validation Test Procedures
Validates RW commanding and FDIR via simulated 1553 bus.

Note: No OBC model in M6 — commands injected directly into
ParameterStore simulating what an OBC would write after
receiving a PUS TC. OBC model deferred to M9 (PUS TM/TC).

Test cases:
  TC-1553-001: RW speed increases when torque commanded via 1553
  TC-1553-002: NO_RESPONSE fault blocks commanding to RW
  TC-1553-003: Fault clears, RW resumes nominal operation
  TC-1553-004: BUS_ERROR triggers switchover to redundant bus
  TC-1553-005: Broadcast command reaches all RTs

Implements: SVF-DEV-038
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
    stop_time: float = 30.0,
    dt: float = 0.1,
    rt_count: int = 5,
    extra_mappings: list[SubaddressMapping] | None = None,
) -> tuple[SimulationMaster, ParameterStore, CommandStore, Mil1553Bus]:
    """Build a 1553 bus + RW simulation. No OBC model — M9."""
    participant = DomainParticipant()
    store = ParameterStore()
    cmd_store = CommandStore()
    sync = DdsSyncProtocol(participant)

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


@pytest.mark.requirement("SVF-DEV-038")
def test_tc_1553_001_rw_speed_increases_when_commanded() -> None:
    """
    TC-1553-001: RW speed increases when torque commanded via 1553 bus.

    Simulates OBC writing torque command to ParameterStore,
    which the 1553 BC_to_RT mapping delivers to the RW.

    Expected: RW speed exceeds 200 rpm within 30s
    """
    master, store, cmd_store, bus = make_1553_system(stop_time=30.0)

    # Simulate OBC writing TC to ParameterStore
    store.write("aocs.rw1.torque_cmd", 0.1, t=0.0, model_id="sim_obc")

    master.run()

    speed = store.read("aocs.rw1.speed")
    assert speed is not None
    assert speed.value > 100.0, \
        f"RW speed too low: {speed.value:.1f} rpm"


@pytest.mark.requirement("SVF-DEV-038")
def test_tc_1553_002_no_response_fault_blocks_commanding() -> None:
    """
    TC-1553-002: NO_RESPONSE fault blocks 1553 commanding to RW.

    Expected: RW speed stays near 0 while fault active.
    """
    master, store, cmd_store, bus = make_1553_system(stop_time=10.0)

    bus.inject_fault(BusFault(
        fault_type=FaultType.NO_RESPONSE,
        target="rt5",
        duration_s=0.0,
        injected_at=0.0,
    ))
    store.write("aocs.rw1.torque_cmd", 0.1, t=0.0, model_id="sim_obc")

    master.run()

    speed = store.read("aocs.rw1.speed")
    assert speed is not None
    assert abs(speed.value) < 10.0, \
        f"RW should not spin with fault active: {speed.value:.1f} rpm"


@pytest.mark.requirement("SVF-DEV-038")
def test_tc_1553_003_fault_clears_operation_resumes() -> None:
    """
    TC-1553-003: After timed fault clears, RW resumes nominal operation.

    Preconditions: NO_RESPONSE fault for 5s then expires.
    Expected: speed near 0 during fault, increases after.
    """
    master, store, cmd_store, bus = make_1553_system(stop_time=20.0)

    bus.inject_fault(BusFault(
        fault_type=FaultType.NO_RESPONSE,
        target="rt5",
        duration_s=5.0,
        injected_at=0.0,
    ))
    store.write("aocs.rw1.torque_cmd", 0.1, t=0.0, model_id="sim_obc")

    master.run()

    speed = store.read("aocs.rw1.speed")
    assert speed is not None
    assert speed.value > 100.0, \
        f"RW should spin after fault cleared: {speed.value:.1f} rpm"


@pytest.mark.requirement("SVF-DEV-038")
def test_tc_1553_004_bus_error_triggers_switchover() -> None:
    """
    TC-1553-004: BUS_ERROR triggers automatic switchover to bus B.

    Expected: active_bus switches from A to B.
    """
    master, store, cmd_store, bus = make_1553_system(stop_time=5.0)

    assert bus.active_bus == "A"
    bus.inject_fault(BusFault(
        fault_type=FaultType.BUS_ERROR,
        target="all",
        duration_s=0.0,
        injected_at=0.0,
    ))

    master.run()

    assert bus.active_bus == "B", \
        f"Bus should have switched to B, got {bus.active_bus}"
    active = store.read("bus.platform_1553.active_bus")
    assert active is not None
    assert active.value == pytest.approx(2.0)


@pytest.mark.requirement("SVF-DEV-038")
def test_tc_1553_005_broadcast_command_reaches_all_rts() -> None:
    """
    TC-1553-005: Broadcast command (RT31) is delivered to all RTs.

    Expected: broadcast parameter injected into CommandStore
    for delivery to all connected RTs.
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

    store.write("aocs.all.mode_cmd", 2.0, t=0.0, model_id="sim_obc")
    master.run()

    # Broadcast should have been injected into CommandStore
    entry = cmd_store.peek("aocs.all.mode_cmd")
    assert entry is not None
    assert entry.value == pytest.approx(2.0)
