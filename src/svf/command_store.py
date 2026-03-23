"""
SVF CommandStore
Thread-safe store for telecommands.
Architecturally separate from ParameterStore — TM and TC are never conflated.
Implements: SVF-DEV-035, SVF-DEV-036
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class CommandEntry:
    """
    A single telecommand stored in the CommandStore.

    Attributes:
        name:      The target parameter or command name.
        value:     The commanded value.
        t:         Simulation time at which the command was injected.
        source_id: ID of the issuing entity (test procedure, ground segment).
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
    via take() before each tick. TM and TC are never mixed — this store
    holds only commands, never telemetry outputs.

    The take() method is atomic: it reads and marks a command as consumed
    in a single operation, preventing double-application across ticks.

    Usage:
        store = CommandStore()

        # Test procedure (ground operator)
        store.inject("thruster_cmd", value=1.0, t=0.0, source_id="TC-001")

        # Model adapter (before doStep)
        entry = store.take("thruster_cmd")
        if entry is not None:
            fmu.setReal(vr, entry.value)
    """

    def __init__(self) -> None:
        self._store: dict[str, CommandEntry] = {}
        self._lock = threading.RLock()

    def inject(
        self,
        name: str,
        value: float,
        t: float = 0.0,
        source_id: str = "test_procedure",
    ) -> None:
        """
        Inject a command into the store.

        If a command for this name already exists and has not been consumed,
        it is overwritten — the latest command wins.

        Args:
            name:      Target parameter or command name
            value:     Commanded value
            t:         Simulation time of injection
            source_id: ID of the issuing entity
        """
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

        Returns the command entry if one exists and has not been consumed.
        Marks it as consumed immediately — subsequent calls return None
        until a new command is injected.

        Args:
            name: Command name to take

        Returns:
            CommandEntry if a fresh command exists, None otherwise.
        """
        with self._lock:
            entry = self._store.get(name)
            if entry is not None and not entry.consumed:
                entry.consumed = True
                logger.debug(f"Command taken: {name}={entry.value} from {entry.source_id}")
                return entry
            return None

    def peek(self, name: str) -> Optional[CommandEntry]:
        """
        Read a command without consuming it.

        Used for inspection and debugging — does not affect whether
        the command will be taken by a model adapter.

        Args:
            name: Command name to peek

        Returns:
            CommandEntry if one exists (consumed or not), None otherwise.
        """
        with self._lock:
            return self._store.get(name)

    def clear(self) -> None:
        """
        Clear all commands. Typically called between simulation runs.
        """
        with self._lock:
            self._store.clear()
        logger.debug("CommandStore cleared")

    def pending(self) -> list[str]:
        """
        Names of all commands that have been injected but not yet consumed.
        Useful for debugging and post-run inspection.
        """
        with self._lock:
            return [
                name for name, entry in self._store.items()
                if not entry.consumed
            ]

    def __len__(self) -> int:
        with self._lock:
            return len(self._store)