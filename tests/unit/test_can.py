"""Tests for CAN bus adapter.
Implements: CAN-001, CAN-002, CAN-003, CAN-004
"""
from __future__ import annotations

from typing import NamedTuple

import pytest
from svf.core.abstractions import SyncProtocol
from svf.stores.parameter_store import ParameterStore
from svf.stores.command_store import CommandStore
from svf.bus.can import CanBus, CanMessage
from svf.bus.bus import BusFault, FaultType


class _NoSync(SyncProtocol):
    def reset(self) -> None:
        pass

    def publish_ready(self, model_id: str, t: float) -> None:
        pass

    def wait_for_ready(self, expected: list[str], timeout: float) -> bool:
        return True


class CanFixture(NamedTuple):
    """Typed fixture bundle for CAN bus tests."""

    bus: CanBus
    store: ParameterStore
    cmd_store: CommandStore


@pytest.fixture
def can_fixture() -> CanFixture:
    """Two-node CAN bus (rw1 TX/RX + pcdu RX extended)."""
    store = ParameterStore()
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
    return CanFixture(bus=bus, store=store, cmd_store=cmd_store)


class CanBusSuite:
    """Behavioural tests for CAN 2.0B bus adapter."""

    # ── CAN-001: identifier validation ───────────────────────────────────────

    @pytest.mark.requirement("CAN-001")
    def test_extended_id_out_of_range_raises(self) -> None:
        """Extended CAN ID exceeding 29-bit range raises ValueError."""
        with pytest.raises(ValueError):
            CanMessage(can_id=0x20000000, parameter="x",
                       direction="rx", node_id="n", extended=True)

    @pytest.mark.requirement("CAN-001")
    def test_standard_id_out_of_range_raises(self) -> None:
        """Standard CAN ID exceeding 11-bit range raises ValueError."""
        with pytest.raises(ValueError):
            CanMessage(can_id=0x800, parameter="x",
                       direction="rx", node_id="n", extended=False)

    @pytest.mark.requirement("CAN-001")
    def test_invalid_direction_raises(self) -> None:
        """CanMessage rejects direction values other than 'tx' or 'rx'."""
        with pytest.raises(ValueError):
            CanMessage(can_id=0x100, parameter="x",
                       direction="both", node_id="n")

    @pytest.mark.requirement("CAN-001")
    def test_invalid_dlc_raises(self) -> None:
        """DLC outside 0–8 raises ValueError."""
        with pytest.raises(ValueError):
            CanMessage(can_id=0x100, parameter="x",
                       direction="rx", node_id="n", dlc=9)

    # ── CAN-002: routing ──────────────────────────────────────────────────────

    @pytest.mark.requirement("CAN-002")
    def test_tx_message_routed_to_command_store(
        self, can_fixture: CanFixture
    ) -> None:
        """TX message routes OBC command to node CommandStore."""
        can_fixture.store.write(
            "aocs.rw1.torque_cmd", 0.05, t=0.0, model_id="obc"
        )
        can_fixture.bus.do_step(t=0.0, dt=0.1)
        entry = can_fixture.cmd_store.take("aocs.rw1.torque_cmd")
        assert entry is not None
        assert entry.value == pytest.approx(0.05)

    @pytest.mark.requirement("CAN-002")
    def test_rx_message_routed_to_canonical_telemetry(
        self, can_fixture: CanFixture
    ) -> None:
        """RX message routes node TM to can.{bus_id}.{node_id}.{parameter}."""
        can_fixture.store.write(
            "aocs.rw1.speed", 1200.0, t=0.0, model_id="rw1"
        )
        can_fixture.bus.do_step(t=0.0, dt=0.1)
        entry = can_fixture.store.read("can.platform_can.rw1.aocs.rw1.speed")
        assert entry is not None
        assert entry.value == pytest.approx(1200.0)

    # ── CAN-003: bus-off ──────────────────────────────────────────────────────

    @pytest.mark.requirement("CAN-003")
    def test_bus_error_fault_causes_bus_off(
        self, can_fixture: CanFixture
    ) -> None:
        """BUS_ERROR on 'all' suspends all CAN traffic."""
        can_fixture.bus.inject_fault(BusFault(
            fault_type=FaultType.BUS_ERROR, target="all",
            duration_s=5.0, injected_at=0.0,
        ))
        can_fixture.store.write(
            "aocs.rw1.torque_cmd", 0.05, t=0.0, model_id="obc"
        )
        can_fixture.bus.do_step(t=0.0, dt=0.1)
        assert can_fixture.bus.bus_off is True
        assert "aocs.rw1.torque_cmd" not in can_fixture.cmd_store.pending()

    @pytest.mark.requirement("CAN-003")
    def test_bus_recovers_after_fault_expires(
        self, can_fixture: CanFixture
    ) -> None:
        """Bus-off clears once the BUS_ERROR fault expires."""
        can_fixture.bus.inject_fault(BusFault(
            fault_type=FaultType.BUS_ERROR, target="all",
            duration_s=1.0, injected_at=0.0,
        ))
        can_fixture.bus.on_tick(t=0.0, dt=0.1)
        assert can_fixture.bus.bus_off is True

        can_fixture.store.write(
            "aocs.rw1.torque_cmd", 0.05, t=2.0, model_id="obc"
        )
        can_fixture.bus.on_tick(t=2.0, dt=0.1)
        assert can_fixture.bus.bus_off is False
        assert can_fixture.cmd_store.take("aocs.rw1.torque_cmd") is not None

    # ── CAN-004: node faults and CommandStore injection ───────────────────────

    @pytest.mark.requirement("CAN-004")
    def test_no_response_blocks_only_affected_node(
        self, can_fixture: CanFixture
    ) -> None:
        """NO_RESPONSE blocks only the named node; other nodes route normally."""
        can_fixture.bus.inject_fault(BusFault(
            fault_type=FaultType.NO_RESPONSE, target="rw1",
            duration_s=5.0, injected_at=0.0,
        ))
        can_fixture.store.write("aocs.rw1.speed",      1200.0, t=0.0, model_id="rw1")
        can_fixture.store.write("eps.battery.voltage",   28.0, t=0.0, model_id="pcdu")
        can_fixture.bus.do_step(t=0.0, dt=0.1)
        assert can_fixture.store.read(
            "can.platform_can.rw1.aocs.rw1.speed") is None
        assert can_fixture.store.read(
            "can.platform_can.pcdu.eps.battery.voltage") is not None

    @pytest.mark.requirement("CAN-004")
    def test_bad_parity_blocks_all_messages(
        self, can_fixture: CanFixture
    ) -> None:
        """BAD_PARITY corrupts all messages on the bus."""
        can_fixture.bus.inject_fault(BusFault(
            fault_type=FaultType.BAD_PARITY, target="all",
            duration_s=5.0, injected_at=0.0,
        ))
        can_fixture.store.write(
            "aocs.rw1.speed", 1200.0, t=0.0, model_id="rw1"
        )
        can_fixture.bus.do_step(t=0.0, dt=0.1)
        assert can_fixture.store.read(
            "can.platform_can.rw1.aocs.rw1.speed") is None

    @pytest.mark.requirement("CAN-004")
    def test_fault_injected_via_command_store(
        self, can_fixture: CanFixture
    ) -> None:
        """Faults injectable via bus.{id}.fault.{target}.{type} in CommandStore."""
        can_fixture.cmd_store.inject(
            name="bus.platform_can.fault.rw1.no_response",
            value=5.0, t=0.0, source_id="test",
        )
        can_fixture.store.write(
            "aocs.rw1.speed", 800.0, t=0.0, model_id="rw1"
        )
        can_fixture.bus.on_tick(t=0.0, dt=0.1)
        assert can_fixture.store.read(
            "can.platform_can.rw1.aocs.rw1.speed") is None

    @pytest.mark.requirement("CAN-004")
    def test_fault_expires_after_duration(
        self, can_fixture: CanFixture
    ) -> None:
        """Time-limited fault auto-expires; routing resumes afterwards."""
        can_fixture.bus.inject_fault(BusFault(
            fault_type=FaultType.NO_RESPONSE, target="rw1",
            duration_s=2.0, injected_at=0.0,
        ))
        can_fixture.store.write(
            "aocs.rw1.speed", 1000.0, t=0.5, model_id="rw1"
        )
        can_fixture.bus.on_tick(t=0.5, dt=0.1)
        assert can_fixture.store.read(
            "can.platform_can.rw1.aocs.rw1.speed") is None  # blocked

        can_fixture.store.write(
            "aocs.rw1.speed", 1000.0, t=3.0, model_id="rw1"
        )
        can_fixture.bus.on_tick(t=3.0, dt=0.1)
        assert can_fixture.store.read(
            "can.platform_can.rw1.aocs.rw1.speed") is not None  # resumed
