"""Tests for CAN bus adapter."""
from __future__ import annotations
import pytest
from svf.core.abstractions import SyncProtocol
from svf.stores.parameter_store import ParameterStore
from svf.stores.command_store import CommandStore
from svf.bus.can import CanBus, CanMessage
from svf.bus.bus import BusFault, FaultType


class _NoSync(SyncProtocol):
    def reset(self) -> None: pass
    def publish_ready(self, model_id: str, t: float) -> None: pass
    def wait_for_ready(self, expected: list[str], timeout: float) -> bool:
        return True


@pytest.fixture
def can_system():
    store     = ParameterStore()
    cmd_store = CommandStore()
    messages = [
        CanMessage(can_id=0x100, parameter="aocs.rw1.torque_cmd",
                   direction="tx", node_id="rw1"),
        CanMessage(can_id=0x101, parameter="aocs.rw1.speed",
                   direction="rx", node_id="rw1"),
        CanMessage(can_id=0x1ABCDEF, parameter="eps.battery.voltage",
                   direction="rx", node_id="pcdu", extended=True),
    ]
    bus = CanBus("platform_can", messages=messages,
                 sync_protocol=_NoSync(), store=store,
                 command_store=cmd_store)
    bus.initialise()
    return bus, store, cmd_store


class TestCanSuite:

    @pytest.mark.requirement("SVF-DEV-038")
    def test_tx_message_routed_to_command_store(self, can_system) -> None:
        """TX message routes OBC command to node command store."""
        bus, store, cmd_store = can_system
        store.write("aocs.rw1.torque_cmd", 0.05, t=0.0, model_id="obc")
        bus.do_step(t=0.0, dt=0.1)
        entry = cmd_store.take("aocs.rw1.torque_cmd")
        assert entry is not None
        assert entry.value == pytest.approx(0.05)

    @pytest.mark.requirement("SVF-DEV-038")
    def test_rx_message_routed_to_store(self, can_system) -> None:
        """RX message routes node telemetry to OBC parameter store."""
        bus, store, cmd_store = can_system
        store.write("aocs.rw1.speed", 1200.0, t=0.0, model_id="rw1")
        bus.do_step(t=0.0, dt=0.1)
        entry = store.read("can.platform_can.rw1.aocs.rw1.speed")
        assert entry is not None
        assert entry.value == pytest.approx(1200.0)

    @pytest.mark.requirement("SVF-DEV-038")
    def test_bus_off_blocks_all_traffic(self, can_system) -> None:
        """BUS_ERROR fault causes bus-off — no messages routed."""
        bus, store, cmd_store = can_system
        bus.inject_fault(BusFault(
            fault_type=FaultType.BUS_ERROR,
            target="all",
            duration_s=5.0,
            injected_at=0.0,
        ))
        store.write("aocs.rw1.torque_cmd", 0.05, t=0.0, model_id="obc")
        bus.do_step(t=0.0, dt=0.1)
        assert bus.bus_off is True
        assert "aocs.rw1.torque_cmd" not in cmd_store.pending()

    @pytest.mark.requirement("SVF-DEV-038")
    def test_node_error_blocks_only_that_node(self, can_system) -> None:
        """NO_RESPONSE fault blocks only the affected node."""
        bus, store, cmd_store = can_system
        bus.inject_fault(BusFault(
            fault_type=FaultType.NO_RESPONSE,
            target="rw1",
            duration_s=5.0,
            injected_at=0.0,
        ))
        store.write("aocs.rw1.speed", 1200.0, t=0.0, model_id="rw1")
        store.write("eps.battery.voltage", 28.0, t=0.0, model_id="pcdu")
        bus.do_step(t=0.0, dt=0.1)
        # rw1 blocked
        assert store.read("can.platform_can.rw1.aocs.rw1.speed") is None
        # pcdu not blocked
        entry = store.read("can.platform_can.pcdu.eps.battery.voltage")
        assert entry is not None

    @pytest.mark.requirement("SVF-DEV-038")
    def test_bad_parity_blocks_all_messages(self, can_system) -> None:
        """BAD_PARITY fault corrupts all messages on the bus."""
        bus, store, cmd_store = can_system
        bus.inject_fault(BusFault(
            fault_type=FaultType.BAD_PARITY,
            target="all",
            duration_s=5.0,
            injected_at=0.0,
        ))
        store.write("aocs.rw1.speed", 1200.0, t=0.0, model_id="rw1")
        bus.do_step(t=0.0, dt=0.1)
        assert store.read("can.platform_can.rw1.aocs.rw1.speed") is None

    @pytest.mark.requirement("SVF-DEV-038")
    def test_extended_id_validation(self) -> None:
        """Extended CAN ID must be within 29-bit range."""
        with pytest.raises(ValueError):
            CanMessage(can_id=0x20000000, parameter="x",
                       direction="rx", node_id="n", extended=True)

    @pytest.mark.requirement("SVF-DEV-038")
    def test_standard_id_validation(self) -> None:
        """Standard CAN ID must be within 11-bit range."""
        with pytest.raises(ValueError):
            CanMessage(can_id=0x800, parameter="x",
                       direction="rx", node_id="n", extended=False)
