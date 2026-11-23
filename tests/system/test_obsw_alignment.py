"""
L3 alignment tests against the real openobsw obsw_sim (v0.19 or later).

Each test drives OBCEmulatorAdapter directly and inspects the parsed TM
queue, so it exercises the same decoding path campaigns and the TTC model
use. Covers:

- TM without Packet Error Control is parsed (SVF-DEV-205)
- HK TM(3,25) byte order: OBT in seconds, TC(9,128) sets it, AOCS floats
  match their S20 values; every TM header carries OBT (SVF-DEV-206,
  opensvf#192)
- SAFE TC gate: rejection code 0x0007, accepted once NOMINAL (SVF-DEV-209)
- S11, S12, S19 built with opensvf's codecs behave as openobsw specifies
  (SVF-DEV-211)
- Each commanded transition emits one real mode event; S5 mode events are
  a hint that HK set 3 overrides (SVF-DEV-216)
- Every HK set is decoded into named parameters from its SRDB layout
  (SVF-DEV-217)
- Wire protocol v4: a simulator-driven thermal fault commands SAFE, and
  its clearance (or persistence) is observable in SAFE (SVF-DEV-219)

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
    # Every alignment test also guards the link itself (SVF-DEV-214).
    health = h.adapter.link_health()
    assert health.healthy, "OBSW link unhealthy: " + "; ".join(health.problems())


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
def test_tm_timestamp_follows_obt(obsw: ObswHarness) -> None:
    """
    Every TM header carries OBT whole seconds (OBSW-SRS-153): set 3 reports
    carry their own obc_obt, the time follows TC(9,128), and the S1 reports
    of that TC still carry the old time.
    """
    obsw.run(25)
    before = obsw.take()
    assert before and all(p.timestamp <= obsw.t + 1 for p in before), \
        f"TM time ahead of {obsw.t} s: {sorted({p.timestamp for p in before})}"

    seq = obsw.tc(9, 128, struct.pack(">I", 1000))
    obsw.run(30)
    after = obsw.take()

    def _for_seq(p: PusTmPacket) -> bool:
        return (p.service == 1 and len(p.app_data) >= 4
                and struct.unpack_from(">H", p.app_data, 2)[0] & 0x3FFF == seq)
    s1 = [p for p in after if _for_seq(p)]
    assert s1, "no S1 report of TC(9,128)"
    assert all(p.timestamp < 1000 for p in s1), \
        f"S1 of TC(9,128) carries the new time: {[p.timestamp for p in s1]}"

    rest = [p for p in after if not _for_seq(p)]
    set3 = [p for p in rest if (p.service, p.subservice) == (3, 25)
            and p.app_data[0] == 3]
    assert set3, "no set 3 report after TC(9,128)"
    for p in set3:
        assert p.timestamp == struct.unpack_from(">I", p.app_data, 2)[0], \
            "set 3 header time differs from its obc_obt"
    times = [p.timestamp for p in rest]
    assert times == sorted(times), f"TM time not monotonic: {times}"
    elapsed = obsw.t
    assert all(1000 <= v <= 1000 + elapsed for v in times), \
        f"TM time {sorted(set(times))} does not follow TC(9,128)"


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


# ── S5 mode events are a hint, HK set 3 is the mode source (SVF-DEV-216) ────
# obsw_sim v0.19 and later emit the mode events on every transition, and HK
# set 3 then agrees with them (test_commanded_transitions_emit_one_real_mode_
# event). To test the override, an event must disagree with HK: an S12
# definition raises a mode-event ID without a mode change, since none of
# these IDs is a safe trigger. The adapter must take the hint from the real
# packet and drop it again at the next set 3 report, which still says NOMINAL.


@pytest.mark.requirement("SVF-DEV-216", "SVF-DEV-210")
@pytest.mark.parametrize("event_id, severity, hinted", [
    (0x0002, 4, 1),    # safe_mode_entry, HIGH -> SAFE
    (0x0004, 1, 0),    # standby_entry, INFO -> STANDBY (ignored before SVF-DEV-216)
])
def test_s5_mode_event_is_a_hint_until_hk_set3(
    obsw: ObswHarness, event_id: int, severity: int, hinted: int,
) -> None:
    from svf.models.dhs.obc import MODE_NOMINAL
    from svf.pus.services.s12_monitoring import PusService12
    adapter = obsw.adapter
    store = adapter._store
    assert store is not None
    _nominal_at_obt(obsw, 100)

    # Start right after a set 3 report (every 10 ticks), so the event arrives
    # between two reports and not in the same tick as one.
    for _ in range(20):
        obsw.run(1)
        if ObswHarness.hk(obsw.take(), 3):
            break
    else:
        pytest.fail("no set 3 report in 20 ticks")
    assert adapter._mode == MODE_NOMINAL
    timeline = list(adapter.link_health().mode_changes)

    obsw.tc(12, 3, PusService12.build_add(BDOT_GAIN_PARAM, None, 5000.0,
                                          0x7001, event_id, severity,
                                          tc_apid=0x010).app_data)
    for _ in range(5):
        obsw.run(1)
        packets = obsw.take()
        raised = [p for p in packets
                  if p.service == 5 and _events([p], event_id)]
        if raised:
            assert [p.subservice for p in raised] == [severity]
            assert not ObswHarness.hk(packets, 3), "set 3 report in the event's tick"
            break
    else:
        pytest.fail(f"obsw_sim never raised event 0x{event_id:04X}")

    # The hint moves dhs.obc.mode; what HK reported is untouched.
    assert adapter._mode == hinted
    reported = store.read("obc_mode")
    assert reported is not None and reported.value == float(MODE_NOMINAL)
    assert adapter.link_health().mode_changes == timeline

    obsw.run(10)
    assert ObswHarness.hk(obsw.take(), 3), "no set 3 report after the event"
    assert adapter._mode == MODE_NOMINAL, "HK set 3 did not override the S5 hint"
    assert adapter.link_health().mode_changes == timeline


@pytest.mark.requirement("SVF-DEV-216", "SVF-DEV-210")
def test_commanded_transitions_emit_one_real_mode_event(obsw: ObswHarness) -> None:
    """
    obsw_sim v0.19 and later report each mode transition itself
    (OBSW-SRS-190): one event without aux, in the tick of the TC that changed
    the mode, and none for the boot mode. The adapter's hint and HK set 3
    then agree on the new mode.
    """
    from svf.models.dhs.obc import MODE_NOMINAL, MODE_SAFE, MODE_STANDBY
    mode_events = {SAFE_MODE_ENTRY_ID: 4, STANDBY_ENTRY_ID: 1, NOMINAL_ENTRY_ID: 1}

    def mode_event_ids(packets: list[PusTmPacket]) -> list[int]:
        return [struct.unpack_from(">H", p.app_data, 0)[0] for p in packets
                if p.service == 5
                and struct.unpack_from(">H", p.app_data, 0)[0] in mode_events]

    adapter = obsw.adapter
    obsw.run(15)
    assert mode_event_ids(obsw.take()) == [], "boot mode reported as an event"

    for mode, event_id in [(MODE_NOMINAL, NOMINAL_ENTRY_ID),
                           (MODE_STANDBY, STANDBY_ENTRY_ID),
                           (MODE_SAFE, SAFE_MODE_ENTRY_ID)]:
        adapter.receive("dhs.obc.mode_cmd", float(mode))
        obsw.run(1)
        packets = obsw.take()
        events = [p for p in packets if p.service == 5
                  and struct.unpack_from(">H", p.app_data, 0)[0] == event_id]
        assert len(events) == 1, \
            f"mode {mode}: expected one 0x{event_id:04X} in the TC's tick"
        assert events[0].subservice == mode_events[event_id]
        assert len(events[0].app_data) == 2, \
            f"0x{event_id:04X} carries aux data: {events[0].app_data.hex()}"
        assert mode_event_ids(packets) == [event_id]
        assert adapter._mode == mode, "S5 hint did not follow the real event"

        obsw.run(10)
        packets = obsw.take()
        assert mode_event_ids(packets) == [], "extra mode event after the transition"
        modes = _set3_modes(packets)
        assert modes and set(modes) == {mode}, \
            f"HK set 3 does not report mode {mode}: {modes}"
        assert adapter._mode == mode
        assert adapter.link_health().mode_changes[-1][1] == mode


SAFE_MODE_ENTRY_ID = 0x0002
STANDBY_ENTRY_ID = 0x0004
NOMINAL_ENTRY_ID = 0x0005


# ── SRDB-driven HK decoding against the flight software (SVF-DEV-217) ───────

OBC_TEMPERATURE_PARAM = 0x0001


@pytest.mark.requirement("SVF-DEV-217")
def test_hk_set1_obc_temperature_follows_tc20_1(obsw: ObswHarness) -> None:
    """dhs.obc.obc_temperature is what TC(20,1) set, by name, sign included."""
    store = obsw.adapter._store
    assert store is not None
    _nominal_at_obt(obsw, 100)                    # TC(20,1) is gated in SAFE

    def reported() -> float:
        """Run until the next nominal_hk (set 1) report and return the stored value."""
        obsw.take()
        for _ in range(15):                       # reported every 10 ticks
            obsw.run(1)
            packets = obsw.take()
            assert _s1_failures(packets) == [], "TC(20,1) rejected in NOMINAL"
            if ObswHarness.hk(packets, 1):
                entry = store.read("dhs.obc.obc_temperature")
                assert entry is not None, "set 1 reported but not decoded by name"
                return float(entry.value)
        pytest.fail("no nominal_hk (set 1) report in 15 ticks")

    assert reported() == 0.0                      # obsw_sim boot value
    for raw in (1300, -100):                      # 90 degC and -50 degC in raw counts
        obsw.tc(20, 1, struct.pack(">Hi", OBC_TEMPERATURE_PARAM, raw))
        obsw.run(2)
        assert reported() == float(raw)

    # The rest of set 1 arrives by name too, with the values obsw_sim holds.
    v3v3, v5v, uptime = (store.read(f"dhs.obc.{n}") for n in
                         ("obc_voltage_3v3", "obc_voltage_5v", "obc_uptime"))
    assert v3v3 is not None and v3v3.value == 3300.0
    assert v5v is not None and v5v.value == 5000.0
    assert uptime is not None and obsw.t - 2 <= uptime.value <= obsw.t


@pytest.mark.requirement("SVF-DEV-217", "SVF-DEV-206")
def test_every_reported_hk_set_is_decoded_by_name(obsw: ObswHarness) -> None:
    """Each set obsw_sim reports lands in the store under its SRDB keys, none undecoded."""
    from svf.srdb.loader import load_bundled_hk_sets
    store = obsw.adapter._store
    assert store is not None
    obsw.run(70)                                  # fdir_hk (set 2) is reported every 60 ticks
    packets = obsw.take()
    layouts = load_bundled_hk_sets()
    seen = sorted({d[0] for p in packets if (p.service, p.subservice) == (3, 25)
                   for d in [p.app_data]})
    assert seen == [1, 2, 3, 4, 6], f"sets reported by obsw_sim: {seen}"
    for set_id in seen:
        last = ObswHarness.hk(packets, set_id)[-1]
        assert len(last) == 1 + layouts[set_id].data_len
        expected = layouts[set_id].decode(last, 1)
        for param, value in zip(layouts[set_id].parameters, expected):
            entry = store.read(param.name)
            assert entry is not None, f"{param.name} (set {set_id}) not in the store"
            assert entry.value == pytest.approx(float(value))
    gain = store.read("dhs.obc.bdot_gain")
    assert gain is not None and gain.value == pytest.approx(1.0e4)
    assert obsw.adapter.link_health().hk_undecoded == 0


# ── Simulator-owned thermal input, wire protocol v4 (SVF-DEV-219) ───────────
# The recovery-evidence anomaly: an S12 high limit on obc_temperature raises
# 0x0051 temperature_hard_limit (HIGH, safe trigger) and the OBSW commands
# SAFE. The value is driven from the simulator side through the sensor frame
# and the equipment fault engine, never by TC(20,1), which SAFE rejects. A:
# the fault is cleared and the cleared value is observable while the OBSW
# stays in SAFE. B: the fault stays and so does the out-of-limit value.

HARD_LIMIT_RAW = 1250.0          # 85 degC
FAULT_RAW = 1300.0               # 90 degC
TEMPERATURE_SOFT_LIMIT = 0x0050
TEMPERATURE_HARD_LIMIT = 0x0051
SAFE_MODE_ENTRY = 0x0002
NOMINAL_ENTRY = 0x0005
SEVERITY_HIGH = 4


class ThermalHarness(ObswHarness):
    """ObswHarness with the obc_thermal model ticking before the adapter."""

    def __init__(self) -> None:
        from svf.core.equipment_fault import EquipmentFaultEngine
        from svf.models.dhs.obc_thermal import make_obc_thermal
        super().__init__()
        store = self.adapter._store
        assert store is not None
        self.thermal = make_obc_thermal(MagicMock(), store)
        self.faults = EquipmentFaultEngine("obc_thermal")
        self.thermal.attach_fault_engine(self.faults)

    def run(self, ticks: int) -> None:
        for _ in range(ticks):
            self.thermal.on_tick(self.t, DT)
            self.adapter.do_step(t=self.t, dt=DT)
            self.t = round(self.t + DT, 6)
        self.tm.extend(self.adapter.get_tm_queue())

    def stick(self, raw: float) -> None:
        from svf.core.equipment_fault import EquipmentFault, FaultMode
        from svf.models.dhs.obc_thermal import TEMPERATURE_RAW_PORT
        self.faults.inject(EquipmentFault(
            TEMPERATURE_RAW_PORT, FaultMode.STUCK, raw, 0.0, self.t))


@pytest.fixture
def obsw_thermal() -> Iterator[ThermalHarness]:
    h = ThermalHarness()
    h.adapter.initialise()
    try:
        yield h
    finally:
        h.adapter.teardown()
    health = h.adapter.link_health()
    assert health.healthy, "OBSW link unhealthy: " + "; ".join(health.problems())


def _set1_temperatures(packets: list[PusTmPacket]) -> list[int]:
    """obc_temperature (int16, first parameter) from every nominal_hk report."""
    return [struct.unpack_from(">h", d, 1)[0] for d in ObswHarness.hk(packets, 1)]


def _set3_modes(packets: list[PusTmPacket]) -> list[int]:
    return [d[1] for d in ObswHarness.hk(packets, 3)]


def _thermal_fault_into_safe(obsw: ThermalHarness) -> None:
    """NOMINAL, hard limit on obc_temperature, stuck fault above it, SAFE."""
    from svf.models.dhs.obc import MODE_NOMINAL, MODE_SAFE
    from svf.models.dhs.obc_thermal import NOMINAL_RAW
    from svf.pus.services.s12_monitoring import PusService12
    _nominal_at_obt(obsw, 100)
    obsw.tc(12, 3, PusService12.build_add(
        OBC_TEMPERATURE_PARAM, None, HARD_LIMIT_RAW,
        TEMPERATURE_SOFT_LIMIT, TEMPERATURE_HARD_LIMIT, SEVERITY_HIGH,
        tc_apid=0x010).app_data)
    obsw.run(20)
    packets = obsw.take()
    assert _s1_failures(packets) == [], "TC(12,3) rejected in NOMINAL"
    assert _events(packets, TEMPERATURE_HARD_LIMIT) == [], "limit event at nominal"
    assert set(_set1_temperatures(packets)) == {int(NOMINAL_RAW)}, \
        "obc_temperature does not follow the simulator's thermal input"
    assert set(_set3_modes(packets)) == {MODE_NOMINAL}

    obsw.stick(FAULT_RAW)
    obsw.run(15)
    packets = obsw.take()
    events = _events(packets, TEMPERATURE_HARD_LIMIT)
    assert len(events) == 1, f"expected one 0x0051, got {len(events)}"
    assert struct.unpack_from(">f", events[0], 2)[0] == pytest.approx(FAULT_RAW)
    assert len(_events(packets, SAFE_MODE_ENTRY)) == 1, "no safe_mode_entry event"
    assert _set3_modes(packets)[-1] == MODE_SAFE, "0x0051 did not command SAFE"
    assert _set1_temperatures(packets)[-1] == int(FAULT_RAW)
    assert obsw.adapter._mode == MODE_SAFE


@pytest.mark.requirement("SVF-DEV-219")
def test_thermal_fault_commands_safe_and_clearance_is_observable_in_safe(
    obsw_thermal: ThermalHarness,
) -> None:
    """Outcome A: the cleared value is reported while the OBSW stays in SAFE."""
    from svf.models.dhs.obc import MODE_SAFE
    from svf.models.dhs.obc_thermal import NOMINAL_RAW
    store = obsw_thermal.adapter._store
    assert store is not None
    _thermal_fault_into_safe(obsw_thermal)

    obsw_thermal.faults.clear()
    obsw_thermal.run(50)                      # 5 s in SAFE after clearance
    packets = obsw_thermal.take()
    temperatures = _set1_temperatures(packets)
    assert len(temperatures) >= 4, "too few nominal_hk reports in SAFE"
    assert set(temperatures) == {int(NOMINAL_RAW)}, \
        f"cleared value not observable in SAFE: {temperatures}"
    entry = store.read("dhs.obc.obc_temperature")
    assert entry is not None and entry.value == NOMINAL_RAW
    assert set(_set3_modes(packets)) == {MODE_SAFE}, "OBSW left SAFE on its own"
    assert _events(packets, NOMINAL_ENTRY) == [], "automatic recovery to NOMINAL"
    assert _events(packets, TEMPERATURE_HARD_LIMIT) == []


@pytest.mark.requirement("SVF-DEV-219")
def test_thermal_fault_left_in_place_persists_in_safe(
    obsw_thermal: ThermalHarness,
) -> None:
    """Outcome B: the out-of-limit value keeps being reported, still SAFE."""
    from svf.models.dhs.obc import MODE_SAFE
    _thermal_fault_into_safe(obsw_thermal)

    obsw_thermal.run(50)
    packets = obsw_thermal.take()
    temperatures = _set1_temperatures(packets)
    assert len(temperatures) >= 4, "too few nominal_hk reports in SAFE"
    assert set(temperatures) == {int(FAULT_RAW)}, f"fault not persistent: {temperatures}"
    assert set(_set3_modes(packets)) == {MODE_SAFE}
    assert _events(packets, NOMINAL_ENTRY) == []


@pytest.mark.requirement("SVF-DEV-219")
def test_obc_temperature_still_follows_tc20_1_without_thermal_input(
    obsw: ObswHarness,
) -> None:
    """No obc_thermal model: thermal_valid is 0 and TC(20,1) keeps control."""
    _nominal_at_obt(obsw, 100)
    obsw.tc(20, 1, struct.pack(">Hi", OBC_TEMPERATURE_PARAM, 1100))
    obsw.run(15)
    temperatures = _set1_temperatures(obsw.take())
    assert temperatures and temperatures[-1] == 1100


@pytest.mark.requirement("SVF-DEV-219")
def test_adapter_refuses_a_sim_on_another_wire_protocol(tmp_path: Path) -> None:
    """A binary with a pre-v4 banner is stopped before the first frame."""
    fake = tmp_path / "obsw_sim_v018"
    fake.write_text(
        "#!/bin/sh\n"
        "echo '[OBSW] Host sim started (type-frame protocol v2).' >&2\n"
        "exec cat >/dev/null\n")
    fake.chmod(0o755)
    adapter = OBCEmulatorAdapter(sim_path=fake, sync_protocol=MagicMock(),
                                 store=ParameterStore())
    with pytest.raises(RuntimeError, match="older wire protocol"):
        adapter.initialise()
    assert adapter._proc is None, "refused sim left running"


# ── svf console against the flight software (SVF-DEV-215) ───────────────────

@pytest.mark.requirement("SVF-DEV-215")
def test_console_script_session_against_obsw_sim(capsys: pytest.CaptureFixture[str]) -> None:
    """The documented manual check, run as a script: exit 0, rejection named."""
    from svf.config.spacecraft import SpacecraftLoader
    from svf.console import run_console
    master = SpacecraftLoader.load(_repo / "mission_mysat1" / "spacecraft_hil.yaml")
    code = run_console(master, [
        "ping", "expect 17,2",
        "param set 0x20A0 20000", "expect 1,2",
        "mode nominal", "wait 1.5",
        "param set 0x20A0 20000", "param get 0x20A0", "expect 20,2",
    ], realtime=False)
    out = capsys.readouterr().out
    assert code == 0, out
    assert "rejected: 0x0007 not allowed in this mode" in out
    assert "TM(20,2) param 0x20A0 = 20000" in out
    assert "0 dropped" in out


@pytest.mark.requirement("SVF-DEV-215")
def test_console_failed_expect_exits_nonzero(capsys: pytest.CaptureFixture[str]) -> None:
    from svf.config.spacecraft import SpacecraftLoader
    from svf.console import run_console
    master = SpacecraftLoader.load(_repo / "mission_mysat1" / "spacecraft_hil.yaml")
    code = run_console(master, ["expect 5,4 1"], realtime=False)
    assert code == 1
    assert "FAILED: expected TM(5,4)" in capsys.readouterr().out
