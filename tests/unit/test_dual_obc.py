"""
Tests for DualObcAdapter  -  dual-OBC topology.
Implements: SVF-DEV-166, SVF-DEV-167, SVF-DEV-168
"""

import pytest
from collections.abc import Iterator

from svf.core.abstractions import SyncProtocol
from svf.core.equipment import PortDefinition
from svf.models.dhs.hil_adapter import HilAdapter
from svf.models.dhs.dual_obc import DualObcAdapter
from svf.pus.tm import PusTmPacket
from svf.stores.parameter_store import ParameterStore
from svf.stores.command_store import CommandStore


# ── Test doubles ─────────────────────────────────────────────────────────────

class _NoSync(SyncProtocol):
    def reset(self) -> None: pass
    def publish_ready(self, model_id: str, t: float) -> None: pass
    def wait_for_ready(self, expected: list[str], timeout: float) -> bool: return True


class _FakeObc(HilAdapter):
    """Minimal HilAdapter stub for routing logic tests."""

    def __init__(self, equipment_id: str) -> None:
        super().__init__(equipment_id, _NoSync(), ParameterStore(), CommandStore())
        self.ticked_at: list[float] = []
        self.tcs_received: list[bytes] = []
        self._connected: bool = True
        self._tm_queue: list[PusTmPacket] = []

    def _declare_ports(self) -> list[PortDefinition]:
        return []

    def initialise(self, start_time: float = 0.0) -> None:
        pass

    def do_step(self, t: float, dt: float) -> None:
        self.ticked_at.append(t)

    def connect(self) -> None:
        self._connected = True

    def disconnect(self) -> None:
        self._connected = False

    def is_connected(self) -> bool:
        return self._connected

    def receive_tc(self, raw_tc: bytes, t: float = 0.0) -> list[PusTmPacket]:
        self.tcs_received.append(raw_tc)
        return []

    def get_tm_queue(self) -> list[PusTmPacket]:
        q = list(self._tm_queue)
        self._tm_queue.clear()
        return q


def _make_tm(service: int = 1, subservice: int = 1) -> PusTmPacket:
    return PusTmPacket(apid=0x100, sequence_count=1, service=service, subservice=subservice)


@pytest.fixture
def primary() -> _FakeObc:
    """Fresh primary OBC stub."""
    return _FakeObc("obc_primary")


@pytest.fixture
def secondary() -> _FakeObc:
    """Fresh secondary OBC stub."""
    return _FakeObc("obc_secondary")


@pytest.fixture
def dual(primary: _FakeObc, secondary: _FakeObc) -> Iterator[DualObcAdapter]:
    """DualObcAdapter wrapping primary + secondary stubs."""
    adapter = DualObcAdapter(
        primary=primary,
        secondary=secondary,
        sync_protocol=_NoSync(),
        store=ParameterStore(),
        command_store=CommandStore(),
    )
    adapter.initialise()
    yield adapter
    adapter.teardown()


# ── Identity and type ─────────────────────────────────────────────────────────

@pytest.mark.requirement("SVF-DEV-166")
def test_dual_obc_is_hil_adapter(dual: DualObcAdapter) -> None:
    assert isinstance(dual, HilAdapter)


@pytest.mark.requirement("SVF-DEV-166")
def test_dual_obc_primary_is_active_by_default(dual: DualObcAdapter) -> None:
    assert dual.active_id == "primary"


# ── Tick routing ─────────────────────────────────────────────────────────────

@pytest.mark.requirement("SVF-DEV-167")
def test_dual_obc_only_active_obc_is_ticked(
    dual: DualObcAdapter, primary: _FakeObc, secondary: _FakeObc
) -> None:
    """Only the active OBC receives on_tick() calls; secondary stays idle."""
    dual.on_tick(0.0, 0.1)
    dual.on_tick(0.1, 0.1)
    assert primary.ticked_at == [0.0, 0.1]
    assert secondary.ticked_at == []


@pytest.mark.requirement("SVF-DEV-167")
def test_dual_obc_secondary_ticked_after_switch(
    dual: DualObcAdapter, primary: _FakeObc, secondary: _FakeObc
) -> None:
    dual.on_tick(0.0, 0.1)
    dual.switch_to_secondary()
    dual.on_tick(0.1, 0.1)
    assert primary.ticked_at == [0.0]
    assert secondary.ticked_at == [0.1]


# ── TC routing ───────────────────────────────────────────────────────────────

@pytest.mark.requirement("SVF-DEV-167")
def test_dual_obc_tc_forwarded_to_active_only(
    dual: DualObcAdapter, primary: _FakeObc, secondary: _FakeObc
) -> None:
    tc = b"\x18\x40\x00\x01\x00\x00"
    dual.receive_tc(tc)
    assert primary.tcs_received == [tc]
    assert secondary.tcs_received == []


@pytest.mark.requirement("SVF-DEV-167")
def test_dual_obc_tc_routes_to_secondary_after_switch(
    dual: DualObcAdapter, primary: _FakeObc, secondary: _FakeObc
) -> None:
    dual.switch_to_secondary()
    tc = b"\x18\x40\x00\x01\x00\x00"
    dual.receive_tc(tc)
    assert secondary.tcs_received == [tc]
    assert primary.tcs_received == []


# ── TM routing ───────────────────────────────────────────────────────────────

@pytest.mark.requirement("SVF-DEV-167")
def test_dual_obc_tm_drained_from_active(
    dual: DualObcAdapter, primary: _FakeObc, secondary: _FakeObc
) -> None:
    tm = _make_tm(17, 2)
    primary._tm_queue.append(tm)
    secondary._tm_queue.append(_make_tm(3, 25))

    result = dual.get_tm_queue()
    assert result == [tm]
    assert primary._tm_queue == []     # drained
    assert secondary._tm_queue != []   # untouched


@pytest.mark.requirement("SVF-DEV-167")
def test_dual_obc_get_primary_tm_independent_of_active(
    dual: DualObcAdapter, primary: _FakeObc
) -> None:
    """get_primary_tm() always drains the primary regardless of which is active."""
    dual.switch_to_secondary()
    tm = _make_tm(17, 2)
    primary._tm_queue.append(tm)
    assert dual.get_primary_tm() == [tm]


@pytest.mark.requirement("SVF-DEV-167")
def test_dual_obc_get_secondary_tm_independent_of_active(
    dual: DualObcAdapter, secondary: _FakeObc
) -> None:
    """get_secondary_tm() always drains the secondary regardless of active."""
    tm = _make_tm(5, 1)
    secondary._tm_queue.append(tm)
    assert dual.get_secondary_tm() == [tm]


# ── Manual failover ───────────────────────────────────────────────────────────

@pytest.mark.requirement("SVF-DEV-168")
def test_dual_obc_switch_to_secondary(dual: DualObcAdapter) -> None:
    dual.switch_to_secondary()
    assert dual.active_id == "secondary"


@pytest.mark.requirement("SVF-DEV-168")
def test_dual_obc_switch_back_to_primary(dual: DualObcAdapter) -> None:
    dual.switch_to_secondary()
    dual.switch_to_primary()
    assert dual.active_id == "primary"


# ── Auto-failover ─────────────────────────────────────────────────────────────

@pytest.mark.requirement("SVF-DEV-168")
def test_dual_obc_auto_failover_when_primary_disconnects(
    dual: DualObcAdapter, primary: _FakeObc
) -> None:
    """If primary loses connection mid-tick, DualObc auto-switches to secondary."""
    primary._connected = False
    dual.on_tick(0.0, 0.1)
    assert dual.active_id == "secondary"


@pytest.mark.requirement("SVF-DEV-168")
def test_dual_obc_auto_failover_when_secondary_disconnects(
    dual: DualObcAdapter, secondary: _FakeObc
) -> None:
    """If secondary loses connection, DualObc auto-switches back to primary."""
    dual.switch_to_secondary()
    secondary._connected = False
    dual.on_tick(0.0, 0.1)
    assert dual.active_id == "primary"


@pytest.mark.requirement("SVF-DEV-168")
def test_dual_obc_is_connected_reflects_active(
    dual: DualObcAdapter, primary: _FakeObc, secondary: _FakeObc
) -> None:
    assert dual.is_connected() is True
    primary._connected = False
    assert dual.is_connected() is False
    dual.switch_to_secondary()
    assert dual.is_connected() is True
