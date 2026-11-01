"""
Communication health between opensvf and a real flight software.

Counts what crossed the link and what became of it, so a run that could not
read the OBSW's telemetry or command it is visible at a glance: TM packets
received, parsed and dropped; TCs sent, accepted, completed and rejected
(by failure code); mode changes reported by the OBSW; sync losses.

Implements: SVF-DEV-214
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class LinkHealth:
    """Counters for one adapter session. All fields count since connection."""

    tm_received: int = 0
    tm_parsed: int = 0
    tm_dropped: int = 0
    last_drop_reason: Optional[str] = None
    tc_sent: int = 0
    tc_accepted: int = 0          # TM(1,1)
    tc_completed: int = 0         # TM(1,7)
    tc_rejected: dict[int, int] = field(default_factory=dict)   # code -> count, TM(1,2)/(1,8)
    mode_changes: list[tuple[float, int]] = field(default_factory=list)  # (sim time, mode)
    desyncs: int = 0

    @property
    def n_rejected(self) -> int:
        return sum(self.tc_rejected.values())

    @property
    def healthy(self) -> bool:
        """No TM was lost and the link never lost sync."""
        return self.tm_dropped == 0 and self.desyncs == 0

    def problems(self) -> list[str]:
        """Human-readable reasons why the link is not healthy."""
        out: list[str] = []
        if self.tm_dropped:
            out.append(f"{self.tm_dropped} of {self.tm_received} TM packets dropped"
                       f" ({self.last_drop_reason})")
        if self.desyncs:
            out.append(f"{self.desyncs} tick(s) without the OBSW sync byte")
        return out

    def summary(self, code_names: Optional[dict[int, str]] = None) -> str:
        """One line, e.g. for the console status or a campaign log."""
        names = code_names or {}
        rejected = ", ".join(
            f"0x{code:04X} {names.get(code, '?')} x{n}"
            for code, n in sorted(self.tc_rejected.items())
        ) or "none"
        return (f"TM {self.tm_parsed}/{self.tm_received} parsed, {self.tm_dropped} dropped | "
                f"TC {self.tc_sent} sent, {self.tc_accepted} accepted, "
                f"{self.tc_completed} completed, rejected: {rejected} | "
                f"mode changes {len(self.mode_changes)} | desyncs {self.desyncs}")

    def to_dict(self) -> dict[str, object]:
        return {
            "tm_received": self.tm_received,
            "tm_parsed": self.tm_parsed,
            "tm_dropped": self.tm_dropped,
            "last_drop_reason": self.last_drop_reason,
            "tc_sent": self.tc_sent,
            "tc_accepted": self.tc_accepted,
            "tc_completed": self.tc_completed,
            "tc_rejected": {f"0x{c:04X}": n for c, n in sorted(self.tc_rejected.items())},
            "mode_changes": [[t, m] for t, m in self.mode_changes],
            "desyncs": self.desyncs,
            "healthy": self.healthy,
        }
