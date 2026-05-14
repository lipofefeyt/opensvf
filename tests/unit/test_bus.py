"""
Tests for Bus abstract base class and fault injection.
Implements: SVF-DEV-038
"""

import pytest
from svf.core.abstractions import SyncProtocol
from svf.stores.parameter_store import ParameterStore
from svf.stores.command_store import CommandStore
from svf.bus.bus import Bus, BusFault, FaultType
from svf.core.equipment import PortDefinition, PortDirection, InterfaceType


class _NoSync(SyncProtocol):
    def reset(self) -> None: pass
    def publish_ready(self, model_id: str, t: float) -> None: pass
    def wait_for_ready(self, expected: list[str], timeout: float) -> bool: return True


class _SimpleBus(Bus):
    """Minimal Bus implementation for testing."""

    def _declare_ports(self) -> list[PortDefinition]:
        return [
            PortDefinition("bc_in", PortDirection.IN,
                           interface_type=InterfaceType.MIL1553_BC),
            PortDefinition("rt1_out", PortDirection.OUT,
                           interface_type=InterfaceType.MIL1553_RT),
        ]

    def initialise(self, start_time: float = 0.0) -> None:
        pass

    def do_step(self, t: float, dt: float) -> None:
        pass


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
def bus(sync: _NoSync, store: ParameterStore,
        cmd_store: CommandStore) -> _SimpleBus:
    b = _SimpleBus("platform_1553", sync, store, cmd_store)
    b.initialise()
    return b


# ── BusFault tests ────────────────────────────────────────────────────────────

@pytest.mark.requirement("SVF-DEV-038")
def test_fault_is_active_immediately(bus: _SimpleBus) -> None:
    """Injected fault is immediately active."""
    fault = BusFault(FaultType.NO_RESPONSE, "rw1", 10.0, injected_at=0.0)
    bus.inject_fault(fault)
    assert bus.has_fault(FaultType.NO_RESPONSE, "rw1", t=0.0)


@pytest.mark.requirement("SVF-DEV-038")
def test_fault_expires_after_duration(bus: _SimpleBus) -> None:
    """Fault expires after duration_s simulation seconds."""
    fault = BusFault(FaultType.NO_RESPONSE, "rw1", 5.0, injected_at=0.0)
    bus.inject_fault(fault)
    assert bus.has_fault(FaultType.NO_RESPONSE, "rw1", t=4.9)
    assert not bus.has_fault(FaultType.NO_RESPONSE, "rw1", t=5.0)


@pytest.mark.requirement("SVF-DEV-038")
def test_permanent_fault_never_expires(bus: _SimpleBus) -> None:
    """Fault with duration_s=0.0 never expires."""
    fault = BusFault(FaultType.BUS_ERROR, "rw1", 0.0, injected_at=0.0)
    bus.inject_fault(fault)
    assert bus.has_fault(FaultType.BUS_ERROR, "rw1", t=99999.0)


@pytest.mark.requirement("SVF-DEV-038")
def test_clear_specific_fault(bus: _SimpleBus) -> None:
    """clear_faults(target) removes only that target's faults."""
    bus.inject_fault(BusFault(FaultType.NO_RESPONSE, "rw1", 0.0, 0.0))
    bus.inject_fault(BusFault(FaultType.NO_RESPONSE, "rw2", 0.0, 0.0))
    bus.clear_faults("rw1")
    assert not bus.has_fault(FaultType.NO_RESPONSE, "rw1", t=0.0)
    assert bus.has_fault(FaultType.NO_RESPONSE, "rw2", t=0.0)


@pytest.mark.requirement("SVF-DEV-038")
def test_clear_all_faults(bus: _SimpleBus) -> None:
    """clear_faults() removes all faults."""
    bus.inject_fault(BusFault(FaultType.NO_RESPONSE, "rw1", 0.0, 0.0))
    bus.inject_fault(BusFault(FaultType.BUS_ERROR, "rw2", 0.0, 0.0))
    bus.clear_faults()
    assert len(bus.active_faults(t=0.0)) == 0


@pytest.mark.requirement("SVF-DEV-038")
def test_broadcast_fault_affects_all(bus: _SimpleBus) -> None:
    """Fault targeting 'all' affects any equipment."""
    bus.inject_fault(BusFault(FaultType.NO_RESPONSE, "all", 0.0, 0.0))
    assert bus.has_fault(FaultType.NO_RESPONSE, "rw1", t=0.0)
    assert bus.has_fault(FaultType.NO_RESPONSE, "rw2", t=0.0)
    assert bus.has_fault(FaultType.NO_RESPONSE, "str1", t=0.0)


@pytest.mark.requirement("SVF-DEV-038")
def test_fault_injected_via_command_store(
    bus: _SimpleBus, cmd_store: CommandStore
) -> None:
    """Fault injected via CommandStore naming convention."""
    cmd_store.inject(
        "bus.platform_1553.fault.rw1.no_response",
        value=5.0,
        source_id="test"
    )
    bus.on_tick(t=0.0, dt=0.1)
    assert bus.has_fault(FaultType.NO_RESPONSE, "rw1", t=0.1)


@pytest.mark.requirement("SVF-DEV-038")
def test_fault_replaced_by_new_injection(bus: _SimpleBus) -> None:
    """Second injection of same fault type+target replaces first."""
    bus.inject_fault(BusFault(FaultType.NO_RESPONSE, "rw1", 5.0, 0.0))
    bus.inject_fault(BusFault(FaultType.NO_RESPONSE, "rw1", 10.0, 0.0))
    active = bus.active_faults(t=0.0)
    no_resp = [f for f in active
               if f.fault_type == FaultType.NO_RESPONSE
               and f.target == "rw1"]
    assert len(no_resp) == 1
    assert no_resp[0].duration_s == 10.0


@pytest.mark.requirement("SVF-DEV-038")
def test_bus_id_in_equipment_id(bus: _SimpleBus) -> None:
    """Bus equipment_id follows convention bus.{bus_id}."""
    assert bus.equipment_id == "bus.platform_1553"
    assert bus.bus_id == "platform_1553"
