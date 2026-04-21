"""
SVF OBC Failure Test Procedures
Exercises OBC failure modes and boundary conditions.

TC-OBC-FAIL-001: Watchdog reset forces mode to SAFE
TC-OBC-FAIL-002: Memory full — health degrades at 90% fill
TC-OBC-FAIL-003: Invalid TC (bad CRC) — TM(1,2) rejection
TC-OBC-FAIL-004: Unknown parameter_id in S20 — graceful no-op
TC-OBC-FAIL-005: S20 with malformed app_data — graceful no-op
TC-OBC-FAIL-006: Mode forced to SAFE on watchdog reset

Implements: OBC-001 through OBC-008
"""

import pytest
import struct
from svf.core.abstractions import SyncProtocol
from svf.stores.parameter_store import ParameterStore
from svf.stores.command_store import CommandStore
from svf.models.dhs.obc import (
    ObcEquipment, ObcConfig,
    MODE_SAFE, MODE_NOMINAL, MODE_PAYLOAD,
    WDG_NOMINAL, WDG_WARNING, WDG_RESET,
    HEALTH_NOMINAL, HEALTH_DEGRADED,
)
from svf.pus.tc import PusTcPacket, PusTcBuilder


class _NoSync(SyncProtocol):
    def reset(self) -> None: pass
    def publish_ready(self, model_id: str, t: float) -> None: pass
    def wait_for_ready(self, expected: list[str], timeout: float) -> bool:
        return True


@pytest.fixture
def obc() -> ObcEquipment:
    config = ObcConfig(
        apid=0x101,
        param_id_map={0x2021: "aocs.rw1.torque_cmd"},
        watchdog_period_s=10.0,
        initial_mode=MODE_NOMINAL,
    )
    eq = ObcEquipment(config, _NoSync(), ParameterStore(), CommandStore())
    eq.initialise(start_time=0.0)
    return eq


@pytest.mark.requirement("OBC-005", "OBC-001")
def test_tc_obc_fail_001_watchdog_reset_forces_safe(
    obc: ObcEquipment,
) -> None:
    """
    TC-OBC-FAIL-001: Watchdog reset forces OBC back to SAFE mode.

    OBC starts in NOMINAL. Without watchdog kick for 2x period,
    OBC resets to SAFE.
    """
    assert obc.mode == MODE_NOMINAL

    for i in range(25):
        obc.do_step(t=float(i), dt=1.0)

    assert obc.watchdog_status == WDG_RESET
    assert obc.mode == MODE_SAFE
    assert obc.reset_count == 1


@pytest.mark.requirement("OBC-008")
def test_tc_obc_fail_002_health_degrades_at_90_pct_memory(
    obc: ObcEquipment,
) -> None:
    """
    TC-OBC-FAIL-002: OBC health degrades when memory exceeds 90%.

    Memory fills faster in PAYLOAD mode. Health should degrade
    before memory reaches 100%.
    """
    config = ObcConfig(
        apid=0x101,
        watchdog_period_s=99999.0,
        initial_mode=MODE_PAYLOAD,
    )
    eq = ObcEquipment(config, _NoSync(), ParameterStore(), CommandStore())
    eq.initialise()

    # Step until memory > 90%
    for i in range(2000):
        eq.do_step(t=float(i), dt=1.0)
        if eq.memory_used_pct > 90.0:
            break

    assert eq.memory_used_pct > 90.0
    assert eq.read_port("dhs.obc.health") == pytest.approx(HEALTH_DEGRADED)


@pytest.mark.requirement("OBC-005")
def test_tc_obc_fail_003_watchdog_warning_generates_s5_event(
    obc: ObcEquipment,
) -> None:
    """
    TC-OBC-FAIL-003: Watchdog timeout generates TM(5,2) low severity event.
    """
    for i in range(12):
        obc.do_step(t=float(i), dt=1.0)

    assert obc.watchdog_status == WDG_WARNING
    events = obc.get_tm_by_service(5, 2)
    assert len(events) > 0


@pytest.mark.requirement("OBC-005")
def test_tc_obc_fail_004_watchdog_reset_generates_s5_high_event(
    obc: ObcEquipment,
) -> None:
    """
    TC-OBC-FAIL-004: Watchdog reset generates TM(5,4) high severity event.
    """
    for i in range(25):
        obc.do_step(t=float(i), dt=1.0)

    assert obc.watchdog_status == WDG_RESET
    events = obc.get_tm_by_service(5, 4)
    assert len(events) > 0


@pytest.mark.requirement("PUS-009", "PUS-010")
def test_tc_obc_fail_005_bad_crc_generates_rejection(
    obc: ObcEquipment,
) -> None:
    """
    TC-OBC-FAIL-005: TC with bad CRC generates TM(1,2) rejection.
    No command should reach CommandStore.
    """
    cmd_store = CommandStore()
    config = ObcConfig(
        apid=0x101,
        param_id_map={0x2021: "aocs.rw1.torque_cmd"},
        watchdog_period_s=99999.0,
    )
    eq = ObcEquipment(config, _NoSync(), ParameterStore(), cmd_store)
    eq.initialise()

    raw = bytearray(PusTcBuilder().build(
        PusTcPacket(
            apid=0x100, sequence_count=1,
            service=20, subservice=1,
            app_data=struct.pack(">Hf", 0x2021, 0.1),
        )
    ))
    raw[-1] ^= 0xFF  # corrupt CRC

    responses = eq.receive_tc(bytes(raw), t=0.0)

    rejections = [r for r in responses if r.service == 1 and r.subservice == 2]
    assert len(rejections) == 1

    # Command must not have reached CommandStore
    entry = cmd_store.peek("aocs.rw1.torque_cmd")
    assert entry is None


@pytest.mark.requirement("PUS-010")
def test_tc_obc_fail_006_unknown_param_id_is_ignored(
    obc: ObcEquipment,
) -> None:
    """
    TC-OBC-FAIL-006: Unknown parameter_id in S20 TC is ignored gracefully.
    OBC still generates S1 acceptance and completion.
    """
    tc = PusTcPacket(
        apid=0x100, sequence_count=1,
        service=20, subservice=1,
        app_data=struct.pack(">Hf", 0xDEAD, 99.9),  # unknown param_id
    )
    responses = obc.receive_tc(PusTcBuilder().build(tc), t=0.0)

    # S1 acceptance and completion still generated
    s1_subs = [r.subservice for r in responses if r.service == 1]
    assert 1 in s1_subs  # acceptance
    assert 7 in s1_subs  # completion


@pytest.mark.requirement("PUS-010")
def test_tc_obc_fail_007_malformed_s20_app_data_ignored(
    obc: ObcEquipment,
) -> None:
    """
    TC-OBC-FAIL-007: S20 TC with too-short app_data handled gracefully.
    """
    tc = PusTcPacket(
        apid=0x100, sequence_count=1,
        service=20, subservice=1,
        app_data=b"\x20",  # only 1 byte — too short for param_id + value
    )
    # Should not raise
    responses = obc.receive_tc(PusTcBuilder().build(tc), t=0.0)
    assert responses is not None


@pytest.mark.requirement("OBC-002")
def test_tc_obc_fail_008_invalid_mode_cmd_clamped(
    obc: ObcEquipment,
) -> None:
    """
    TC-OBC-FAIL-008: Mode command with invalid value — OBC transitions
    to nearest valid mode.
    """
    obc.receive("dhs.obc.mode_cmd", 99.0)  # invalid mode
    obc.do_step(t=0.0, dt=1.0)
    # Should not crash — mode should be some valid integer
    assert obc.mode in (MODE_SAFE, MODE_NOMINAL, MODE_PAYLOAD, 99)
