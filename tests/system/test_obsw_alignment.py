"""
L3 alignment tests against the real openobsw obsw_sim (v0.18 or later).

Each test drives OBCEmulatorAdapter directly and inspects the parsed TM
queue, so it exercises the same decoding path campaigns and the TTC model
use. Covers:

- TM without Packet Error Control is parsed (SVF-DEV-205)
- HK TM(3,25) byte order: OBT in seconds, TC(9,128) sets it, AOCS floats
  match their S20 values (SVF-DEV-206, opensvf#192)
- SAFE TC gate: rejection code 0x0007, accepted once NOMINAL (SVF-DEV-209)
- S11, S12, S19 built with opensvf's codecs behave as openobsw specifies
  (SVF-DEV-211)

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


def _s1_failures(packets: list[PusTmPacket]) -> list[int]:
    """Failure codes from TM(1,2): request id (u32) then code (u16)."""
    return [struct.unpack_from(">H", p.app_data, 4)[0] for p in packets
            if (p.service, p.subservice) == (1, 2) and len(p.app_data) >= 6]


@pytest.mark.requirement("SVF-DEV-209")
def test_safe_gate_rejects_s20_set_until_nominal(obsw: ObswHarness) -> None:
    """TC(20,1) gets TM(1,2) 0x0007 in SAFE and is accepted once NOMINAL."""
    from svf.models.dhs.obc import MODE_NOMINAL
    new_gain = 2.0e4
    set_gain = struct.pack(">Hf", BDOT_GAIN_PARAM, new_gain)

    obsw.run(5)
    obsw.take()
    obsw.tc(20, 1, set_gain)
    obsw.run(3)
    assert _s1_failures(obsw.take()) == [0x0007], "TC(20,1) not rejected in SAFE"

    obsw.adapter.receive("dhs.obc.mode_cmd", float(MODE_NOMINAL))
    obsw.run(5)
    obsw.take()
    obsw.tc(20, 1, set_gain)
    obsw.tc(20, 3, struct.pack(">H", BDOT_GAIN_PARAM))
    obsw.run(3)
    packets = obsw.take()
    assert _s1_failures(packets) == [], "TC(20,1) rejected in NOMINAL"
    reports = [p.app_data for p in packets if (p.service, p.subservice) == (20, 2)]
    assert reports and struct.unpack_from(">f", reports[-1], 2)[0] == pytest.approx(new_gain)


# ── S11, S12, S19 against the flight software (SVF-DEV-211) ─────────────────
# TCs are built with opensvf's own codecs, so these tests prove that what
# opensvf campaigns send is what openobsw v0.18 implements (OBSW-SRS-280..306).


def _ping() -> bytes:
    """A complete TC(17,1) space packet, to embed in S11/S19 definitions."""
    return PusTcBuilder().build(PusTcPacket(apid=0x010, sequence_count=900,
                                            service=17, subservice=1))


def _nominal_at_obt(obsw: ObswHarness, obt: int) -> None:
    """Set OBT with TC(9,128) and command NOMINAL (S11/S12/S19 are gated)."""
    from svf.models.dhs.obc import MODE_NOMINAL
    obsw.run(3)
    obsw.tc(9, 128, struct.pack(">I", obt))
    obsw.adapter.receive("dhs.obc.mode_cmd", float(MODE_NOMINAL))
    obsw.run(12)
    obsw.take()


def _pongs(packets: list[PusTmPacket]) -> int:
    return sum(1 for p in packets if (p.service, p.subservice) == (17, 2))


def _events(packets: list[PusTmPacket], event_id: int) -> list[bytes]:
    return [p.app_data for p in packets
            if p.service == 5 and struct.unpack_from(">H", p.app_data, 0)[0] == event_id]


@pytest.mark.requirement("SVF-DEV-211")
def test_s11_activity_released_at_its_time_tag(obsw: ObswHarness) -> None:
    from svf.pus.services.s11_scheduling import PusService11
    _nominal_at_obt(obsw, 100)
    # Report set 3 every tick so the observed OBT is current, not up to 1 s old.
    obsw.tc(3, 5, struct.pack(">BI", 3, 1))
    obsw.run(2)
    obsw.take()
    obsw.tc(11, 4, PusService11.build_insert(103.0, _ping(), tc_apid=0x010).app_data)
    released_at = None
    for _ in range(60):                       # 6 s, one tick at a time
        obsw.run(1)
        if _pongs(obsw.take()):
            released_at = obsw.adapter._obc_obt
            break
    assert released_at is not None, "scheduled TC(17,1) never released"
    assert 103 <= released_at <= 104, f"released at OBT {released_at}, tag 103"


@pytest.mark.requirement("SVF-DEV-211")
def test_s11_delete_and_nested_rejection(obsw: ObswHarness) -> None:
    from svf.pus.services.s11_scheduling import PusService11
    _nominal_at_obt(obsw, 100)
    nested = PusTcBuilder().build(PusService11.build_insert(200.0, _ping(), tc_apid=0x010))
    obsw.tc(11, 4, PusService11.build_insert(110.0, nested, tc_apid=0x010).app_data)
    obsw.run(3)
    assert _s1_failures(obsw.take()) == [0x0005], "nested S11 TC not rejected"

    obsw.tc(11, 4, PusService11.build_insert(103.0, _ping(), tc_apid=0x010).app_data)
    obsw.tc(11, 5, struct.pack(">H", 1))      # first accepted insert since boot
    obsw.run(50)
    packets = obsw.take()
    assert _s1_failures(packets) == [], "TC(11,5) for request ID 1 rejected"
    assert _pongs(packets) == 0, "deleted activity was still released"


@pytest.mark.requirement("SVF-DEV-211")
def test_s12_event_once_with_value_as_be_float(obsw: ObswHarness) -> None:
    from svf.pus.services.s12_monitoring import PusService12
    _nominal_at_obt(obsw, 100)
    obsw.tc(20, 3, struct.pack(">H", BDOT_GAIN_PARAM))
    obsw.tc(12, 3, PusService12.build_add(BDOT_GAIN_PARAM, None, 5000.0,
                                          0x7001, 0x7002, 2, tc_apid=0x010).app_data)
    obsw.run(5)
    packets = obsw.take()
    gain = [struct.unpack_from(">f", p.app_data, 2)[0] for p in packets
            if (p.service, p.subservice) == (20, 2)]
    events = _events(packets, 0x7002)
    assert len(events) == 1, f"expected one high-limit event, got {len(events)}"
    assert struct.unpack_from(">f", events[0], 2)[0] == pytest.approx(gain[-1])
    obsw.run(20)
    assert _events(obsw.take(), 0x7002) == [], "event repeated while still out of limit"


@pytest.mark.requirement("SVF-DEV-211")
def test_s19_event_dispatches_action_tc(obsw: ObswHarness) -> None:
    from svf.pus.services.s12_monitoring import PusService12
    from svf.pus.services.s19_event_action import PusService19
    _nominal_at_obt(obsw, 100)
    obsw.tc(19, 1, PusService19.build_add(0x7004, _ping(), tc_apid=0x010).app_data)
    obsw.run(3)
    assert _pongs(obsw.take()) == 0, "action ran before its event"
    obsw.tc(12, 3, PusService12.build_add(BDOT_GAIN_PARAM, None, 5000.0,
                                          0x7003, 0x7004, 2, tc_apid=0x010).app_data)
    obsw.run(5)
    packets = obsw.take()
    assert _events(packets, 0x7004), "triggering S12 event not raised"
    assert _pongs(packets) == 1, "S19 action TC(17,1) not dispatched"
