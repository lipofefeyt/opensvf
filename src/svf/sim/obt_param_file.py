"""
SVF OBT Parameter File
Time-tagged parameter initialisation from a tab-delimited file.

File format (one entry per line):
    OBT<TAB>PARAM_NAME<TAB>VALUE

    # Lines beginning with '#' are ignored.
    # Blank lines are ignored.
    # OBT and VALUE must be numeric. PARAM_NAME is an arbitrary string.

Example:
    # Initial spacecraft state — replay from TM dump 2025-03-01T14:00:00Z
    0.0    eps.battery.soc              0.72
    0.0    aocs.rw1.speed_rpm           3200.0
    60.0   eps.solar_array.illumination 0.0

Implements: SVF-DEV-149
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ObtEntry:
    """Single time-tagged parameter entry."""
    obt: float
    name: str
    value: float


class ObtParamFile:
    """
    Parsed OBT parameter file, sorted ascending by OBT.

    Usage:
        obf = ObtParamFile.load("init.tsv")
        for entry in obf.entries_due(t=0.0, since=None):
            cmd_store.inject(entry.name, entry.value, t=0.0, source_id="obt_file")
    """

    def __init__(self, entries: list[ObtEntry]) -> None:
        self._entries = sorted(entries, key=lambda e: e.obt)
        self._next_index: int = 0

    @classmethod
    def load(cls, path: str | Path) -> "ObtParamFile":
        """
        Parse an OBT parameter file.

        Raises:
            FileNotFoundError: if the file does not exist
            ValueError: if any data line is malformed
        """
        path = Path(path)
        entries: list[ObtEntry] = []

        for lineno, raw in enumerate(path.read_text().splitlines(), start=1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue

            parts = line.split()
            if len(parts) != 3:
                raise ValueError(
                    f"{path}:{lineno}: expected 3 tab/space-separated fields "
                    f"(OBT PARAM_NAME VALUE), got {len(parts)}: {raw!r}"
                )

            obt_str, name, value_str = parts
            try:
                obt = float(obt_str)
            except ValueError:
                raise ValueError(
                    f"{path}:{lineno}: OBT column is not numeric: {obt_str!r}"
                )
            try:
                value = float(value_str)
            except ValueError:
                raise ValueError(
                    f"{path}:{lineno}: VALUE column is not numeric: {value_str!r}"
                )

            entries.append(ObtEntry(obt=obt, name=name, value=value))

        return cls(entries)

    def entries_due(self, t: float) -> list[ObtEntry]:
        """
        Return all entries whose OBT <= t that have not yet been returned.
        Advances the internal cursor so each entry is returned exactly once.
        """
        due: list[ObtEntry] = []
        while (
            self._next_index < len(self._entries)
            and self._entries[self._next_index].obt <= t
        ):
            due.append(self._entries[self._next_index])
            self._next_index += 1
        return due

    def reset(self) -> None:
        """Reset the cursor so all entries can be replayed."""
        self._next_index = 0

    @property
    def entries(self) -> list[ObtEntry]:
        """All entries in OBT order (read-only view)."""
        return list(self._entries)

    def __len__(self) -> int:
        return len(self._entries)
