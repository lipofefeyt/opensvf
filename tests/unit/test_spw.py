"""Tests for SpaceWire bus adapter.
Implements: SPW-001, SPW-002, SPW-003, SPW-004
"""
from __future__ import annotations

from typing import NamedTuple

import pytest
from svf.core.abstractions import SyncProtocol
from svf.stores.parameter_store import ParameterStore
from svf.stores.command_store import CommandStore
from svf.bus.spw import SpwBus, SpwNode, RmapMapping
from svf.bus.bus import BusFault, FaultType


class _NoSync(SyncProtocol):
    def reset(self) -> None:
        pass

    def publish_ready(self, model_id: str, t: float) -> None:
        pass

    def wait_for_ready(self, expected: list[str], timeout: float) -> bool:
        return True


class SpwFixture(NamedTuple):
    """Typed fixture bundle for SpaceWire bus tests."""

    bus: SpwBus
    store: ParameterStore
    cmd_store: CommandStore


@pytest.fixture
def spw_fixture() -> SpwFixture:
    """Two-node SpW bus: str1 (read) + payload (write)."""
    store = ParameterStore()
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
    return SpwFixture(bus=bus, store=store, cmd_store=cmd_store)


class SpwBusSuite:
    """Behavioural tests for SpaceWire + RMAP bus adapter."""

    # ── SPW-001: logical address validation ───────────────────────────────────

    @pytest.mark.requirement("SPW-001")
    def test_logical_address_below_minimum_raises(self) -> None:
        """Logical address below 32 raises ValueError."""
        with pytest.raises(ValueError):
            RmapMapping(logical_address=0x00, register_address=0,
                        parameter="x", transaction_type="read")

    @pytest.mark.requirement("SPW-001")
    def test_logical_address_reserved_255_raises(self) -> None:
        """Logical address 0xFF (reserved) raises ValueError."""
        with pytest.raises(ValueError):
            RmapMapping(logical_address=0xFF, register_address=0,
                        parameter="x", transaction_type="read")

    @pytest.mark.requirement("SPW-001")
    def test_invalid_transaction_type_raises(self) -> None:
        """RmapMapping rejects transaction_type other than 'read' or 'write'."""
        with pytest.raises(ValueError):
            RmapMapping(logical_address=0x20, register_address=0,
                        parameter="x", transaction_type="readwrite")

    @pytest.mark.requirement("SPW-001")
    def test_invalid_data_length_raises(self) -> None:
        """data_length must be 1, 2, 4, or 8."""
        with pytest.raises(ValueError):
            RmapMapping(logical_address=0x20, register_address=0,
                        parameter="x", transaction_type="read",
                        data_length=3)

    # ── SPW-002: RMAP write ───────────────────────────────────────────────────

    @pytest.mark.requirement("SPW-002")
    def test_rmap_write_routes_to_command_store(
        self, spw_fixture: SpwFixture
    ) -> None:
        """RMAP write routes OBC command to node CommandStore."""
        spw_fixture.store.write("payload.mode_cmd", 2.0, t=0.0, model_id="obc")
        spw_fixture.bus.do_step(t=0.0, dt=0.1)
        entry = spw_fixture.cmd_store.take("payload.mode_cmd")
        assert entry is not None
        assert entry.value == pytest.approx(2.0)

    # ── SPW-003: RMAP read ────────────────────────────────────────────────────

    @pytest.mark.requirement("SPW-003")
    def test_rmap_read_routes_to_canonical_telemetry(
        self, spw_fixture: SpwFixture
    ) -> None:
        """RMAP read routes node TM to spw.{bus_id}.{node_id}.{parameter}."""
        spw_fixture.store.write(
            "aocs.str1.quaternion_w", 1.0, t=0.0, model_id="str1"
        )
        spw_fixture.bus.do_step(t=0.0, dt=0.1)
        entry = spw_fixture.store.read(
            "spw.platform_spw.str1.aocs.str1.quaternion_w"
        )
        assert entry is not None
        assert entry.value == pytest.approx(1.0)

    # ── SPW-004: link error faults ────────────────────────────────────────────

    @pytest.mark.requirement("SPW-004")
    def test_link_error_blocks_transaction_to_node(
        self, spw_fixture: SpwFixture
    ) -> None:
        """BUS_ERROR on a specific node blocks all RMAP transactions to it."""
        spw_fixture.store.write(
            "aocs.str1.quaternion_w", 1.0, t=0.0, model_id="str1"
        )
        spw_fixture.bus.inject_fault(BusFault(
            fault_type=FaultType.BUS_ERROR, target="str1",
            duration_s=5.0, injected_at=0.0,
        ))
        spw_fixture.bus.do_step(t=0.0, dt=0.1)
        assert spw_fixture.store.read(
            "spw.platform_spw.str1.aocs.str1.quaternion_w"
        ) is None

    @pytest.mark.requirement("SPW-004")
    def test_global_link_error_blocks_all_nodes(
        self, spw_fixture: SpwFixture
    ) -> None:
        """BUS_ERROR targeting 'all' blocks RMAP to every node."""
        spw_fixture.store.write(
            "aocs.str1.quaternion_w", 1.0, t=0.0, model_id="str1"
        )
        spw_fixture.store.write(
            "payload.mode_cmd", 2.0, t=0.0, model_id="obc"
        )
        spw_fixture.bus.inject_fault(BusFault(
            fault_type=FaultType.BUS_ERROR, target="all",
            duration_s=5.0, injected_at=0.0,
        ))
        spw_fixture.bus.do_step(t=0.0, dt=0.1)
        assert spw_fixture.store.read(
            "spw.platform_spw.str1.aocs.str1.quaternion_w"
        ) is None
        assert spw_fixture.cmd_store.take("payload.mode_cmd") is None

    @pytest.mark.requirement("SPW-004")
    def test_fault_expires_and_transactions_resume(
        self, spw_fixture: SpwFixture
    ) -> None:
        """Time-limited link error expires; RMAP transactions resume."""
        spw_fixture.bus.inject_fault(BusFault(
            fault_type=FaultType.BUS_ERROR, target="str1",
            duration_s=2.0, injected_at=0.0,
        ))
        spw_fixture.store.write(
            "aocs.str1.quaternion_w", 1.0, t=3.0, model_id="str1"
        )
        spw_fixture.bus.do_step(t=3.0, dt=0.1)
        assert spw_fixture.store.read(
            "spw.platform_spw.str1.aocs.str1.quaternion_w"
        ) is not None

    @pytest.mark.requirement("SPW-004")
    def test_fault_injected_via_command_store(
        self, spw_fixture: SpwFixture
    ) -> None:
        """Faults injectable via bus.{id}.fault.{target}.{type} in CommandStore."""
        spw_fixture.cmd_store.inject(
            name="bus.platform_spw.fault.str1.bus_error",
            value=5.0, t=0.0, source_id="test",
        )
        spw_fixture.store.write(
            "aocs.str1.quaternion_w", 1.0, t=0.0, model_id="str1"
        )
        spw_fixture.bus.on_tick(t=0.0, dt=0.1)
        assert spw_fixture.store.read(
            "spw.platform_spw.str1.aocs.str1.quaternion_w"
        ) is None
