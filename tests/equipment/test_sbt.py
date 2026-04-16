"""
Tests for S-Band Transponder model.
Carrier lock, mode transitions, bit rates.
Implements: SVF-DEV-038
"""

import pytest
from svf.abstractions import SyncProtocol
from svf.parameter_store import ParameterStore
from svf.command_store import CommandStore
from svf.models.ttc.sbt import (
    make_sbt, LOCK_THRESHOLD_DBM, LOCK_TIME_S,
    TC_BITRATE_BPS, TM_BITRATE_BPS,
    MODE_IDLE, MODE_RANGING, MODE_TC_RX, MODE_TM_TX,
)
from svf.native_equipment import NativeEquipment


class _NoSync(SyncProtocol):
    def reset(self) -> None: pass
    def publish_ready(self, model_id: str, t: float) -> None: pass
    def wait_for_ready(self, expected: list[str], timeout: float) -> bool:
        return True


@pytest.fixture
def sbt() -> NativeEquipment:
    sync  = _NoSync()
    store = ParameterStore()
    cmd   = CommandStore()
    eq = make_sbt(sync, store, cmd)
    eq.initialise()
    return eq


def power_on(sbt: NativeEquipment, signal: float = -90.0) -> None:
    sbt.receive("ttc.sbt.power_enable", 1.0)
    sbt.receive("ttc.sbt.uplink_signal_level", signal)


# ── Power ─────────────────────────────────────────────────────────────────────

@pytest.mark.requirement("SVF-DEV-038")
def test_sbt_idle_when_unpowered(sbt: NativeEquipment) -> None:
    """SBT outputs zeros when unpowered."""
    sbt.do_step(t=0.0, dt=1.0)
    assert sbt.read_port("ttc.sbt.uplink_lock")    == pytest.approx(0.0)
    assert sbt.read_port("ttc.sbt.downlink_active") == pytest.approx(0.0)
    assert sbt.read_port("ttc.sbt.rx_bitrate")     == pytest.approx(0.0)


# ── Carrier lock ──────────────────────────────────────────────────────────────

@pytest.mark.requirement("SVF-DEV-038")
def test_sbt_no_lock_below_threshold(sbt: NativeEquipment) -> None:
    """No carrier lock when signal below threshold."""
    power_on(sbt, signal=LOCK_THRESHOLD_DBM - 5.0)
    for i in range(10):
        sbt.do_step(t=float(i), dt=1.0)
    assert sbt.read_port("ttc.sbt.uplink_lock") == pytest.approx(0.0)


@pytest.mark.requirement("SVF-DEV-038")
def test_sbt_lock_acquired_above_threshold(sbt: NativeEquipment) -> None:
    """Carrier lock acquired after LOCK_TIME_S above threshold."""
    power_on(sbt, signal=LOCK_THRESHOLD_DBM + 10.0)
    for i in range(int(LOCK_TIME_S) + 2):
        sbt.do_step(t=float(i), dt=1.0)
    assert sbt.read_port("ttc.sbt.uplink_lock") == pytest.approx(1.0)


@pytest.mark.requirement("SVF-DEV-038")
def test_sbt_lock_lost_when_signal_drops(sbt: NativeEquipment) -> None:
    """Lock lost immediately when signal drops below threshold."""
    power_on(sbt, signal=LOCK_THRESHOLD_DBM + 10.0)
    for i in range(int(LOCK_TIME_S) + 2):
        sbt.do_step(t=float(i), dt=1.0)
    assert sbt.read_port("ttc.sbt.uplink_lock") == pytest.approx(1.0)

    sbt.receive("ttc.sbt.uplink_signal_level", LOCK_THRESHOLD_DBM - 5.0)
    sbt.do_step(t=float(LOCK_TIME_S) + 2, dt=1.0)
    assert sbt.read_port("ttc.sbt.uplink_lock") == pytest.approx(0.0)


# ── Mode transitions ──────────────────────────────────────────────────────────

@pytest.mark.requirement("SVF-DEV-038")
def test_sbt_mode_transition_to_tc_rx(sbt: NativeEquipment) -> None:
    """SBT transitions to TC_RX mode on command."""
    power_on(sbt)
    sbt.receive("ttc.sbt.mode_cmd", float(MODE_TC_RX))
    sbt.do_step(t=0.0, dt=1.0)
    assert sbt.read_port("ttc.sbt.mode") == pytest.approx(MODE_TC_RX)


@pytest.mark.requirement("SVF-DEV-038")
def test_sbt_mode_transition_to_tm_tx(sbt: NativeEquipment) -> None:
    """SBT transitions to TM_TX mode on command."""
    power_on(sbt)
    sbt.receive("ttc.sbt.mode_cmd", float(MODE_TM_TX))
    sbt.do_step(t=0.0, dt=1.0)
    assert sbt.read_port("ttc.sbt.mode") == pytest.approx(MODE_TM_TX)


# ── Bit rates ─────────────────────────────────────────────────────────────────

@pytest.mark.requirement("SVF-DEV-038")
def test_sbt_rx_bitrate_when_locked_in_tc_rx(sbt: NativeEquipment) -> None:
    """RX bitrate is TC_BITRATE_BPS when locked in TC_RX mode."""
    power_on(sbt, signal=LOCK_THRESHOLD_DBM + 10.0)
    sbt.receive("ttc.sbt.mode_cmd", float(MODE_TC_RX))
    for i in range(int(LOCK_TIME_S) + 2):
        sbt.do_step(t=float(i), dt=1.0)
    assert sbt.read_port("ttc.sbt.rx_bitrate") == pytest.approx(TC_BITRATE_BPS)


@pytest.mark.requirement("SVF-DEV-038")
def test_sbt_tx_bitrate_in_tm_tx_mode(sbt: NativeEquipment) -> None:
    """TX bitrate is TM_BITRATE_BPS in TM_TX mode."""
    power_on(sbt)
    sbt.receive("ttc.sbt.mode_cmd", float(MODE_TM_TX))
    sbt.do_step(t=0.0, dt=1.0)
    assert sbt.read_port("ttc.sbt.tx_bitrate") == pytest.approx(TM_BITRATE_BPS)
    assert sbt.read_port("ttc.sbt.downlink_active") == pytest.approx(1.0)


@pytest.mark.requirement("SVF-DEV-038")
def test_sbt_no_tx_when_not_in_tm_tx(sbt: NativeEquipment) -> None:
    """No TX when not in TM_TX mode."""
    power_on(sbt)
    sbt.receive("ttc.sbt.mode_cmd", float(MODE_TC_RX))
    sbt.do_step(t=0.0, dt=1.0)
    assert sbt.read_port("ttc.sbt.tx_bitrate")     == pytest.approx(0.0)
    assert sbt.read_port("ttc.sbt.downlink_active") == pytest.approx(0.0)
