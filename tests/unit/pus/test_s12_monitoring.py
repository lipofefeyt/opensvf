"""
Tests for PUS Service 12 On-Board Monitoring (M39).
Implements: SVF-DEV-164
"""

import math
import struct
import pytest
from unittest.mock import MagicMock

from svf.pus.tc import PusTcPacket, PusTcBuilder
from svf.pus.services import (
    PusService12, OnBoardMonitor, MonitoringDefinition, EventSeverity,
)
from svf.stores.parameter_store import ParameterStore


# ── PusService12 static API ───────────────────────────────────────────────────

@pytest.mark.requirement("SVF-DEV-164")
def test_s12_is_add_detects_tc_12_3() -> None:
    tc = PusTcPacket(apid=0x100, sequence_count=1, service=12, subservice=3,
                     app_data=b"\x00" * 15)
    assert PusService12.is_add(tc) is True


@pytest.mark.requirement("SVF-DEV-164")
def test_s12_is_delete_detects_tc_12_4() -> None:
    tc = PusTcPacket(apid=0x100, sequence_count=1, service=12, subservice=4,
                     app_data=struct.pack(">H", 1))
    assert PusService12.is_delete(tc) is True


@pytest.mark.requirement("SVF-DEV-164")
def test_s12_build_and_parse_add_with_both_limits() -> None:
    tc = PusService12.build_add(
        param_id=0x3001,
        low_limit=-10.0,
        high_limit=100.0,
        event_id_low=0x1001,
        event_id_high=0x1002,
        severity=EventSeverity.MEDIUM,
    )
    assert tc.service == 12
    assert tc.subservice == 3
    defn = PusService12.parse_add(tc, param_name="eps.battery.voltage")
    assert defn.param_id == 0x3001
    assert defn.param_name == "eps.battery.voltage"
    assert defn.low_limit == pytest.approx(-10.0, abs=1e-4)
    assert defn.high_limit == pytest.approx(100.0, abs=1e-4)
    assert defn.event_id_low == 0x1001
    assert defn.event_id_high == 0x1002
    assert defn.severity == EventSeverity.MEDIUM


@pytest.mark.requirement("SVF-DEV-164")
def test_s12_build_add_no_low_limit() -> None:
    tc = PusService12.build_add(
        param_id=0x3002, low_limit=None, high_limit=50.0,
        event_id_low=0, event_id_high=0x2000, severity=EventSeverity.LOW,
    )
    defn = PusService12.parse_add(tc, "test.param")
    assert defn.low_limit is None
    assert defn.high_limit == pytest.approx(50.0, abs=1e-4)


@pytest.mark.requirement("SVF-DEV-164")
def test_s12_build_add_no_limits() -> None:
    tc = PusService12.build_add(
        param_id=0x3003, low_limit=None, high_limit=None,
        event_id_low=0, event_id_high=0, severity=EventSeverity.INFORMATIVE,
    )
    defn = PusService12.parse_add(tc, "test.param")
    assert defn.low_limit is None
    assert defn.high_limit is None


@pytest.mark.requirement("SVF-DEV-164")
def test_s12_parse_add_short_raises() -> None:
    tc = PusTcPacket(apid=0x100, sequence_count=1, service=12, subservice=3,
                     app_data=b"\x00" * 5)
    with pytest.raises(ValueError, match="too short"):
        PusService12.parse_add(tc, "x")


@pytest.mark.requirement("SVF-DEV-164")
def test_s12_parse_delete() -> None:
    tc = PusTcPacket(apid=0x100, sequence_count=1, service=12, subservice=4,
                     app_data=struct.pack(">H", 0x3001))
    assert PusService12.parse_delete(tc) == 0x3001


# ── OnBoardMonitor ────────────────────────────────────────────────────────────

def _make_store(params: dict[str, float]) -> ParameterStore:
    store = ParameterStore()
    for name, val in params.items():
        store.write(name, val, t=0.0, model_id="test")
    return store


def _seq() -> int:
    _seq._n = getattr(_seq, "_n", 0) + 1
    return _seq._n


@pytest.mark.requirement("SVF-DEV-164")
def test_monitor_add_and_count() -> None:
    mon = OnBoardMonitor()
    mon.add(MonitoringDefinition(
        param_id=1, param_name="p", low_limit=0.0, high_limit=10.0,
        event_id_low=1, event_id_high=2, severity=EventSeverity.LOW,
    ))
    assert mon.count == 1


@pytest.mark.requirement("SVF-DEV-164")
def test_monitor_high_limit_fires_once_on_entry() -> None:
    mon = OnBoardMonitor()
    mon.add(MonitoringDefinition(
        param_id=1, param_name="eps.battery.soc",
        low_limit=None, high_limit=0.9,
        event_id_low=0, event_id_high=0x2001,
        severity=EventSeverity.MEDIUM,
    ))
    store = _make_store({"eps.battery.soc": 0.95})   # OOL

    tms = mon.check(store, tm_apid=0x101, next_seq=_seq, obt=10.0)
    assert len(tms) == 1
    assert tms[0].service == 5
    assert tms[0].subservice == EventSeverity.MEDIUM
    event_id = struct.unpack_from(">H", tms[0].app_data)[0]
    assert event_id == 0x2001

    # Second check with same value: no new event (latched)
    tms2 = mon.check(store, 0x101, _seq, 11.0)
    assert tms2 == []


@pytest.mark.requirement("SVF-DEV-164")
def test_monitor_low_limit_fires_once_on_entry() -> None:
    mon = OnBoardMonitor()
    mon.add(MonitoringDefinition(
        param_id=2, param_name="eps.battery.voltage",
        low_limit=3.0, high_limit=None,
        event_id_low=0x1001, event_id_high=0,
        severity=EventSeverity.HIGH,
    ))
    store = _make_store({"eps.battery.voltage": 2.5})   # below low limit

    tms = mon.check(store, 0x101, _seq, 0.0)
    assert len(tms) == 1
    assert tms[0].subservice == EventSeverity.HIGH
    event_id = struct.unpack_from(">H", tms[0].app_data)[0]
    assert event_id == 0x1001

    # Still OOL  -  no repeat
    tms2 = mon.check(store, 0x101, _seq, 1.0)
    assert tms2 == []


@pytest.mark.requirement("SVF-DEV-164")
def test_monitor_recovery_then_new_ool_fires_again() -> None:
    mon = OnBoardMonitor()
    mon.add(MonitoringDefinition(
        param_id=3, param_name="aocs.rate",
        low_limit=None, high_limit=1.0,
        event_id_low=0, event_id_high=0x3001,
        severity=EventSeverity.LOW,
    ))
    store = _make_store({"aocs.rate": 1.5})   # OOL

    tms1 = mon.check(store, 0x101, _seq, 0.0)
    assert len(tms1) == 1

    # Recover
    store.write("aocs.rate", 0.5, t=1.0, model_id="test")
    tms2 = mon.check(store, 0x101, _seq, 1.0)
    assert tms2 == []

    # OOL again → fires again
    store.write("aocs.rate", 2.0, t=2.0, model_id="test")
    tms3 = mon.check(store, 0x101, _seq, 2.0)
    assert len(tms3) == 1


@pytest.mark.requirement("SVF-DEV-164")
def test_monitor_in_limits_no_event() -> None:
    mon = OnBoardMonitor()
    mon.add(MonitoringDefinition(
        param_id=4, param_name="p",
        low_limit=0.0, high_limit=10.0,
        event_id_low=1, event_id_high=2,
        severity=EventSeverity.LOW,
    ))
    store = _make_store({"p": 5.0})   # within limits

    tms = mon.check(store, 0x101, _seq, 0.0)
    assert tms == []


@pytest.mark.requirement("SVF-DEV-164")
def test_monitor_unknown_parameter_skipped() -> None:
    mon = OnBoardMonitor()
    mon.add(MonitoringDefinition(
        param_id=5, param_name="no.such.param",
        low_limit=0.0, high_limit=1.0,
        event_id_low=1, event_id_high=2,
        severity=EventSeverity.LOW,
    ))
    # Empty store  -  no entry → no crash, no event
    tms = mon.check(ParameterStore(), 0x101, _seq, 0.0)
    assert tms == []


@pytest.mark.requirement("SVF-DEV-164")
def test_monitor_disabled_does_not_check() -> None:
    mon = OnBoardMonitor()
    mon.add(MonitoringDefinition(
        param_id=6, param_name="p",
        low_limit=None, high_limit=0.0,
        event_id_low=0, event_id_high=0x9999,
        severity=EventSeverity.HIGH,
    ))
    store = _make_store({"p": 999.0})   # very OOL
    mon.disable()
    tms = mon.check(store, 0x101, _seq, 0.0)
    assert tms == []


@pytest.mark.requirement("SVF-DEV-164")
def test_monitor_delete_removes_definition() -> None:
    mon = OnBoardMonitor()
    mon.add(MonitoringDefinition(
        param_id=7, param_name="p",
        low_limit=None, high_limit=0.0,
        event_id_low=0, event_id_high=1,
        severity=EventSeverity.LOW,
    ))
    assert mon.delete(7) is True
    assert mon.count == 0
    assert mon.delete(7) is False


@pytest.mark.requirement("SVF-DEV-164")
def test_monitor_delete_all() -> None:
    mon = OnBoardMonitor()
    for i in range(4):
        mon.add(MonitoringDefinition(
            param_id=i, param_name=f"p{i}",
            low_limit=None, high_limit=1.0,
            event_id_low=0, event_id_high=i,
            severity=EventSeverity.INFORMATIVE,
        ))
    assert mon.delete_all() == 4
    assert mon.count == 0


# ── ObcEquipment integration ──────────────────────────────────────────────────

@pytest.mark.requirement("SVF-DEV-164")
def test_obc_tc_12_3_adds_monitor_and_fires_ool_event() -> None:
    """TC(12,3) adds a monitor; OBC fires S5 event when parameter goes OOL."""
    from svf.models.dhs.obc import ObcEquipment, ObcConfig
    from svf.stores.command_store import CommandStore

    PARAM_ID = 0x3001
    store = ParameterStore()
    cmd_store = CommandStore()
    cfg = ObcConfig(
        apid=0x101,
        param_id_map={PARAM_ID: "eps.battery.soc"},
    )
    obc = ObcEquipment(cfg, MagicMock(), store, cmd_store)
    obc.initialise(start_time=0.0)

    # Send TC(12,3): monitor eps.battery.soc, high limit = 0.9
    add_tc = PusTcBuilder().build(PusService12.build_add(
        param_id=PARAM_ID,
        low_limit=None,
        high_limit=0.9,
        event_id_low=0,
        event_id_high=0x2001,
        severity=EventSeverity.MEDIUM,
    ))
    obc.receive_tc(add_tc, t=0.0)
    assert obc._s12.count == 1

    # Write an in-limits value → no OOL event
    store.write("eps.battery.soc", 0.8, t=1.0, model_id="test")
    obc.do_step(t=1.0, dt=1.0)
    tm_queue = obc.get_tm_queue()
    ool_events = [p for p in tm_queue if p.service == 5 and p.subservice == EventSeverity.MEDIUM]
    assert ool_events == []

    # Write an OOL value → OOL event generated
    store.write("eps.battery.soc", 0.95, t=2.0, model_id="test")
    obc.do_step(t=2.0, dt=1.0)
    tm_queue2 = obc.get_tm_queue()
    ool_events2 = [p for p in tm_queue2 if p.service == 5]
    assert len(ool_events2) >= 1
    event_id = struct.unpack_from(">H", ool_events2[0].app_data)[0]
    assert event_id == 0x2001


@pytest.mark.requirement("SVF-DEV-164")
def test_obc_tc_12_2_disables_monitoring() -> None:
    """TC(12,2) disables OBC monitoring service."""
    from svf.models.dhs.obc import ObcEquipment, ObcConfig
    from svf.stores.command_store import CommandStore

    obc = ObcEquipment(ObcConfig(), MagicMock(), ParameterStore(), CommandStore())
    obc.initialise()

    disable_tc = PusTcBuilder().build(
        PusTcPacket(apid=0x100, sequence_count=1, service=12, subservice=2)
    )
    obc.receive_tc(disable_tc, t=0.0)
    assert obc._s12.enabled is False

    enable_tc = PusTcBuilder().build(
        PusTcPacket(apid=0x100, sequence_count=2, service=12, subservice=1)
    )
    obc.receive_tc(enable_tc, t=0.0)
    assert obc._s12.enabled is True


@pytest.mark.requirement("SVF-DEV-164")
def test_obc_tc_12_5_clears_all_monitors() -> None:
    """TC(12,5) removes all monitoring definitions."""
    from svf.models.dhs.obc import ObcEquipment, ObcConfig
    from svf.stores.command_store import CommandStore

    PARAM_IDS = {0x3001: "p1", 0x3002: "p2"}
    cfg = ObcConfig(apid=0x101, param_id_map=PARAM_IDS)
    obc = ObcEquipment(cfg, MagicMock(), ParameterStore(), CommandStore())
    obc.initialise()

    for pid, name in PARAM_IDS.items():
        obc.receive_tc(PusTcBuilder().build(PusService12.build_add(
            param_id=pid, low_limit=None, high_limit=1.0,
            event_id_low=0, event_id_high=pid,
            severity=EventSeverity.LOW,
        )), t=0.0)
    assert obc._s12.count == 2

    delete_all_tc = PusTcBuilder().build(
        PusTcPacket(apid=0x100, sequence_count=99, service=12, subservice=5)
    )
    obc.receive_tc(delete_all_tc, t=0.0)
    assert obc._s12.count == 0
