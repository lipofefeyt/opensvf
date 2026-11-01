"""
svf console command handling and TM decoding, without a binary (M76).

Implements: SVF-DEV-215
"""
from __future__ import annotations

import struct
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from svf.console import ConsoleError, SvfConsole
from svf.models.dhs.obc import MODE_NOMINAL
from svf.models.dhs.obc_emulator import OBCEmulatorAdapter
from svf.pus.tc import PusTcParser
from svf.pus.tm import PusTmPacket
from svf.stores.command_store import CommandStore
from svf.stores.parameter_store import ParameterStore


def _console() -> tuple[SvfConsole, OBCEmulatorAdapter, CommandStore, list[str]]:
    store, cmd = ParameterStore(), CommandStore()
    adapter = OBCEmulatorAdapter(sim_path=None, sync_protocol=MagicMock(), store=store)
    master = SimpleNamespace(_models=[adapter], _param_store=store, _command_store=cmd)
    lines: list[str] = []
    console = SvfConsole(master, out=lines.append)  # type: ignore[arg-type]
    return console, adapter, cmd, lines


def _tm(svc: int, sub: int, data: bytes) -> PusTmPacket:
    return PusTmPacket(apid=0x103, sequence_count=0, service=svc, subservice=sub,
                       app_data=data)


def _queued(adapter: OBCEmulatorAdapter) -> list[tuple[int, int, bytes]]:
    return [(p.service, p.subservice, p.app_data)
            for p in (PusTcParser().parse(raw) for raw in adapter._tc_queue)]


@pytest.mark.requirement("SVF-DEV-215")
def test_param_set_sends_tc20_1_with_be_float() -> None:
    console, adapter, _, _ = _console()
    console.execute("param set 0x20A0 20000")
    assert _queued(adapter) == [(20, 1, struct.pack(">Hf", 0x20A0, 20000.0))]


@pytest.mark.requirement("SVF-DEV-215")
def test_rejection_is_named_and_tied_to_the_sent_tc() -> None:
    console, adapter, _, _ = _console()
    seq = console.send_tc(20, 1, b"\x20\xa0\x46\x9c\x40\x00")
    request_id = (0x1810 << 16) | (0xC000 | seq)
    line = console.describe_tm(_tm(1, 2, struct.pack(">IH", request_id, 0x0007)))
    assert line == f"TM(1,2) TC(20,1) #{seq} rejected: 0x0007 not allowed in this mode"


@pytest.mark.requirement("SVF-DEV-215")
def test_tc_not_sent_by_the_console_is_labelled_as_adapter() -> None:
    console, _, _, _ = _console()
    line = console.describe_tm(_tm(1, 1, struct.pack(">I", 0x1810C063)))
    assert line == "TM(1,1) TC #99 (sent by the adapter) accepted"


@pytest.mark.requirement("SVF-DEV-215")
@pytest.mark.parametrize("svc, sub, data, expected", [
    (3, 25, bytes([3, 2]) + (1000).to_bytes(4, "big") + bytes([0, 12, 0, 0, 0, 5]),
     "TM(3,25) HK set 3: mode=NOMINAL obt=1000s health=0 resets=0 cpu=5% mem=12%"),
    (3, 25, bytes([4]) + struct.pack(">fff", 1e4, 0.5, 0.1),
     "TM(3,25) HK set 4: bdot_gain=10000 adcs_kp=0.5 adcs_kd=0.1"),
    (5, 2, struct.pack(">Hf", 0x7002, 1e4), "TM(5,2) event 0x7002 (low) value=10000"),
    (17, 2, b"", "TM(17,2) pong"),
    (20, 2, struct.pack(">Hf", 0x20A0, 2e4), "TM(20,2) param 0x20A0 = 20000"),
])
def test_describe_tm(svc: int, sub: int, data: bytes, expected: str) -> None:
    console, _, _, _ = _console()
    assert console.describe_tm(_tm(svc, sub, data)) == expected


@pytest.mark.requirement("SVF-DEV-215")
def test_mode_command_goes_through_the_command_store() -> None:
    console, _, cmd, _ = _console()
    console.execute("mode nominal")
    entry = cmd.peek("dhs.obc.mode_cmd")
    assert entry is not None and entry.value == float(MODE_NOMINAL)


@pytest.mark.requirement("SVF-DEV-215")
@pytest.mark.parametrize("line", ["frobnicate", "mode sideways", "param set 0x20A0",
                                  "tc 17", "tc 17 1 zz", "expect 17"])
def test_bad_commands_raise_console_error(line: str) -> None:
    console, _, _, _ = _console()
    with pytest.raises(ConsoleError):
        console.execute(line)


@pytest.mark.requirement("SVF-DEV-215")
def test_comments_and_blank_lines_are_ignored_and_quit_stops() -> None:
    console, adapter, _, _ = _console()
    assert console.execute("   # just a comment") is True
    assert console.execute("") is True
    assert console.execute("quit") is False
    assert adapter._tc_queue == []
