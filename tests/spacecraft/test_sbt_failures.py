"""
SVF S-Band Transponder Failure Test Procedures
Exercises SBT failure modes and boundary conditions.

TC-SBT-FAIL-001: Signal loss — carrier lock drops mid-pass
TC-SBT-FAIL-002: Weak signal — lock not acquired below threshold
TC-SBT-FAIL-003: Power cycle — lock re-acquired after power on
TC-SBT-FAIL-004: No RX bitrate without lock
TC-SBT-FAIL-005: No TX when not in TM_TX mode
TC-SBT-FAIL-006: All outputs zero when unpowered

Implements: SBT-001 through SBT-006
"""

import pytest
from svf.abstractions import SyncProtocol
from svf.parameter_store import ParameterStore
from svf.command_store import CommandStore
from svf.models.ttc.sbt import (
    make_sbt, LOCK_THRESHOLD_DBM, LOCK_TIME_S,
    TC_BITRATE_BPS, TM_BITRATE_BPS,
    MODE_IDLE, MODE_TC_RX, MODE_TM_TX,
)
from svf.native_equipment import NativeEquipment


class _NoSync(SyncProtocol):
    def reset(self) -> None: pass
    def publish_ready(self, model_id: str, t: float) -> None: pass
    def wait_for_ready(self, expected: list[str], timeout: float) -> bool:
        return True


@pytest.fixture
def sbt() -> NativeEquipment:
    eq = make_sbt(_NoSync(), ParameterStore(), CommandStore())
    eq.initialise()
    return eq


def power_on_and_lock(sbt: NativeEquipment) -> None:
    """Power on SBT and acquire carrier lock."""
    sbt.receive("ttc.sbt.power_enable", 1.0)
    sbt.receive("ttc.sbt.uplink_signal_level", LOCK_THRESHOLD_DBM + 20.0)
    sbt.receive("ttc.sbt.mode_cmd", float(MODE_TC_RX))
    for i in range(int(LOCK_TIME_S) + 2):
        sbt.do_step(t=float(i), dt=1.0)
    assert sbt.read_port("ttc.sbt.uplink_lock") == pytest.approx(1.0)


@pytest.mark.requirement("SBT-003")
def test_tc_sbt_fail_001_signal_loss_drops_lock(
    sbt: NativeEquipment,
) -> None:
    """
    TC-SBT-FAIL-001: Carrier lock lost when signal drops below threshold.
    RX bitrate drops to zero immediately.
    """
    power_on_and_lock(sbt)
    assert sbt.read_port("ttc.sbt.uplink_lock") == pytest.approx(1.0)
    assert sbt.read_port("ttc.sbt.rx_bitrate") == pytest.approx(TC_BITRATE_BPS)

    # Signal drops
    sbt.receive("ttc.sbt.uplink_signal_level", LOCK_THRESHOLD_DBM - 10.0)
    sbt.do_step(t=float(LOCK_TIME_S) + 3, dt=1.0)

    assert sbt.read_port("ttc.sbt.uplink_lock") == pytest.approx(0.0)
    assert sbt.read_port("ttc.sbt.rx_bitrate") == pytest.approx(0.0)


@pytest.mark.requirement("SBT-002")
def test_tc_sbt_fail_002_weak_signal_no_lock(
    sbt: NativeEquipment,
) -> None:
    """
    TC-SBT-FAIL-002: No carrier lock when signal below threshold.
    Even after long exposure.
    """
    sbt.receive("ttc.sbt.power_enable", 1.0)
    sbt.receive("ttc.sbt.uplink_signal_level", LOCK_THRESHOLD_DBM - 5.0)
    for i in range(20):
        sbt.do_step(t=float(i), dt=1.0)

    assert sbt.read_port("ttc.sbt.uplink_lock") == pytest.approx(0.0)
    assert sbt.read_port("ttc.sbt.rx_bitrate") == pytest.approx(0.0)


@pytest.mark.requirement("SBT-002")
def test_tc_sbt_fail_003_lock_requires_sustained_signal(
    sbt: NativeEquipment,
) -> None:
    """
    TC-SBT-FAIL-003: Lock not acquired if signal only briefly above threshold.
    Signal must be above threshold for LOCK_TIME_S continuously.
    """
    sbt.receive("ttc.sbt.power_enable", 1.0)
    sbt.receive("ttc.sbt.uplink_signal_level", LOCK_THRESHOLD_DBM + 10.0)
    sbt.do_step(t=0.0, dt=1.0)  # only 1 second — not enough

    sbt.receive("ttc.sbt.uplink_signal_level", LOCK_THRESHOLD_DBM - 10.0)
    sbt.do_step(t=1.0, dt=1.0)  # signal drops — timer resets

    assert sbt.read_port("ttc.sbt.uplink_lock") == pytest.approx(0.0)


@pytest.mark.requirement("SBT-001", "SBT-002")
def test_tc_sbt_fail_004_power_cycle_reacquires_lock(
    sbt: NativeEquipment,
) -> None:
    """
    TC-SBT-FAIL-004: After power cycle lock is re-acquired from scratch.
    """
    power_on_and_lock(sbt)
    assert sbt.read_port("ttc.sbt.uplink_lock") == pytest.approx(1.0)

    # Power off
    sbt.receive("ttc.sbt.power_enable", 0.0)
    sbt.do_step(t=float(LOCK_TIME_S) + 3, dt=1.0)
    assert sbt.read_port("ttc.sbt.uplink_lock") == pytest.approx(0.0)

    # Power on again — must re-acquire
    sbt.receive("ttc.sbt.power_enable", 1.0)
    sbt.receive("ttc.sbt.uplink_signal_level", LOCK_THRESHOLD_DBM + 20.0)
    sbt.receive("ttc.sbt.mode_cmd", float(MODE_TC_RX))
    for i in range(int(LOCK_TIME_S) + 2):
        sbt.do_step(t=float(LOCK_TIME_S) + 4 + float(i), dt=1.0)

    assert sbt.read_port("ttc.sbt.uplink_lock") == pytest.approx(1.0)


@pytest.mark.requirement("SBT-004")
def test_tc_sbt_fail_005_no_rx_without_lock(
    sbt: NativeEquipment,
) -> None:
    """
    TC-SBT-FAIL-005: No RX bitrate when in TC_RX mode but not locked.
    """
    sbt.receive("ttc.sbt.power_enable", 1.0)
    sbt.receive("ttc.sbt.uplink_signal_level", LOCK_THRESHOLD_DBM - 5.0)
    sbt.receive("ttc.sbt.mode_cmd", float(MODE_TC_RX))
    sbt.do_step(t=0.0, dt=1.0)

    assert sbt.read_port("ttc.sbt.uplink_lock") == pytest.approx(0.0)
    assert sbt.read_port("ttc.sbt.rx_bitrate") == pytest.approx(0.0)


@pytest.mark.requirement("SBT-005")
def test_tc_sbt_fail_006_no_tx_in_tc_rx_mode(
    sbt: NativeEquipment,
) -> None:
    """
    TC-SBT-FAIL-006: No TX bitrate when in TC_RX mode.
    """
    power_on_and_lock(sbt)
    # Already in TC_RX mode from power_on_and_lock

    assert sbt.read_port("ttc.sbt.tx_bitrate") == pytest.approx(0.0)
    assert sbt.read_port("ttc.sbt.downlink_active") == pytest.approx(0.0)


@pytest.mark.requirement("SBT-006")
def test_tc_sbt_fail_007_all_outputs_zero_unpowered(
    sbt: NativeEquipment,
) -> None:
    """
    TC-SBT-FAIL-007: All outputs zero when SBT not powered.
    """
    sbt.do_step(t=0.0, dt=1.0)

    assert sbt.read_port("ttc.sbt.uplink_lock") == pytest.approx(0.0)
    assert sbt.read_port("ttc.sbt.downlink_active") == pytest.approx(0.0)
    assert sbt.read_port("ttc.sbt.rx_bitrate") == pytest.approx(0.0)
    assert sbt.read_port("ttc.sbt.tx_bitrate") == pytest.approx(0.0)
    assert sbt.read_port("ttc.sbt.mode") == pytest.approx(MODE_IDLE)
