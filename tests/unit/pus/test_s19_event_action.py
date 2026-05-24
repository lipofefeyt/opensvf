"""
Tests for PUS Service 19 Event-Action Service (M40).
Implements: SVF-DEV-165
"""

import struct
import pytest
from unittest.mock import MagicMock

from svf.pus.tc import PusTcPacket, PusTcBuilder
from svf.pus.services import (
    PusService5, PusService19,
    EventActionService, EventActionDefinition, EventSeverity,
)
from svf.stores.parameter_store import ParameterStore
from svf.stores.command_store import CommandStore


# ── PusService19 static API ───────────────────────────────────────────────────

@pytest.mark.requirement("SVF-DEV-165")
def test_s19_is_add_detects_tc_19_1() -> None:
    tc = PusTcPacket(apid=0x100, sequence_count=1, service=19, subservice=1,
                     app_data=struct.pack(">H", 0x0001) + b"\x18\x01\xc0\x00\x00\x03\x20\x11\x01\x00")
    assert PusService19.is_add(tc) is True


@pytest.mark.requirement("SVF-DEV-165")
def test_s19_is_add_rejects_other() -> None:
    assert PusService19.is_add(
        PusTcPacket(apid=0x100, sequence_count=1, service=17, subservice=1)
    ) is False


@pytest.mark.requirement("SVF-DEV-165")
def test_s19_build_and_parse_add_roundtrip() -> None:
    action = b"\x18\x01\xc0\x00\x00\x03\x20\x11\x01\x00"
    tc = PusService19.build_add(0x0002, action, tc_apid=0x100, sequence_count=1)
    assert tc.service == 19
    assert tc.subservice == 1
    event_id, got_action = PusService19.parse_add(tc)
    assert event_id == 0x0002
    assert got_action == action


@pytest.mark.requirement("SVF-DEV-165")
def test_s19_parse_add_short_raises() -> None:
    tc = PusTcPacket(apid=0x100, sequence_count=1, service=19, subservice=1,
                     app_data=b"\x00\x01")  # 2 bytes — no TC payload
    with pytest.raises(ValueError, match="too short"):
        PusService19.parse_add(tc)


@pytest.mark.requirement("SVF-DEV-165")
def test_s19_parse_delete() -> None:
    tc = PusTcPacket(apid=0x100, sequence_count=1, service=19, subservice=2,
                     app_data=struct.pack(">H", 0x0005))
    assert PusService19.parse_delete(tc) == 0x0005


@pytest.mark.requirement("SVF-DEV-165")
def test_s19_build_add_survives_wire_encode_decode() -> None:
    from svf.pus.tc import PusTcParser
    action = b"\x18\x01\xc0\x00\x00\x03\x20\x11\x01\x00"
    tc = PusService19.build_add(0x0003, action)
    raw = PusTcBuilder().build(tc)
    parsed = PusTcParser().parse(raw)
    event_id, got = PusService19.parse_add(parsed)
    assert event_id == 0x0003
    assert got == action


# ── EventActionService ────────────────────────────────────────────────────────

@pytest.mark.requirement("SVF-DEV-165")
def test_eas_add_and_react() -> None:
    eas = EventActionService()
    action = b"\xAA\xBB"
    eas.add(EventActionDefinition(event_id=0x0001, action_tc=action))
    assert eas.react(0x0001) == [action]


@pytest.mark.requirement("SVF-DEV-165")
def test_eas_react_unknown_event_returns_empty() -> None:
    eas = EventActionService()
    assert eas.react(0x9999) == []


@pytest.mark.requirement("SVF-DEV-165")
def test_eas_add_replaces_existing() -> None:
    eas = EventActionService()
    eas.add(EventActionDefinition(event_id=0x0001, action_tc=b"\x01"))
    eas.add(EventActionDefinition(event_id=0x0001, action_tc=b"\x02"))
    assert eas.count == 1
    assert eas.react(0x0001) == [b"\x02"]


@pytest.mark.requirement("SVF-DEV-165")
def test_eas_delete_removes_definition() -> None:
    eas = EventActionService()
    eas.add(EventActionDefinition(event_id=0x0001, action_tc=b"\x01"))
    assert eas.delete(0x0001) is True
    assert eas.count == 0
    assert eas.delete(0x0001) is False


@pytest.mark.requirement("SVF-DEV-165")
def test_eas_delete_all() -> None:
    eas = EventActionService()
    for i in range(3):
        eas.add(EventActionDefinition(event_id=i, action_tc=bytes([i])))
    assert eas.delete_all() == 3
    assert eas.count == 0


@pytest.mark.requirement("SVF-DEV-165")
def test_eas_disabled_does_not_react() -> None:
    eas = EventActionService()
    eas.add(EventActionDefinition(event_id=0x0001, action_tc=b"\x01"))
    eas.disable()
    assert eas.react(0x0001) == []


@pytest.mark.requirement("SVF-DEV-165")
def test_eas_re_enable_reacts() -> None:
    eas = EventActionService()
    eas.add(EventActionDefinition(event_id=0x0001, action_tc=b"\x01"))
    eas.disable()
    eas.enable()
    assert eas.react(0x0001) == [b"\x01"]


@pytest.mark.requirement("SVF-DEV-165")
def test_eas_individual_definition_disabled() -> None:
    eas = EventActionService()
    defn = EventActionDefinition(event_id=0x0001, action_tc=b"\x01", enabled=False)
    eas.add(defn)
    assert eas.react(0x0001) == []


# ── ObcEquipment integration ──────────────────────────────────────────────────

@pytest.mark.requirement("SVF-DEV-165")
def test_obc_tc_19_1_registers_reaction_fired_next_tick() -> None:
    """TC(19,1) links event 0x0002 to a TC(17,1); when OBC generates a
    TM(5,x) with event_id=0x0002, the action TC fires on the next tick."""
    from svf.models.dhs.obc import ObcEquipment, ObcConfig

    PARAM_ID   = 0x3001
    EVENT_HIGH = 0x0002

    store     = ParameterStore()
    cmd_store = CommandStore()
    cfg = ObcConfig(
        apid=0x101,
        param_id_map={PARAM_ID: "eps.battery.soc"},
    )
    obc = ObcEquipment(cfg, MagicMock(), store, cmd_store)
    obc.initialise(start_time=0.0)

    # Build action TC(17,1) to fire as reaction
    action_bytes = PusTcBuilder().build(
        PusTcPacket(apid=0x100, sequence_count=1, service=17, subservice=1)
    )

    # Register S19: event 0x0002 → TC(17,1)
    add_tc = PusTcBuilder().build(
        PusService19.build_add(EVENT_HIGH, action_bytes, tc_apid=0x100, sequence_count=2)
    )
    obc.receive_tc(add_tc, t=0.0)
    assert obc._s19.count == 1

    # Register S12: eps.battery.soc high limit=0.9 → event 0x0002
    from svf.pus.services import PusService12
    mon_tc = PusTcBuilder().build(PusService12.build_add(
        param_id=PARAM_ID, low_limit=None, high_limit=0.9,
        event_id_low=0, event_id_high=EVENT_HIGH,
        severity=EventSeverity.MEDIUM,
    ))
    obc.receive_tc(mon_tc, t=0.0)

    # Step 1: write OOL value → S12 fires S5 event → S19 queues reaction
    store.write("eps.battery.soc", 0.95, t=1.0, model_id="test")
    obc.do_step(t=1.0, dt=1.0)
    assert len(obc._pending_reactions) == 1  # reaction queued

    # Step 2: pending reaction dispatched → OBC receives TC(17,1)
    # TM(17,2) are-you-alive response should appear in queue
    obc.do_step(t=2.0, dt=1.0)
    assert len(obc._pending_reactions) == 0  # drained
    all_tm = obc.get_tm_queue()
    alive_responses = [p for p in all_tm if p.service == 17 and p.subservice == 2]
    assert len(alive_responses) >= 1


@pytest.mark.requirement("SVF-DEV-165")
def test_obc_tc_19_4_5_enable_disable() -> None:
    """TC(19,4) enables and TC(19,5) disables the event-action service."""
    from svf.models.dhs.obc import ObcEquipment, ObcConfig

    obc = ObcEquipment(ObcConfig(), MagicMock(), ParameterStore(), CommandStore())
    obc.initialise()

    disable_tc = PusTcBuilder().build(
        PusTcPacket(apid=0x100, sequence_count=1, service=19, subservice=5)
    )
    obc.receive_tc(disable_tc, t=0.0)
    assert obc._s19.enabled is False

    enable_tc = PusTcBuilder().build(
        PusTcPacket(apid=0x100, sequence_count=2, service=19, subservice=4)
    )
    obc.receive_tc(enable_tc, t=0.0)
    assert obc._s19.enabled is True


@pytest.mark.requirement("SVF-DEV-165")
def test_obc_tc_19_3_clears_all_definitions() -> None:
    """TC(19,3) removes all event-action definitions."""
    from svf.models.dhs.obc import ObcEquipment, ObcConfig

    obc = ObcEquipment(ObcConfig(), MagicMock(), ParameterStore(), CommandStore())
    obc.initialise()

    action = PusTcBuilder().build(
        PusTcPacket(apid=0x100, sequence_count=1, service=17, subservice=1)
    )
    for eid in [0x0001, 0x0002, 0x0003]:
        obc.receive_tc(PusTcBuilder().build(
            PusService19.build_add(eid, action, sequence_count=eid)
        ), t=0.0)
    assert obc._s19.count == 3

    delete_all_tc = PusTcBuilder().build(
        PusTcPacket(apid=0x100, sequence_count=99, service=19, subservice=3)
    )
    obc.receive_tc(delete_all_tc, t=0.0)
    assert obc._s19.count == 0
