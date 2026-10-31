"""
L3 alignment tests against the real openobsw obsw_sim (v0.18 or later).

Each test drives OBCEmulatorAdapter directly and inspects the parsed TM
queue, so it exercises the same decoding path campaigns and the TTC model
use. Covers:

- TM without Packet Error Control is parsed (SVF-DEV-205)
- HK TM(3,25) byte order: OBT in seconds, TC(9,128) sets it, AOCS floats
  match their S20 values (SVF-DEV-206, opensvf#192)

Run:
    pytest tests/system/test_obsw_alignment.py -v
"""

from __future__ import annotations

import os
import struct
from pathlib import Path
from typing import Iterator
from unittest.mock import MagicMock

import pytest

from svf.models.dhs.obc_emulator import OBCEmulatorAdapter
from svf.pus.tc import PusTcBuilder, PusTcPacket
from svf.pus.tm import PusTmPacket
from svf.stores.parameter_store import ParameterStore

_repo = Path(__file__).parent.parent.parent
_candidates = [
    Path(p) for p in (os.environ.get("OBSW_SIM"),) if p
] + [
    _repo / "bin" / "obsw_sim",
    _repo.parent / "openobsw" / "build" / "sim" / "obsw_sim",
]
OBSW_SIM = next((p for p in _candidates if p.exists()), _candidates[0])

pytestmark = pytest.mark.skipif(
    not OBSW_SIM.exists(), reason=f"obsw_sim not found at {OBSW_SIM}"
)

DT = 0.1
BDOT_GAIN_PARAM = 0x20A0


class ObswHarness:
    """Thin driver around OBCEmulatorAdapter for tick-level L3 tests."""

    def __init__(self) -> None:
        self.adapter = OBCEmulatorAdapter(
            sim_path=OBSW_SIM, sync_protocol=MagicMock(),
            store=ParameterStore(), sync_timeout=5.0,
        )
        self.t = 0.0
        self._seq = 0
        self.tm: list[PusTmPacket] = []

    def tc(self, service: int, subservice: int, data: bytes = b"") -> int:
        """Send a TC; returns its packet sequence count."""
        self._seq += 1
        self.adapter.receive_tc(PusTcBuilder().build(PusTcPacket(
            apid=0x010, sequence_count=self._seq,
            service=service, subservice=subservice, app_data=data,
        )))
        self.tm.extend(self.adapter.get_tm_queue())
        return self._seq

    def run(self, ticks: int) -> None:
        for _ in range(ticks):
            self.adapter.do_step(t=self.t, dt=DT)
            self.t = round(self.t + DT, 6)
        self.tm.extend(self.adapter.get_tm_queue())

    def take(self) -> list[PusTmPacket]:
        out, self.tm = self.tm, []
        return out

    @staticmethod
    def hk(packets: list[PusTmPacket], set_id: int) -> list[bytes]:
        return [p.app_data for p in packets
                if (p.service, p.subservice) == (3, 25)
                and p.app_data and p.app_data[0] == set_id]


@pytest.fixture
def obsw() -> Iterator[ObswHarness]:
    h = ObswHarness()
    h.adapter.initialise()
    try:
        yield h
    finally:
        h.adapter.teardown()


def _obt_values(packets: list[PusTmPacket]) -> list[int]:
    """obc_obt from DHS OBC HK (set 3): u8 set id, u8 mode, u32 OBT, ..."""
    return [struct.unpack_from(">I", d, 2)[0] for d in ObswHarness.hk(packets, 3)]


@pytest.mark.requirement("SVF-DEV-205")
def test_adapter_queues_parsed_obsw_tm(obsw: ObswHarness) -> None:
    """obsw_sim TM has no PEC; the adapter must still parse and queue it."""
    obsw.run(25)
    packets = obsw.take()
    assert any((p.service, p.subservice) == (3, 25) for p in packets), \
        "no parsed TM(3,25) from obsw_sim: TM parsing is dropping packets"


@pytest.mark.requirement("SVF-DEV-206")
def test_hk_obt_counts_seconds_since_boot(obsw: ObswHarness) -> None:
    """Byte-swapped OBT reads as ~1e9; big-endian reads as elapsed seconds."""
    obsw.run(50)                                   # 5.0 s of sim time
    obts = _obt_values(obsw.take())
    assert len(obts) >= 3, f"too few set 3 reports: {obts}"
    assert obts == sorted(obts), f"OBT not monotonic: {obts}"
    assert obts[-1] <= obsw.t + 1, f"OBT {obts[-1]} ahead of {obsw.t} s"
    assert obts[-1] >= obsw.t - 2, f"OBT {obts[-1]} behind {obsw.t} s"


@pytest.mark.requirement("SVF-DEV-206")
def test_hk_obt_follows_tc9_128(obsw: ObswHarness) -> None:
    """After TC(9,128) sets OBT, set 3 reports it plus elapsed seconds."""
    obsw.run(15)
    obsw.take()
    t_set = obsw.t
    obsw.tc(9, 128, struct.pack(">I", 1000))
    obsw.run(30)
    obts = _obt_values(obsw.take())
    assert obts, "no set 3 report after TC(9,128)"
    elapsed = obsw.t - t_set
    assert all(1000 <= v <= 1000 + elapsed + 1 for v in obts), \
        f"OBT {obts} not within [1000, {1000 + elapsed + 1:.0f}]"


@pytest.mark.requirement("SVF-DEV-206")
def test_hk_bdot_gain_matches_s20_value(obsw: ObswHarness) -> None:
    """AOCS HK (set 4) bdot_gain equals TM(20,2): catches double swapping."""
    obsw.run(15)
    obsw.take()
    obsw.tc(20, 3, struct.pack(">H", BDOT_GAIN_PARAM))   # allowed in SAFE
    obsw.run(12)
    packets = obsw.take()
    reports = [p.app_data for p in packets if (p.service, p.subservice) == (20, 2)]
    assert reports, "no TM(20,2) for bdot_gain"
    param, s20_value = struct.unpack_from(">Hf", reports[-1], 0)
    assert param == BDOT_GAIN_PARAM
    hk4 = ObswHarness.hk(packets, 4)
    assert hk4, "no AOCS HK (set 4) report"
    hk_gain = struct.unpack_from(">f", hk4[-1], 1)[0]
    assert hk_gain == pytest.approx(s20_value)
    assert 1.0 < hk_gain < 1.0e7, f"implausible bdot_gain {hk_gain}"


@pytest.mark.requirement("SVF-DEV-034", "SVF-DEV-206")
def test_hk_mode_decodes_openobsw_encoding(obsw: ObswHarness) -> None:
    """Mode decoded from set 3 (not the adapter's initial value) follows obsw_sim."""
    from svf.models.dhs.obc import MODE_NOMINAL, MODE_SAFE
    store = obsw.adapter._store
    assert store is not None
    obsw.run(15)
    boot = store.read("obc_mode")
    assert boot is not None and boot.value == float(MODE_SAFE)
    obsw.adapter.receive("dhs.obc.mode_cmd", float(MODE_NOMINAL))
    obsw.run(15)
    after = store.read("obc_mode")
    assert after is not None and after.value == float(MODE_NOMINAL)
