"""Tests for SpaceWire bus adapter."""
from __future__ import annotations
import pytest
from svf.abstractions import SyncProtocol
from svf.parameter_store import ParameterStore
from svf.command_store import CommandStore
from svf.spw import SpwBus, SpwNode, RmapMapping
from svf.bus import BusFault, FaultType


class _NoSync(SyncProtocol):
    def reset(self) -> None: pass
    def publish_ready(self, model_id: str, t: float) -> None: pass
    def wait_for_ready(self, expected: list[str], timeout: float) -> bool:
        return True


@pytest.fixture
def spw_system():
    store     = ParameterStore()
    cmd_store = CommandStore()
    nodes = [
        SpwNode(logical_address=0x20, node_id="str1",
                description="Star tracker"),
        SpwNode(logical_address=0x21, node_id="payload",
                description="Payload controller"),
    ]
    mappings = [
        RmapMapping(logical_address=0x20, register_address=0x0100,
                    parameter="aocs.str1.quaternion_w",
                    transaction_type="read"),
        RmapMapping(logical_address=0x21, register_address=0x0000,
                    parameter="payload.mode_cmd",
                    transaction_type="write"),
    ]
    bus = SpwBus("platform_spw", nodes=nodes, mappings=mappings,
                 sync_protocol=_NoSync(), store=store,
                 command_store=cmd_store)
    bus.initialise()
    return bus, store, cmd_store


class TestSpwSuite:

    @pytest.mark.requirement("SVF-DEV-038")
    def test_rmap_read_routes_to_store(self, spw_system) -> None:
        """RMAP read routes node value to OBC parameter store."""
        bus, store, cmd_store = spw_system
        store.write("aocs.str1.quaternion_w", 1.0, t=0.0,
                    model_id="str1")
        bus.do_step(t=0.0, dt=0.1)
        entry = store.read("spw.platform_spw.str1.aocs.str1.quaternion_w")
        assert entry is not None
        assert entry.value == pytest.approx(1.0)

    @pytest.mark.requirement("SVF-DEV-038")
    def test_rmap_write_routes_to_command_store(self, spw_system) -> None:
        """RMAP write routes OBC command to node command store."""
        bus, store, cmd_store = spw_system
        store.write("payload.mode_cmd", 2.0, t=0.0, model_id="obc")
        bus.do_step(t=0.0, dt=0.1)
        entry = cmd_store.take("payload.mode_cmd")
        assert entry is not None
        assert entry.value == pytest.approx(2.0)

    @pytest.mark.requirement("SVF-DEV-038")
    def test_link_error_blocks_transaction(self, spw_system) -> None:
        """Link error fault blocks all transactions to affected node."""
        bus, store, cmd_store = spw_system
        store.write("aocs.str1.quaternion_w", 1.0, t=0.0,
                    model_id="str1")
        bus.inject_fault(BusFault(
            fault_type=FaultType.BUS_ERROR,
            target="str1",
            duration_s=5.0,
            injected_at=0.0,
        ))
        bus.do_step(t=0.0, dt=0.1)
        entry = store.read("spw.platform_spw.str1.aocs.str1.quaternion_w")
        assert entry is None

    @pytest.mark.requirement("SVF-DEV-038")
    def test_fault_expiry(self, spw_system) -> None:
        """Fault expires and transactions resume."""
        bus, store, cmd_store = spw_system
        bus.inject_fault(BusFault(
            fault_type=FaultType.BUS_ERROR,
            target="str1",
            duration_s=2.0,
            injected_at=0.0,
        ))
        store.write("aocs.str1.quaternion_w", 1.0, t=3.0,
                    model_id="str1")
        bus.do_step(t=3.0, dt=0.1)  # fault expired
        entry = store.read("spw.platform_spw.str1.aocs.str1.quaternion_w")
        assert entry is not None

    @pytest.mark.requirement("SVF-DEV-038")
    def test_logical_address_validation(self) -> None:
        """RmapMapping rejects invalid logical addresses."""
        with pytest.raises(ValueError):
            RmapMapping(logical_address=0x00, register_address=0,
                        parameter="x", transaction_type="read")
        with pytest.raises(ValueError):
            RmapMapping(logical_address=0xFF, register_address=0,
                        parameter="x", transaction_type="read")
