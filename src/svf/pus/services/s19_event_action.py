"""PUS Service 19  -  Event-Action Service."""

from __future__ import annotations

import struct
from dataclasses import dataclass

from svf.pus.tc import PusTcPacket


@dataclass
class EventActionDefinition:
    """
    Maps a S5 event_id to an automated TC response.

    Attributes:
        event_id:  The S5 event_id that triggers this action.
        action_tc: Raw TC bytes to dispatch when the event fires.
        enabled:   Whether this definition is currently active.
    """
    event_id:  int
    action_tc: bytes
    enabled:   bool = True


class EventActionService:
    """
    S19 Event-Action runtime.

    Holds one ``EventActionDefinition`` per event_id (last write wins).
    ``react()`` is called by ``ObcEquipment._enqueue_tm()`` for every
    enqueued TM(5,x); matching action TCs are collected into a pending
    list and dispatched at the start of the next ``do_step()`` tick,
    avoiding re-entrant calls into ``receive_tc()``.
    """

    def __init__(self) -> None:
        self._definitions: dict[int, EventActionDefinition] = {}
        self._enabled: bool = True

    def add(self, defn: EventActionDefinition) -> None:
        self._definitions[defn.event_id] = defn

    def delete(self, event_id: int) -> bool:
        return self._definitions.pop(event_id, None) is not None

    def delete_all(self) -> int:
        n = len(self._definitions)
        self._definitions.clear()
        return n

    def enable(self) -> None:
        self._enabled = True

    def disable(self) -> None:
        self._enabled = False

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def count(self) -> int:
        return len(self._definitions)

    def react(self, event_id: int) -> list[bytes]:
        """Return action TC bytes for *event_id* if a matching enabled definition exists."""
        if not self._enabled:
            return []
        defn = self._definitions.get(event_id)
        if defn is None or not defn.enabled:
            return []
        return [defn.action_tc]


class PusService19:
    """
    PUS Service 19  -  Event-Action Service.

    TC(19,1)  -  Add Event-Action Definition
    TC(19,2)  -  Delete Event-Action Definition
    TC(19,3)  -  Delete All Event-Action Definitions
    TC(19,4)  -  Enable Event-Action Definitions
    TC(19,5)  -  Disable Event-Action Definitions

    TC(19,1) app_data format:
        2B uint16  event_id
        N bytes    action TC frame
    """

    @staticmethod
    def is_add(tc: PusTcPacket) -> bool:
        return tc.service == 19 and tc.subservice == 1

    @staticmethod
    def is_delete(tc: PusTcPacket) -> bool:
        return tc.service == 19 and tc.subservice == 2

    @staticmethod
    def is_delete_all(tc: PusTcPacket) -> bool:
        return tc.service == 19 and tc.subservice == 3

    @staticmethod
    def is_enable(tc: PusTcPacket) -> bool:
        return tc.service == 19 and tc.subservice == 4

    @staticmethod
    def is_disable(tc: PusTcPacket) -> bool:
        return tc.service == 19 and tc.subservice == 5

    @staticmethod
    def parse_add(tc: PusTcPacket) -> tuple[int, bytes]:
        """Parse TC(19,1) app_data → (event_id, action_tc_bytes)."""
        if len(tc.app_data) < 3:
            raise ValueError(
                f"TC(19,1) app_data too short: {len(tc.app_data)} bytes (need ≥3)"
            )
        event_id: int
        event_id, = struct.unpack_from(">H", tc.app_data)
        return event_id, bytes(tc.app_data[2:])

    @staticmethod
    def parse_delete(tc: PusTcPacket) -> int:
        """Parse TC(19,2) app_data → event_id."""
        if len(tc.app_data) < 2:
            raise ValueError(
                f"TC(19,2) app_data too short: {len(tc.app_data)} bytes (need 2)"
            )
        event_id: int
        event_id, = struct.unpack_from(">H", tc.app_data)
        return event_id

    @staticmethod
    def build_add(
        event_id: int,
        action_tc_bytes: bytes,
        tc_apid: int = 0x100,
        sequence_count: int = 0,
    ) -> PusTcPacket:
        """Build TC(19,1) linking *event_id* to *action_tc_bytes*."""
        app_data = struct.pack(">H", event_id) + action_tc_bytes
        return PusTcPacket(
            apid=tc_apid,
            sequence_count=sequence_count,
            service=19,
            subservice=1,
            app_data=app_data,
        )
