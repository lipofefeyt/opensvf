"""
Tests for MIL-STD-1553 Bus adapter.
Implements: SVF-DEV-038
"""

import pytest
from svf.abstractions import SyncProtocol
from svf.parameter_store import ParameterStore
from svf.command_store import CommandStore
from svf.mil1553 import Mil1553Bus, SubaddressMapping, BROADCAST_RT
from svf.bus import BusFault, FaultType


class _NoSync(SyncProtocol):
    def reset(self) -> None: pass
    def publish_ready(self, model_id: str, t: float) -> None: pass
    def wait_for_ready(self, expected: list[str], timeout: float) -> bool:
        return True


@pytest.fixture
def sync() -> _NoSync:
    return _NoSync()


@pytest.fixture
def store() -> ParameterStore:
    return ParameterStore()


@pytest.fixture
def cmd_store() -> CommandStore:
    return CommandStore()


@pytest.fixture
def mappings() -> list[SubaddressMapping]:
    return [
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


@pytest.fixture
def bus(
    sync: _NoSync,
    store: ParameterStore,
    cmd_store: CommandStore,
    mappings: list[SubaddressMapping],
) -> Mil1553Bus:
    b = Mil1553Bus(
        bus_id="platform_1553",
        rt_count=5,
        mappings=mappings,
        sync_protocol=sync,
        store=store,
        command_store=cmd_store,
    )
    b.initialise()
    return b


# ── Construction tests ────────────────────────────────────────────────────────

@pytest.mark.requirement("1553-001", "1553-002", "1553-003", "1553-004", "1553-010", "SVF-DEV-038")
def test_bus_declares_correct_ports(bus: Mil1553Bus) -> None:
    """Bus declares one BC port and rt_count RT ports."""
    assert "bc_in" in bus.ports
    for i in range(1, 6):
        assert f"rt{i}_out" in bus.ports


@pytest.mark.requirement("SVF-DEV-038")
def test_subaddress_mapping_validation() -> None:
    """SubaddressMapping validates RT address and subaddress ranges."""
    with pytest.raises(ValueError, match="RT address"):
        SubaddressMapping(rt_address=0, subaddress=1,
                         parameter="p", direction="BC_to_RT")
    with pytest.raises(ValueError, match="Subaddress"):
        SubaddressMapping(rt_address=1, subaddress=0,
                         parameter="p", direction="BC_to_RT")
    with pytest.raises(ValueError, match="Direction"):
        SubaddressMapping(rt_address=1, subaddress=1,
                         parameter="p", direction="INVALID")


# ── Routing tests ─────────────────────────────────────────────────────────────

@pytest.mark.requirement("SVF-DEV-038")
def test_bc_to_rt_routes_parameter(
    bus: Mil1553Bus,
    store: ParameterStore,
    cmd_store: CommandStore,
) -> None:
    """BC_to_RT mapping routes parameter from ParameterStore to CommandStore."""
    store.write("aocs.rw1.torque_cmd", 0.1, t=0.0, model_id="obc")
    bus.do_step(t=0.0, dt=1.0)
    entry = cmd_store.peek("aocs.rw1.torque_cmd")
    assert entry is not None
    assert entry.value == pytest.approx(0.1)


@pytest.mark.requirement("SVF-DEV-038")
def test_rt_to_bc_routes_telemetry(
    bus: Mil1553Bus,
    store: ParameterStore,
) -> None:
    """RT_to_BC mapping routes telemetry from equipment to OBC namespace."""
    store.write("aocs.rw1.speed", 1500.0, t=0.0, model_id="rw1")
    bus.do_step(t=0.0, dt=1.0)
    entry = store.read("obc.rt5.aocs.rw1.speed")
    assert entry is not None
    assert entry.value == pytest.approx(1500.0)


@pytest.mark.requirement("SVF-DEV-038")
def test_no_response_fault_blocks_bc_to_rt(
    bus: Mil1553Bus,
    store: ParameterStore,
    cmd_store: CommandStore,
) -> None:
    """NO_RESPONSE fault blocks BC_to_RT messages to affected RT."""
    bus.inject_fault(BusFault(FaultType.NO_RESPONSE, "rt5", 0.0, 0.0))
    store.write("aocs.rw1.torque_cmd", 0.1, t=0.0, model_id="obc")
    bus.do_step(t=0.0, dt=1.0)
    entry = cmd_store.peek("aocs.rw1.torque_cmd")
    assert entry is None


@pytest.mark.requirement("SVF-DEV-038")
def test_no_response_fault_blocks_rt_to_bc(
    bus: Mil1553Bus,
    store: ParameterStore,
) -> None:
    """NO_RESPONSE fault blocks RT_to_BC telemetry from affected RT."""
    bus.inject_fault(BusFault(FaultType.NO_RESPONSE, "rt5", 0.0, 0.0))
    store.write("aocs.rw1.speed", 1500.0, t=0.0, model_id="rw1")
    bus.do_step(t=0.0, dt=1.0)
    entry = store.read("obc.rt5.aocs.rw1.speed")
    assert entry is None


@pytest.mark.requirement("SVF-DEV-038")
def test_broadcast_mapping_reaches_all_rts(
    sync: _NoSync,
    store: ParameterStore,
    cmd_store: CommandStore,
) -> None:
    """Broadcast RT address 31 delivers command to all RTs."""
    broadcast_mappings = [
        SubaddressMapping(
            rt_address=BROADCAST_RT, subaddress=1,
            parameter="aocs.all.mode_cmd",
            direction="BC_to_RT",
        ),
    ]
    bus = Mil1553Bus(
        bus_id="platform_1553",
        rt_count=3,
        mappings=broadcast_mappings,
        sync_protocol=sync,
        store=store,
        command_store=cmd_store,
    )
    bus.initialise()
    store.write("aocs.all.mode_cmd", 2.0, t=0.0, model_id="obc")
    bus.do_step(t=0.0, dt=1.0)
    entry = cmd_store.peek("aocs.all.mode_cmd")
    assert entry is not None
    assert entry.value == pytest.approx(2.0)


@pytest.mark.requirement("SVF-DEV-038")
def test_bus_error_triggers_switchover(
    bus: Mil1553Bus,
    store: ParameterStore,
) -> None:
    """BUS_ERROR fault triggers automatic switchover to redundant bus."""
    assert bus.active_bus == "A"
    bus.inject_fault(BusFault(FaultType.BUS_ERROR, "all", 0.0, 0.0))
    bus.do_step(t=0.0, dt=1.0)
    assert bus.active_bus == "B"


@pytest.mark.requirement("SVF-DEV-038")
def test_fault_clears_after_duration(
    bus: Mil1553Bus,
    store: ParameterStore,
    cmd_store: CommandStore,
) -> None:
    """Routing resumes after timed fault expires."""
    bus.inject_fault(BusFault(FaultType.NO_RESPONSE, "rt5", 5.0, 0.0))
    store.write("aocs.rw1.torque_cmd", 0.1, t=0.0, model_id="obc")

    # During fault — blocked
    bus.do_step(t=0.0, dt=1.0)
    assert cmd_store.peek("aocs.rw1.torque_cmd") is None

    # After fault expires — routing resumes
    bus._expire_faults(t=5.0)
    bus.do_step(t=5.0, dt=1.0)
    entry = cmd_store.peek("aocs.rw1.torque_cmd")
    assert entry is not None
