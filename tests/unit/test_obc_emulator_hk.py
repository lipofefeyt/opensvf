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


# ── SRDB-driven TM(3,25) decoding (SVF-DEV-217) ──────────────────────────────

def _hk(set_id: int, params: bytes) -> bytes:
    """TM(3,25) without PEC: 17-byte header, set id, parameter bytes."""
    app = bytes([set_id]) + params
    return bytes([0x09, 0x03, 0xC0, 0x00]) + (10 + len(app)).to_bytes(2, "big") \
        + bytes([0x20, 3, 25]) + bytes(8) + app


def _value(store: ParameterStore, name: str) -> float:
    entry = store.read(name)
    assert entry is not None, f"{name} not in the store"
    return float(entry.value)


@pytest.mark.requirement("SVF-DEV-217")
def test_set1_is_decoded_into_named_parameters() -> None:
    """nominal_hk: int16, uint16, uint16, uint32. A negative temperature stays negative."""
    import struct
    adapter, store = _adapter()
    adapter._parse_tm(_hk(1, struct.pack(">hHHI", -100, 3300, 5000, 42)), t=3.0)
    assert _value(store, "dhs.obc.obc_temperature") == -100.0
    assert _value(store, "dhs.obc.obc_voltage_3v3") == 3300.0
    assert _value(store, "dhs.obc.obc_voltage_5v") == 5000.0
    assert _value(store, "dhs.obc.obc_uptime") == 42.0
    entry = store.read("dhs.obc.obc_temperature")
    assert entry is not None and (entry.t, entry.model_id) == (3.0, "obc")
    assert adapter.link_health().healthy


@pytest.mark.requirement("SVF-DEV-217")
@pytest.mark.parametrize("set_id, fmt, values, names", [
    (2, ">HII", (3, 1200, 28),
     ("safe_mode_entry_count", "watchdog_kick_count", "watchdog_ticks_remaining")),
    (4, ">fff", (1.0e4, 0.5, 0.125), ("bdot_gain", "adcs_kp", "adcs_kd")),
    (5, ">ffffff", (550.0, 97.5, 0.25, 0.5, 0.75, 0.125),
     ("orbit_altitude_km", "orbit_inclination_deg", "sc_inertia_xx",
      "sc_inertia_yy", "sc_inertia_zz", "mtq_max_dipole")),
    (6, ">ffB", (0.25, 0.0625, 2),
     ("aocs_angle_err_rad", "aocs_omega_mag", "aocs_controller")),
    (7, ">ffffffB", (1.5, -2.5, 0.5, 0.25, -0.125, 0.0, 1),
     ("bdot_mag_x", "bdot_mag_y", "bdot_mag_z", "bdot_m_cmd_x",
      "bdot_m_cmd_y", "bdot_m_cmd_z", "bdot_mag_valid")),
])
def test_every_other_openobsw_set_is_decoded(
    set_id: int, fmt: str, values: tuple[float, ...], names: tuple[str, ...],
) -> None:
    import struct
    adapter, store = _adapter()
    adapter._parse_tm(_hk(set_id, struct.pack(fmt, *values)), t=1.0)
    assert [_value(store, f"dhs.obc.{n}") for n in names] == [float(v) for v in values]


@pytest.mark.requirement("SVF-DEV-217", "SVF-DEV-210")
def test_set3_still_drives_mode_obt_and_both_key_families() -> None:
    adapter, store = _adapter()
    adapter._parse_tm(_set3(MODE_NOMINAL, 1000), t=1.0)
    assert (adapter._mode, adapter._obc_obt) == (MODE_NOMINAL, 1000)
    assert (adapter._obc_memory_used_pct, adapter._obc_health, adapter._obc_cpu_load) == (12, 1, 5)
    assert adapter.link_health().mode_changes == [(1.0, MODE_NOMINAL)]
    for name, value in (("obc_mode", MODE_NOMINAL), ("obc_obt", 1000),
                        ("obc_watchdog_status", 0), ("obc_memory_used_pct", 12),
                        ("obc_health", 1), ("obc_reset_count", 0), ("obc_cpu_load", 5)):
        assert _value(store, f"dhs.obc.{name}") == float(value)
        assert _value(store, name) == float(value)          # key from before SVF-DEV-217


@pytest.mark.requirement("SVF-DEV-217")
@pytest.mark.parametrize("params", [
    bytes(9),      # one byte short of nominal_hk
    bytes(12),     # two bytes too many, e.g. a PEC the adapter was not told about
])
def test_report_not_matching_its_layout_is_not_decoded_and_is_counted(params: bytes) -> None:
    """Decoding a shifted report would store wrong values with no error."""
    adapter, store = _adapter()
    adapter._parse_tm(_hk(1, params), t=1.0)
    assert store.read("dhs.obc.obc_temperature") is None
    health = adapter.link_health()
    assert health.hk_undecoded == 1 and not health.healthy
    assert health.last_hk_problem is not None
    assert f"carries {len(params)} parameter bytes, SRDB layout has 10" in health.last_hk_problem
    assert "1 HK report(s) not decoded" in health.problems()[0]
    assert health.to_dict()["hk_undecoded"] == 1
    assert health.tm_dropped == 0                # the packet itself parsed and was queued
    assert [(p.service, p.subservice) for p in adapter.get_tm_queue()] == [(3, 25)]


@pytest.mark.requirement("SVF-DEV-217")
def test_mismatched_set3_report_does_not_touch_the_mode() -> None:
    adapter, _ = _adapter()
    adapter._parse_tm(_set3(MODE_NOMINAL, 10), t=1.0)
    adapter._parse_tm(_hk(3, bytes([MODE_SAFE]) + bytes(5)), t=2.0)
    assert adapter._mode == MODE_NOMINAL
    assert adapter.link_health().mode_changes == [(1.0, MODE_NOMINAL)]


@pytest.mark.requirement("SVF-DEV-217")
def test_set_without_a_layout_is_logged_once_and_link_stays_healthy(
    caplog: pytest.LogCaptureFixture,
) -> None:
    import logging
    adapter, store = _adapter()
    with caplog.at_level(logging.WARNING, logger="svf.models.dhs.obc_emulator"):
        for _ in range(3):
            adapter._parse_tm(_hk(42, bytes(6)), t=1.0)
    assert [r.getMessage() for r in caplog.records].count(
        "[obc-emu] TM(3,25) set 42 has no SRDB layout; its reports are not decoded") == 1
    assert adapter.link_health().healthy
    assert not [n for n in store.snapshot() if n.startswith("dhs.obc.")]


@pytest.mark.requirement("SVF-DEV-217", "SVF-DEV-205")
def test_pec_is_excluded_from_the_report_when_expected() -> None:
    import struct
    from svf.pus.tm import PusTmBuilder, PusTmPacket
    store = ParameterStore()
    adapter = OBCEmulatorAdapter(sim_path=None, sync_protocol=MagicMock(),
                                 store=store, tm_pec=True)
    pkt = PusTmBuilder().build(PusTmPacket(
        apid=0x010, sequence_count=1, service=3, subservice=25,
        app_data=bytes([1]) + struct.pack(">hHHI", 1250, 3300, 5000, 7)))
    adapter._parse_tm(pkt, t=1.0)
    assert _value(store, "dhs.obc.obc_temperature") == 1250.0
    assert adapter.link_health().healthy


@pytest.mark.requirement("SVF-DEV-217")
def test_layouts_can_be_supplied_and_set3_must_carry_the_obc_state() -> None:
    """A mission layout replaces the bundled one; set 3 without obc_mode is refused."""
    import struct
    from svf.srdb.definitions import HkParameter, HkSetDefinition, HkWireType
    from svf.srdb.loader import load_bundled_hk_sets
    mission = HkSetDefinition(8, "payload_hk", (
        HkParameter("dhs.obc.payload_temp", "payload_temp", HkWireType.INT16),))
    store = ParameterStore()
    adapter = OBCEmulatorAdapter(
        sim_path=None, sync_protocol=MagicMock(), store=store,
        hk_sets={**load_bundled_hk_sets(), 8: mission})
    adapter._parse_tm(_hk(8, struct.pack(">h", -5)), t=1.0)
    assert _value(store, "dhs.obc.payload_temp") == -5.0

    broken = HkSetDefinition(3, "dhs_obc_hk", (
        HkParameter("dhs.obc.obc_obt", "obc_obt", HkWireType.UINT32),))
    with pytest.raises(ValueError, match="lacks .*obc_mode"):
        OBCEmulatorAdapter(sim_path=None, sync_protocol=MagicMock(),
                           store=ParameterStore(), hk_sets={3: broken})
