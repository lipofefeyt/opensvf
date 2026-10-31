"""
L1 tests for OBCEmulatorAdapter TM decoding, using packets captured from
openobsw v0.18 obsw_sim (no PEC, big-endian HK parameters).

Implements: SVF-DEV-205, SVF-DEV-206, SVF-DEV-207
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from svf.models.dhs.obc import MODE_NOMINAL, MODE_SAFE
from svf.models.dhs.obc_emulator import OBCEmulatorAdapter
from svf.stores.parameter_store import ParameterStore

_HDR = "0903c00000162003190000000000000000"   # TM(3,25), data length 22, no PEC


def _set3(mode: int, obt: int) -> bytes:
    """DHS OBC HK set 3: set id, mode, OBT (u32 BE), wd, mem, health, resets (u16), cpu."""
    return bytes.fromhex(_HDR) + bytes([3, mode]) + obt.to_bytes(4, "big") \
        + bytes([0, 12, 1]) + (0).to_bytes(2, "big") + bytes([5])


def _adapter() -> tuple[OBCEmulatorAdapter, ParameterStore]:
    store = ParameterStore()
    return OBCEmulatorAdapter(sim_path=None, sync_protocol=MagicMock(), store=store), store


@pytest.mark.requirement("SVF-DEV-205")
def test_pec_less_hk_packet_reaches_tm_queue() -> None:
    adapter, _ = _adapter()
    adapter._parse_tm(_set3(MODE_SAFE, 7), t=0.0)
    queued = adapter.get_tm_queue()
    assert [(p.service, p.subservice) for p in queued] == [(3, 25)]


@pytest.mark.requirement("SVF-DEV-206")
def test_set3_obt_and_mode_decode_big_endian() -> None:
    """OBT 1000 must read as 1000, not the byte-swapped 3892510720."""
    adapter, store = _adapter()
    adapter._parse_tm(_set3(MODE_NOMINAL, 1000), t=1.0)
    obt, mode = store.read("obc_obt"), store.read("obc_mode")
    assert obt is not None and obt.value == pytest.approx(1000.0)
    assert mode is not None and mode.value == pytest.approx(float(MODE_NOMINAL))


@pytest.mark.requirement("SVF-DEV-207")
@pytest.mark.parametrize("build, svc, sub", [
    (lambda a: a._build_s8_perform(1), 8, 1),
    (lambda a: a._build_s8_perform(2), 8, 1),
    (lambda a: a._build_s17_ping(), 17, 1),
    (lambda a: a._build_s9_set_obt(1000), 9, 128),
])
def test_adapter_tcs_are_valid_pus_c(build, svc, sub) -> None:  # type: ignore[no-untyped-def]
    """Every TC the adapter generates parses as PUS-C with a valid PEC."""
    from svf.pus.tc import PusTcParser
    adapter = OBCEmulatorAdapter(sim_path=None, sync_protocol=MagicMock(),
                                 store=ParameterStore(), apid=0x010)
    pkt = PusTcParser().parse(build(adapter))
    assert (pkt.apid, pkt.service, pkt.subservice) == (0x010, svc, sub)


@pytest.mark.requirement("SVF-DEV-207")
def test_adapter_tc_sequence_count_increments() -> None:
    from svf.pus.tc import PusTcParser
    adapter, _ = _adapter()
    first = PusTcParser().parse(adapter._build_s17_ping()).sequence_count
    second = PusTcParser().parse(adapter._build_s17_ping()).sequence_count
    assert second == (first + 1) % 16384


@pytest.mark.requirement("SVF-DEV-208")
def test_receive_tc_from_another_thread_only_queues() -> None:
    """No pipe I/O on the caller's thread; the TC goes out with the next tick."""
    import threading
    adapter, _ = _adapter()
    written: list[tuple[int, bytes]] = []
    adapter._write_typed_frame = lambda kind, frame: written.append((kind, frame))  # type: ignore[method-assign]
    tc = adapter._build_s17_ping()
    th = threading.Thread(target=adapter.receive_tc, args=(tc,))
    th.start(); th.join()
    assert written == []
    assert adapter._send_tcs(t=0.0) == 1
    assert [f for _, f in written] == [tc]


@pytest.mark.requirement("SVF-DEV-209")
def test_tm_1_2_failure_code_is_decoded() -> None:
    from svf.models.dhs.obc_emulator import S1_FAILURE_CODES
    adapter, store = _adapter()
    raw = bytes.fromhex("0903c00000102001020000000000000000") + bytes.fromhex("1810c0020007")
    adapter._parse_tm(raw, t=2.0)
    code = store.read("svf.tm.1.2.last_code")
    assert code is not None and int(code.value) == 0x0007
    assert S1_FAILURE_CODES[0x0007] == "not allowed in this mode"


@pytest.mark.requirement("SVF-DEV-210")
def test_actuator_controller_byte_is_published() -> None:
    import struct
    from svf.models.dhs.obc_emulator import _ACTUATOR_FMT
    adapter, store = _adapter()
    adapter._parse_actuator(struct.pack(_ACTUATOR_FMT, 0, 0, 0, 1e-3, 0, 0, 1, 5.0))
    ctrl = store.read("svf.obc.actuator_controller")
    assert ctrl is not None and ctrl.value == 1.0


@pytest.mark.requirement("SVF-DEV-210")
def test_published_obt_comes_from_hk_not_adapter_clock() -> None:
    adapter, _ = _adapter()
    assert adapter._obc_obt is None             # nothing reported yet -> 0.0 published
    adapter._parse_tm(_set3(MODE_SAFE, 1234), t=0.3)
    assert adapter._obc_obt == 1234
