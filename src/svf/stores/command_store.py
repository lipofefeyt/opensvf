"""
SVF CommandStore
Thread-safe store for telecommands.
Optionally validates inject() against SRDB definitions.
Implements: SVF-DEV-035, SVF-DEV-036, SVF-DEV-095
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from svf.srdb.loader import Srdb

logger = logging.getLogger(__name__)


@dataclass
class CommandEntry:
    """
    A single telecommand stored in the CommandStore.

    Attributes:
        name:      The target parameter or command name.
        value:     The commanded value.
        t:         Simulation time at which the command was injected.
        source_id: ID of the issuing entity.
        consumed:  True if the command has been taken by a model adapter.
    """
    name: str
    value: float
    t: float
    source_id: str
    consumed: bool = False


class CommandStore:
    """
    Thread-safe store for telecommands.

    Test procedures inject commands here. Model adapters consume them
    via take() before each tick. Architecturally separate from
    ParameterStore — TM and TC are never mixed.

    Optionally accepts an Srdb instance for runtime validation:
      - Warns when a TM-classified parameter is injected as a command

    Warnings are logged, never raised — the command is still stored.
    """

    def __init__(self, srdb: Optional[Srdb] = None) -> None:
        self._store: dict[str, CommandEntry] = {}
        self._lock = threading.RLock()
        self._srdb = srdb

    def inject(
        self,
        name: str,
        value: float,
        t: float = 0.0,
        source_id: str = "test_procedure",
    ) -> None:
        """
        Inject a command into the store.

        If an SRDB is configured, warns when injecting to a
        TM-classified parameter.

        Args:
            name:      Target parameter or command name
            value:     Commanded value
            t:         Simulation time of injection
            source_id: ID of the issuing entity
        """
        if self._srdb is not None:
            defn = self._srdb.get(name)
            if defn is not None:
                from svf.srdb.definitions import Classification
                if defn.classification == Classification.TM:
                    logger.warning(
                        f"[SRDB] '{source_id}' injected command to "
                        f"TM-classified parameter '{name}' — "
                        f"TM/TC separation violation"
                    )
                if defn.valid_range is not None:
                    if not defn.is_in_range(value):
                        lo, hi = defn.valid_range
                        logger.warning(
                            f"[SRDB] Command value {value} for '{name}' "
                            f"is outside valid range [{lo}, {hi}]"
                        )
            else:
                logger.debug(
                    f"[SRDB] Command parameter '{name}' not found in SRDB"
                )

        with self._lock:
            self._store[name] = CommandEntry(
                name=name,
                value=value,
                t=t,
                source_id=source_id,
                consumed=False,
            )
        logger.info(f"[{source_id}] Command injected: {name}={value} at t={t:.3f}")

    def take(self, name: str) -> Optional[CommandEntry]:
        """
        Atomically read and consume a command.
        Returns None if no fresh command exists.
        """
        with self._lock:
            entry = self._store.get(name)
            if entry is not None and not entry.consumed:
                entry.consumed = True
                logger.debug(f"Command taken: {name}={entry.value} from {entry.source_id}")
                return entry
            return None

    def peek(self, name: str) -> Optional[CommandEntry]:
        """Read a command without consuming it."""
        with self._lock:
            return self._store.get(name)

    def clear(self) -> None:
        """Clear all commands."""
        with self._lock:
            self._store.clear()
        logger.debug("CommandStore cleared")

    def pending(self) -> list[str]:
        """Names of all unconsumed commands."""
        with self._lock:
            return [
                name for name, entry in self._store.items()
                if not entry.consumed
            ]

    def __len__(self) -> int:
        with self._lock:
            return len(self._store)
