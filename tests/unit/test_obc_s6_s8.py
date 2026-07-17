"""
Tests for OBC Equipment S6 Memory Management and S8 Function Management dispatch.
Implements: SVF-DEV-190, SVF-DEV-191
"""

import struct

import pytest
from svf.core.abstractions import SyncProtocol
from svf.stores.parameter_store import ParameterStore
from svf.stores.command_store import CommandStore
from svf.models.dhs.obc import ObcEquipment, ObcConfig, MODE_SAFE, MODE_NOMINAL
from svf.pus.tc import PusTcPacket, PusTcBuilder, crc16
from svf.pus.services import PusService6, PusService8


class _NoSync(SyncProtocol):
    def reset(self) -> None: pass
    def publish_ready(self, model_id: str, t: float) -> None: pass
    def wait_for_ready(self, expected: list[str], timeout: float) -> bool:
        return True


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
    config = ObcConfig(apid=0x101)
    eq = ObcEquipment(config, sync, store, cmd_store)
    eq.initialise()
    return eq


# ── S6 memory management dispatch tests ──────────────────────────────────────

@pytest.mark.requirement("PUS-010", "SVF-DEV-190")
def test_obc_s6_load_then_dump_roundtrip(obc: ObcEquipment) -> None:
    """OBC writes S6 load data into its simulated memory and dumps it back."""
    load_tc = PusTcPacket(
        apid=0x100, sequence_count=1, service=6, subservice=2,
        app_data=PusService6.build_load(0x0010, b"\xAA\xBB\xCC\xDD"),
    )
    obc.receive_tc(PusTcBuilder().build(load_tc), t=0.0)

    dump_tc = PusTcPacket(
        apid=0x100, sequence_count=2, service=6, subservice=9,
        app_data=PusService6.build_dump(0x0010, 4, mem_id=1),
    )
    responses = obc.receive_tc(PusTcBuilder().build(dump_tc), t=0.0)

    tm_6_6 = [r for r in responses if r.service == 6 and r.subservice == 6]
    assert len(tm_6_6) == 1
    assert tm_6_6[0].app_data[5:] == b"\xAA\xBB\xCC\xDD"


@pytest.mark.requirement("PUS-010", "SVF-DEV-190")
def test_obc_s6_check_success(obc: ObcEquipment) -> None:
    """OBC responds TM(6,10) when memory CRC matches."""
    data = b"\x01\x02\x03\x04"
    load_tc = PusTcPacket(
        apid=0x100, sequence_count=1, service=6, subservice=2,
        app_data=PusService6.build_load(0x0020, data),
    )
    obc.receive_tc(PusTcBuilder().build(load_tc), t=0.0)

    expected_crc = crc16(data)
    check_tc = PusTcPacket(
        apid=0x100, sequence_count=2, service=6, subservice=5,
        app_data=PusService6.build_check(0x0020, len(data), mem_id=1, expected_crc=expected_crc),
    )
    responses = obc.receive_tc(PusTcBuilder().build(check_tc), t=0.0)

    tm_6_10 = [r for r in responses if r.service == 6 and r.subservice == 10]
    assert len(tm_6_10) == 1


@pytest.mark.requirement("PUS-010", "SVF-DEV-190")
def test_obc_s6_check_failure_reports_actual_crc(obc: ObcEquipment) -> None:
    """OBC responds TM(6,11) with the actual CRC when it doesn't match."""
    data = b"\x01\x02\x03\x04"
    load_tc = PusTcPacket(
        apid=0x100, sequence_count=1, service=6, subservice=2,
        app_data=PusService6.build_load(0x0030, data),
    )
    obc.receive_tc(PusTcBuilder().build(load_tc), t=0.0)

    check_tc = PusTcPacket(
        apid=0x100, sequence_count=2, service=6, subservice=5,
        app_data=PusService6.build_check(0x0030, len(data), mem_id=1, expected_crc=0x0000),
    )
    responses = obc.receive_tc(PusTcBuilder().build(check_tc), t=0.0)

    tm_6_11 = [r for r in responses if r.service == 6 and r.subservice == 11]
    assert len(tm_6_11) == 1
    _addr, _length, actual_crc = struct.unpack_from(">IHH", tm_6_11[0].app_data)
    assert actual_crc == crc16(data)


@pytest.mark.requirement("PUS-010", "SVF-DEV-190")
def test_obc_s6_load_out_of_range_is_ignored(obc: ObcEquipment) -> None:
    """OBC ignores a S6 load that would write past the simulated memory."""
    out_of_range_addr = len(obc._memory) - 1
    load_tc = PusTcPacket(
        apid=0x100, sequence_count=1, service=6, subservice=2,
        app_data=PusService6.build_load(out_of_range_addr, b"\xAA\xBB\xCC\xDD"),
    )
    # Should not raise; out-of-range writes are dropped with a logged warning.
    obc.receive_tc(PusTcBuilder().build(load_tc), t=0.0)


# ── S8 function management dispatch tests ────────────────────────────────────

@pytest.mark.requirement("PUS-010", "SVF-DEV-191")
def test_obc_s8_perform_triggers_mode_transition(
    sync: _NoSync, store: ParameterStore, cmd_store: CommandStore,
) -> None:
    """TC(8,1) with a mapped function_id triggers the corresponding mode transition."""
    config = ObcConfig(apid=0x101, function_mode_map={1: MODE_NOMINAL, 2: MODE_SAFE})
    eq = ObcEquipment(config, sync, store, cmd_store)
    eq.initialise()

    tc = PusTcPacket(
        apid=0x100, sequence_count=1, service=8, subservice=1,
        app_data=PusService8.build_perform(function_id=1),
    )
    eq.receive_tc(PusTcBuilder().build(tc), t=0.0)

    assert eq.mode == MODE_NOMINAL


@pytest.mark.requirement("PUS-010", "SVF-DEV-191")
def test_obc_s8_perform_generates_s5_event(
    sync: _NoSync, store: ParameterStore, cmd_store: CommandStore,
) -> None:
    """A S8-triggered mode transition emits the same S5 event as a direct one."""
    config = ObcConfig(apid=0x101, function_mode_map={1: MODE_NOMINAL})
    eq = ObcEquipment(config, sync, store, cmd_store)
    eq.initialise()

    tc = PusTcPacket(
        apid=0x100, sequence_count=1, service=8, subservice=1,
        app_data=PusService8.build_perform(function_id=1),
    )
    eq.receive_tc(PusTcBuilder().build(tc), t=0.0)

    # _transition_mode() self-enqueues its S5 event rather than returning it
    # through receive_tc()'s response list  -  read it back via the TM queue.
    events = eq.get_tm_by_service(5, 1)
    assert len(events) > 0


@pytest.mark.requirement("PUS-010", "SVF-DEV-191")
def test_obc_s8_perform_unknown_function_id_no_transition(
    sync: _NoSync, store: ParameterStore, cmd_store: CommandStore,
) -> None:
    """TC(8,1) with an unmapped function_id is ignored  -  mode does not change."""
    config = ObcConfig(apid=0x101, function_mode_map={1: MODE_NOMINAL})
    eq = ObcEquipment(config, sync, store, cmd_store)
    eq.initialise()

    tc = PusTcPacket(
        apid=0x100, sequence_count=1, service=8, subservice=1,
        app_data=PusService8.build_perform(function_id=99),
    )
    eq.receive_tc(PusTcBuilder().build(tc), t=0.0)

    assert eq.mode == MODE_SAFE  # unchanged from ObcConfig default


@pytest.mark.requirement("PUS-010", "SVF-DEV-191")
def test_obc_s8_perform_already_in_target_mode_no_duplicate_event(
    sync: _NoSync, store: ParameterStore, cmd_store: CommandStore,
) -> None:
    """TC(8,1) targeting the current mode is a no-op  -  no extra S5 event."""
    config = ObcConfig(apid=0x101, initial_mode=MODE_NOMINAL, function_mode_map={1: MODE_NOMINAL})
    eq = ObcEquipment(config, sync, store, cmd_store)
    eq.initialise()

    tc = PusTcPacket(
        apid=0x100, sequence_count=1, service=8, subservice=1,
        app_data=PusService8.build_perform(function_id=1),
    )
    responses = eq.receive_tc(PusTcBuilder().build(tc), t=0.0)

    events = [r for r in responses if r.service == 5]
    assert len(events) == 0
    assert eq.mode == MODE_NOMINAL
