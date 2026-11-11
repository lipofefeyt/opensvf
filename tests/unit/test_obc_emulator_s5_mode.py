"""
L1 tests for the mode hint OBCEmulatorAdapter takes from openobsw's
mode-transition events, and for HK set 3 remaining the mode source.

Packets are synthetic TM(5,x) in the openobsw layout (no PEC): 17-byte
header, event ID (u16 BE), auxiliary data.

Implements: SVF-DEV-216
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from svf.models.dhs.obc import MODE_NOMINAL, MODE_SAFE, MODE_STANDBY
from svf.models.dhs.obc_emulator import S5_MODE_EVENTS, OBCEmulatorAdapter
from svf.stores.parameter_store import ParameterStore

_HK_HDR = "0903c00000162003190000000000000000"   # TM(3,25), data length 22


def _event(subservice: int, event_id: int, aux: bytes = b"") -> bytes:
    """TM(5,subservice) as openobsw builds it: event ID (u16 BE) then aux data."""
    app = event_id.to_bytes(2, "big") + aux
    data_len = 11 + len(app) - 1                 # secondary header + app data - 1
    header = bytes([0x09, 0x03, 0xC0, 0x00]) + data_len.to_bytes(2, "big") \
        + bytes([0x20, 5, subservice]) + bytes(8)
    assert len(header) == 17
    return header + app


def _set3(mode: int, obt: int = 100) -> bytes:
    """DHS OBC HK set 3: set id, mode, OBT (u32 BE), wd, mem, health, resets (u16), cpu."""
    return bytes.fromhex(_HK_HDR) + bytes([3, mode]) + obt.to_bytes(4, "big") \
        + bytes([0, 12, 1]) + (0).to_bytes(2, "big") + bytes([5])


def _adapter() -> tuple[OBCEmulatorAdapter, ParameterStore]:
    store = ParameterStore()
    return OBCEmulatorAdapter(sim_path=None, sync_protocol=MagicMock(), store=store), store


@pytest.mark.requirement("SVF-DEV-216")
def test_mapping_is_the_four_openobsw_mode_events() -> None:
    """0x0005 (nominal_entry) and 0x0004 (standby_entry) are what openobsw emits."""
    assert S5_MODE_EVENTS == {
        0x0002: MODE_SAFE,
        0x0003: MODE_NOMINAL,
        0x0004: MODE_STANDBY,
        0x0005: MODE_NOMINAL,
    }


@pytest.mark.requirement("SVF-DEV-216")
@pytest.mark.parametrize("event_id, start, hinted", [
    (0x0002, MODE_NOMINAL, MODE_SAFE),       # safe_mode_entry
    (0x0003, MODE_SAFE,    MODE_NOMINAL),    # safe_mode_exit
    (0x0004, MODE_NOMINAL, MODE_STANDBY),    # standby_entry
    (0x0005, MODE_SAFE,    MODE_NOMINAL),    # nominal_entry
])
@pytest.mark.parametrize("subservice", [1, 2, 3, 4])
def test_mode_event_sets_the_mode_hint(
    event_id: int, start: int, hinted: int, subservice: int,
) -> None:
    """The event ID decides, whatever severity subtype carries it."""
    adapter, _ = _adapter()
    adapter._mode = start
    adapter._parse_tm(_event(subservice, event_id), t=1.0)
    assert adapter._mode == hinted


@pytest.mark.requirement("SVF-DEV-216")
def test_safe_mode_entry_aux_data_does_not_disturb_the_event_id() -> None:
    """safe_mode_entry carries a trigger_source byte after the event ID."""
    adapter, _ = _adapter()
    adapter._mode = MODE_NOMINAL
    adapter._parse_tm(_event(4, 0x0002, aux=bytes([3])), t=1.0)
    assert adapter._mode == MODE_SAFE


@pytest.mark.requirement("SVF-DEV-216")
@pytest.mark.parametrize("event_id", [0x0001, 0x0010, 0x0051, 0x0200, 0x0300, 0x7002])
def test_other_events_leave_the_mode_alone(event_id: int) -> None:
    """boot_complete, a safe trigger such as 0x0051, and S12 events are not mode events."""
    adapter, _ = _adapter()
    adapter._mode = MODE_NOMINAL
    adapter._parse_tm(_event(4, event_id, aux=bytes(4)), t=1.0)
    assert adapter._mode == MODE_NOMINAL


@pytest.mark.requirement("SVF-DEV-216")
def test_event_packet_without_an_event_id_is_ignored() -> None:
    adapter, _ = _adapter()
    adapter._mode = MODE_NOMINAL
    adapter._on_s5(4, _event(4, 0x0002)[:18], t=1.0)     # one byte short
    assert adapter._mode == MODE_NOMINAL


@pytest.mark.requirement("SVF-DEV-216", "SVF-DEV-210")
def test_hk_set3_overrides_a_contradicting_event() -> None:
    """HK set 3 is the mode source: the next report replaces the S5 hint."""
    adapter, _ = _adapter()
    adapter._parse_tm(_set3(MODE_NOMINAL), t=1.0)
    adapter._parse_tm(_event(4, 0x0002), t=1.1)
    assert adapter._mode == MODE_SAFE                    # hint, until HK says otherwise
    adapter._parse_tm(_set3(MODE_NOMINAL), t=2.0)
    assert adapter._mode == MODE_NOMINAL


@pytest.mark.requirement("SVF-DEV-216", "SVF-DEV-214")
def test_event_hint_reaches_neither_obc_mode_nor_the_mode_timeline() -> None:
    """obc_mode and LinkHealth.mode_changes record what HK reported, nothing else."""
    adapter, store = _adapter()
    adapter._parse_tm(_set3(MODE_NOMINAL), t=1.0)
    adapter._parse_tm(_event(4, 0x0002), t=1.1)
    adapter._parse_tm(_event(1, 0x0004), t=1.2)
    obc_mode = store.read("obc_mode")
    assert obc_mode is not None and obc_mode.value == float(MODE_NOMINAL)
    assert adapter.link_health().mode_changes == [(1.0, MODE_NOMINAL)]
    adapter._parse_tm(_set3(MODE_SAFE), t=2.0)
    assert adapter.link_health().mode_changes == [(1.0, MODE_NOMINAL), (2.0, MODE_SAFE)]
