"""
Tests for PUS Service 11 Time-Based Scheduling (M38).
Implements: SVF-DEV-163
"""

import struct
import pytest
from svf.pus.tc import PusTcPacket, PusTcBuilder, PusTcParser
from svf.pus.services import PusService11, TimeBasedScheduler


# ── PusService11 static API ───────────────────────────────────────────────────

@pytest.mark.requirement("SVF-DEV-163")
def test_s11_is_insert_detects_tc_11_4() -> None:
    tc = PusTcPacket(apid=0x100, sequence_count=1, service=11, subservice=4,
                     app_data=struct.pack(">IH", 60, 0) + b"\x18\x01\xc0\x00\x00\x03\x20\x11\x01\x00")
    assert PusService11.is_insert(tc) is True


@pytest.mark.requirement("SVF-DEV-163")
def test_s11_is_insert_rejects_other() -> None:
    tc = PusTcPacket(apid=0x100, sequence_count=1, service=17, subservice=1)
    assert PusService11.is_insert(tc) is False


@pytest.mark.requirement("SVF-DEV-163")
def test_s11_parse_insert_extracts_time_tag_and_embedded_tc() -> None:
    embedded = b"\x18\x01\xc0\x00\x00\x03\x20\x11\x01\x00"
    tc = PusTcPacket(apid=0x100, sequence_count=1, service=11, subservice=4,
                     app_data=struct.pack(">IH", 120, 0x8000) + embedded)
    time_tag, got_embedded = PusService11.parse_insert(tc)
    assert time_tag == pytest.approx(120.5, abs=1e-4)
    assert got_embedded == embedded


@pytest.mark.requirement("SVF-DEV-163")
def test_s11_parse_insert_short_app_data_raises() -> None:
    tc = PusTcPacket(apid=0x100, sequence_count=1, service=11, subservice=4,
                     app_data=b"\x00\x00\x00")
    with pytest.raises(ValueError, match="too short"):
        PusService11.parse_insert(tc)


@pytest.mark.requirement("SVF-DEV-163")
def test_s11_parse_delete_extracts_request_id() -> None:
    tc = PusTcPacket(apid=0x100, sequence_count=1, service=11, subservice=5,
                     app_data=struct.pack(">H", 7))
    assert PusService11.parse_delete(tc) == 7


@pytest.mark.requirement("SVF-DEV-163")
def test_s11_build_insert_roundtrip() -> None:
    embedded = b"\x18\x01\xc0\x00\x00\x03\x20\x11\x01\x00"
    tc = PusService11.build_insert(300.25, embedded, tc_apid=0x100, sequence_count=1)
    assert tc.service == 11
    assert tc.subservice == 4
    time_tag, got = PusService11.parse_insert(tc)
    assert time_tag == pytest.approx(300.25, abs=1 / 65536)
    assert got == embedded


@pytest.mark.requirement("SVF-DEV-163")
def test_s11_build_insert_survives_wire_encode_decode() -> None:
    embedded = b"\x18\x01\xc0\x00\x00\x03\x20\x11\x01\x00"
    tc = PusService11.build_insert(60.0, embedded)
    raw = PusTcBuilder().build(tc)
    parsed = PusTcParser().parse(raw)
    time_tag, got = PusService11.parse_insert(parsed)
    assert time_tag == pytest.approx(60.0, abs=1 / 65536)
    assert got == embedded


# ── TimeBasedScheduler ────────────────────────────────────────────────────────

@pytest.mark.requirement("SVF-DEV-163")
def test_scheduler_insert_returns_unique_ids() -> None:
    sched = TimeBasedScheduler()
    r1 = sched.insert(10.0, b"\x01")
    r2 = sched.insert(20.0, b"\x02")
    assert r1 != r2
    assert sched.count == 2


@pytest.mark.requirement("SVF-DEV-163")
def test_scheduler_due_returns_tc_at_correct_obt() -> None:
    sched = TimeBasedScheduler()
    sched.insert(10.0, b"\xAA")
    sched.insert(20.0, b"\xBB")

    assert sched.due(9.9) == []
    assert sched.count == 2

    fired = sched.due(10.0)
    assert fired == [b"\xAA"]
    assert sched.count == 1

    fired = sched.due(25.0)
    assert fired == [b"\xBB"]
    assert sched.count == 0


@pytest.mark.requirement("SVF-DEV-163")
def test_scheduler_due_fires_multiple_at_once() -> None:
    sched = TimeBasedScheduler()
    sched.insert(5.0, b"\x01")
    sched.insert(5.0, b"\x02")
    sched.insert(10.0, b"\x03")

    fired = sched.due(5.0)
    assert len(fired) == 2
    assert sched.count == 1


@pytest.mark.requirement("SVF-DEV-163")
def test_scheduler_delete_removes_activity() -> None:
    sched = TimeBasedScheduler()
    rid = sched.insert(30.0, b"\xFF")
    assert sched.delete(rid) is True
    assert sched.count == 0
    assert sched.delete(rid) is False  # already gone


@pytest.mark.requirement("SVF-DEV-163")
def test_scheduler_delete_all() -> None:
    sched = TimeBasedScheduler()
    sched.insert(1.0, b"\x01")
    sched.insert(2.0, b"\x02")
    sched.insert(3.0, b"\x03")
    assert sched.delete_all() == 3
    assert sched.count == 0


@pytest.mark.requirement("SVF-DEV-163")
def test_scheduler_disabled_does_not_fire() -> None:
    sched = TimeBasedScheduler()
    sched.insert(5.0, b"\xAA")
    sched.disable()
    assert sched.due(10.0) == []
    assert sched.count == 1  # still queued


@pytest.mark.requirement("SVF-DEV-163")
def test_scheduler_re_enable_fires_overdue() -> None:
    sched = TimeBasedScheduler()
    sched.insert(5.0, b"\xAA")
    sched.disable()
    sched.due(10.0)  # nothing fired
    sched.enable()
    fired = sched.due(10.0)
    assert fired == [b"\xAA"]


# ── ObcEquipment integration ──────────────────────────────────────────────────

@pytest.mark.requirement("SVF-DEV-163")
def test_obc_routes_tc_11_4_and_fires_at_obt() -> None:
    """TC(11,4) received by ObcEquipment fires the embedded TC when OBT is due."""
    from unittest.mock import MagicMock
    from svf.models.dhs.obc import ObcEquipment, ObcConfig
    from svf.stores.parameter_store import ParameterStore
    from svf.stores.command_store import CommandStore

    store = ParameterStore()
    cmd_store = CommandStore()
    sync = MagicMock()
    cfg = ObcConfig(apid=0x101)
    obc = ObcEquipment(cfg, sync, store, cmd_store)
    obc.initialise(start_time=0.0)

    # Build an embedded TC(17,1) are-you-alive to fire at OBT=5.0
    embedded_tc = PusTcBuilder().build(
        PusTcPacket(apid=0x100, sequence_count=1, service=17, subservice=1)
    )
    insert_tc = PusTcBuilder().build(
        PusService11.build_insert(5.0, embedded_tc, tc_apid=0x100, sequence_count=2)
    )

    obc.receive_tc(insert_tc, t=0.0)
    assert obc._s11.count == 1

    # Advance OBT past the time tag  -  scheduled TC should fire
    obc.do_step(t=5.0, dt=1.0)   # OBT becomes 1.0  -  not yet
    assert obc._s11.count == 1

    # Advance to OBT=5.5 (start_time=0 + 5 ticks of dt=1 + initial dt=1 = 6)
    # Simpler: call do_step until OBT >= 5.0
    for i in range(5):
        obc.do_step(t=float(i + 1), dt=1.0)

    # At this point OBT >= 5.0, activity should have fired
    assert obc._s11.count == 0


@pytest.mark.requirement("SVF-DEV-163")
def test_obc_tc_11_6_clears_schedule() -> None:
    """TC(11,6) Delete All empties the scheduler."""
    from unittest.mock import MagicMock
    from svf.models.dhs.obc import ObcEquipment, ObcConfig
    from svf.stores.parameter_store import ParameterStore
    from svf.stores.command_store import CommandStore

    store = ParameterStore()
    cmd_store = CommandStore()
    obc = ObcEquipment(ObcConfig(), MagicMock(), store, cmd_store)
    obc.initialise()

    embedded = PusTcBuilder().build(
        PusTcPacket(apid=0x100, sequence_count=1, service=17, subservice=1)
    )
    for i in range(3):
        obc.receive_tc(PusTcBuilder().build(
            PusService11.build_insert(float(i + 10), embedded, sequence_count=i)
        ), t=0.0)
    assert obc._s11.count == 3

    delete_all = PusTcBuilder().build(
        PusTcPacket(apid=0x100, sequence_count=99, service=11, subservice=6)
    )
    obc.receive_tc(delete_all, t=0.0)
    assert obc._s11.count == 0


@pytest.mark.requirement("SVF-DEV-163")
def test_obc_tc_11_17_18_enable_disable() -> None:
    """TC(11,17) enables and TC(11,18) disables the scheduler."""
    from unittest.mock import MagicMock
    from svf.models.dhs.obc import ObcEquipment, ObcConfig
    from svf.stores.parameter_store import ParameterStore
    from svf.stores.command_store import CommandStore

    obc = ObcEquipment(ObcConfig(), MagicMock(), ParameterStore(), CommandStore())
    obc.initialise()

    disable_tc = PusTcBuilder().build(
        PusTcPacket(apid=0x100, sequence_count=1, service=11, subservice=18)
    )
    obc.receive_tc(disable_tc, t=0.0)
    assert obc._s11.enabled is False

    enable_tc = PusTcBuilder().build(
        PusTcPacket(apid=0x100, sequence_count=2, service=11, subservice=17)
    )
    obc.receive_tc(enable_tc, t=0.0)
    assert obc._s11.enabled is True
