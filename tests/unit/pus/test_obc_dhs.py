"""
Tests for OBC DHS behaviour (M8 extension).
Mode management, OBT, watchdog, memory.
Implements: SVF-DEV-038
"""

import pytest
from svf.abstractions import SyncProtocol
from svf.parameter_store import ParameterStore
from svf.command_store import CommandStore
from svf.models.obc import ObcEquipment, ObcConfig, MODE_SAFE, MODE_NOMINAL, MODE_PAYLOAD, WDG_WARNING, WDG_RESET


class _NoSync(SyncProtocol):
    def reset(self) -> None: pass
    def publish_ready(self, model_id: str, t: float) -> None: pass
    def wait_for_ready(self, expected: list[str], timeout: float) -> bool: return True


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
def obc(sync: _NoSync, store: ParameterStore, cmd_store: CommandStore) -> ObcEquipment:
    config = ObcConfig(
        apid=0x101,
        watchdog_period_s=10.0,
        initial_mode=MODE_SAFE,
    )
    eq = ObcEquipment(config, sync, store, cmd_store)
    eq.initialise(start_time=0.0)
    return eq


# ── Mode management ───────────────────────────────────────────────────────────

@pytest.mark.requirement("SVF-DEV-038")
def test_obc_initial_mode_is_safe(obc: ObcEquipment) -> None:
    """OBC starts in SAFE mode."""
    assert obc.mode == MODE_SAFE


@pytest.mark.requirement("SVF-DEV-038")
def test_obc_mode_transition_to_nominal(
    obc: ObcEquipment
) -> None:
    """Mode transitions to NOMINAL when commanded."""
    obc.receive("dhs.obc.mode_cmd", float(MODE_NOMINAL))
    obc.do_step(t=0.0, dt=1.0)
    assert obc.mode == MODE_NOMINAL


@pytest.mark.requirement("SVF-DEV-038")
def test_obc_mode_transition_generates_s5_event(
    obc: ObcEquipment
) -> None:
    """Mode transition generates S5 informative event."""
    obc.receive("dhs.obc.mode_cmd", float(MODE_NOMINAL))
    obc.do_step(t=0.0, dt=1.0)
    events = obc.get_tm_by_service(5, 1)
    assert len(events) > 0


@pytest.mark.requirement("SVF-DEV-038")
def test_obc_mode_transition_safe_to_nominal_to_payload(
    obc: ObcEquipment
) -> None:
    """Mode can transition through all states."""
    obc.receive("dhs.obc.mode_cmd", float(MODE_NOMINAL))
    obc.do_step(t=0.0, dt=1.0)
    assert obc.mode == MODE_NOMINAL

    obc.receive("dhs.obc.mode_cmd", float(MODE_PAYLOAD))
    obc.do_step(t=1.0, dt=1.0)
    assert obc.mode == MODE_PAYLOAD


# ── On-board time ─────────────────────────────────────────────────────────────

@pytest.mark.requirement("SVF-DEV-038")
def test_obc_obt_increments(obc: ObcEquipment) -> None:
    """OBT increments by dt on each step."""
    obc.do_step(t=0.0, dt=1.0)
    assert obc.obt == pytest.approx(1.0)
    obc.do_step(t=1.0, dt=1.0)
    assert obc.obt == pytest.approx(2.0)


@pytest.mark.requirement("SVF-DEV-038")
def test_obc_obt_written_to_port(
    obc: ObcEquipment
) -> None:
    """OBT written to dhs.obc.obt OUT port each tick."""
    obc.do_step(t=0.0, dt=5.0)
    assert obc.read_port("dhs.obc.obt") == pytest.approx(5.0)


# ── Watchdog ──────────────────────────────────────────────────────────────────

@pytest.mark.requirement("SVF-DEV-038")
def test_obc_watchdog_nominal_when_kicked(
    obc: ObcEquipment
) -> None:
    """Watchdog stays nominal when kicked regularly."""
    for i in range(5):
        obc.receive("dhs.obc.watchdog_kick", 1.0)
        obc.do_step(t=float(i), dt=1.0)
    assert obc.watchdog_status == 0  # WDG_NOMINAL


@pytest.mark.requirement("SVF-DEV-038")
def test_obc_watchdog_warning_on_timeout(
    obc: ObcEquipment
) -> None:
    """Watchdog goes to WARNING after timeout period."""
    # Don't kick watchdog — period is 10s
    for i in range(12):
        obc.do_step(t=float(i), dt=1.0)
    assert obc.watchdog_status == WDG_WARNING


@pytest.mark.requirement("SVF-DEV-038")
def test_obc_watchdog_reset_on_double_timeout(
    obc: ObcEquipment
) -> None:
    """Watchdog triggers reset after 2x timeout period."""
    for i in range(25):
        obc.do_step(t=float(i), dt=1.0)
    assert obc.watchdog_status == WDG_RESET
    assert obc.reset_count == 1
    assert obc.mode == MODE_SAFE


@pytest.mark.requirement("SVF-DEV-038")
def test_obc_watchdog_kick_resets_timer(
    obc: ObcEquipment
) -> None:
    """Kicking watchdog after warning resets to nominal."""
    for i in range(12):
        obc.do_step(t=float(i), dt=1.0)
    assert obc.watchdog_status == WDG_WARNING

    obc.receive("dhs.obc.watchdog_kick", 1.0)
    obc.do_step(t=12.0, dt=1.0)
    assert obc.watchdog_status == 0  # WDG_NOMINAL


# ── Memory management ─────────────────────────────────────────────────────────

@pytest.mark.requirement("SVF-DEV-038")
def test_obc_memory_fills_over_time(obc: ObcEquipment) -> None:
    """Memory used percentage increases each tick."""
    obc.do_step(t=0.0, dt=100.0)
    assert obc.memory_used_pct > 0.0


@pytest.mark.requirement("SVF-DEV-038")
def test_obc_memory_dump_clears_memory(obc: ObcEquipment) -> None:
    """Memory dump command clears memory."""
    obc.do_step(t=0.0, dt=100.0)
    assert obc.memory_used_pct > 0.0

    obc.receive("dhs.obc.memory_dump_cmd", 1.0)
    obc.do_step(t=100.0, dt=1.0)
    assert obc.memory_used_pct == pytest.approx(0.0)


@pytest.mark.requirement("SVF-DEV-038")
def test_obc_memory_fills_faster_in_payload_mode(
    sync: _NoSync, store: ParameterStore, cmd_store: CommandStore
) -> None:
    """Memory fills faster in PAYLOAD mode than SAFE mode."""
    config = ObcConfig(
        apid=0x101,
        watchdog_period_s=99999.0,  # effectively disable watchdog
        initial_mode=MODE_SAFE,
    )
    obc = ObcEquipment(config, sync, store, cmd_store)
    obc.initialise(start_time=0.0)

    # SAFE mode fill
    obc.do_step(t=0.0, dt=100.0)
    safe_fill = obc.memory_used_pct

    # Reset memory and switch to PAYLOAD
    obc.receive("dhs.obc.memory_dump_cmd", 1.0)
    obc.do_step(t=100.0, dt=1.0)
    obc.receive("dhs.obc.mode_cmd", float(MODE_PAYLOAD))
    obc.do_step(t=101.0, dt=100.0)
    payload_fill = obc.memory_used_pct

    assert payload_fill > safe_fill
