"""PUS Service 11 — Time-Based Scheduling."""

from __future__ import annotations

import struct
from dataclasses import dataclass

from svf.pus.tc import PusTcPacket


@dataclass
class ScheduledActivity:
    """A single entry in the on-board time-based schedule."""
    request_id: int
    time_tag: float
    tc_bytes: bytes


class TimeBasedScheduler:
    """
    On-board time-based schedule.

    Holds a sorted list of ``ScheduledActivity`` items. On each OBT tick
    ``ObcEquipment`` calls ``due(obt)`` to drain and fire any overdue TCs.
    """

    def __init__(self) -> None:
        self._activities: list[ScheduledActivity] = []
        self._next_id: int = 1
        self._enabled: bool = True

    def insert(self, time_tag: float, tc_bytes: bytes) -> int:
        """Schedule *tc_bytes* to fire at *time_tag* seconds OBT. Returns request_id."""
        rid = self._next_id
        self._next_id += 1
        self._activities.append(ScheduledActivity(rid, time_tag, tc_bytes))
        self._activities.sort(key=lambda a: a.time_tag)
        return rid

    def delete(self, request_id: int) -> bool:
        """Delete a scheduled activity. Returns True if found and removed."""
        before = len(self._activities)
        self._activities = [a for a in self._activities if a.request_id != request_id]
        return len(self._activities) < before

    def delete_all(self) -> int:
        """Remove all scheduled activities. Returns count removed."""
        n = len(self._activities)
        self._activities.clear()
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
        return len(self._activities)

    def due(self, obt: float) -> list[bytes]:
        """Return and remove TC bytes for all activities with time_tag <= *obt*."""
        if not self._enabled:
            return []
        due = [a for a in self._activities if a.time_tag <= obt]
        if due:
            due_ids = {a.request_id for a in due}
            self._activities = [a for a in self._activities if a.request_id not in due_ids]
        return [a.tc_bytes for a in due]


class PusService11:
    """
    PUS Service 11 — Time-Based Scheduling.

    TC(11,4)  — Insert Activity (time-tagged TC)
    TC(11,5)  — Delete Activity by request_id
    TC(11,6)  — Delete All Activities
    TC(11,17) — Enable Schedule
    TC(11,18) — Disable Schedule

    TC(11,4) app_data format (SVF pragmatic subset):
        4B CUC coarse time tag  (big-endian uint32)
        2B CUC fine time tag    (big-endian uint16, 1/65536 s)
        N B embedded TC frame
    """

    @staticmethod
    def is_insert(tc: PusTcPacket) -> bool:
        return tc.service == 11 and tc.subservice == 4

    @staticmethod
    def is_delete(tc: PusTcPacket) -> bool:
        return tc.service == 11 and tc.subservice == 5

    @staticmethod
    def is_delete_all(tc: PusTcPacket) -> bool:
        return tc.service == 11 and tc.subservice == 6

    @staticmethod
    def is_enable(tc: PusTcPacket) -> bool:
        return tc.service == 11 and tc.subservice == 17

    @staticmethod
    def is_disable(tc: PusTcPacket) -> bool:
        return tc.service == 11 and tc.subservice == 18

    @staticmethod
    def parse_insert(tc: PusTcPacket) -> tuple[float, bytes]:
        """
        Parse TC(11,4) app_data.
        Returns (time_tag_seconds, embedded_tc_bytes).
        """
        if len(tc.app_data) < 7:
            raise ValueError(
                f"TC(11,4) app_data too short: {len(tc.app_data)} bytes (need ≥7)"
            )
        coarse: int
        fine: int
        coarse, fine = struct.unpack_from(">IH", tc.app_data)
        time_tag = coarse + fine / 65536.0
        return time_tag, bytes(tc.app_data[6:])

    @staticmethod
    def parse_delete(tc: PusTcPacket) -> int:
        """Parse TC(11,5) app_data → request_id."""
        if len(tc.app_data) < 2:
            raise ValueError(
                f"TC(11,5) app_data too short: {len(tc.app_data)} bytes (need 2)"
            )
        rid: int
        rid, = struct.unpack_from(">H", tc.app_data)
        return rid

    @staticmethod
    def build_insert(
        time_tag: float,
        embedded_tc_bytes: bytes,
        tc_apid: int = 0x100,
        sequence_count: int = 0,
    ) -> PusTcPacket:
        """Build TC(11,4) wrapping *embedded_tc_bytes* with a CUC-4,2 time tag."""
        coarse = int(time_tag)
        fine = int((time_tag - coarse) * 65536) & 0xFFFF
        app_data = struct.pack(">IH", coarse, fine) + embedded_tc_bytes
        return PusTcPacket(
            apid=tc_apid,
            sequence_count=sequence_count,
            service=11,
            subservice=4,
            app_data=app_data,
        )
