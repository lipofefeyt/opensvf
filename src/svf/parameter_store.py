"""
SVF ParameterStore
Thread-safe central state store for all simulation outputs.
Models write to it after each tick. Observables and loggers read from it.
Implements: SVF-DEV-031, SVF-DEV-032, SVF-DEV-033
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ParameterEntry:
    """
    A single parameter value recorded in the store.

    Attributes:
        value:    The parameter value at the time of writing.
        t:        Simulation time at which the value was written.
        model_id: ID of the model that wrote this value.
    """
    value: float
    t: float
    model_id: str


class ParameterStore:
    """
    Thread-safe central state store for simulation parameters.

    Models write outputs here after each tick. Observables and loggers
    read from here on demand. No subscriber registration required —
    any reader always gets the last written value regardless of when
    it first connects.

    This eliminates the late-joiner problem inherent in pure pub/sub
    approaches: a reader that connects after a value was written still
    sees that value.

    Usage:
        store = ParameterStore()

        # Writer (model adapter)
        store.write("battery_voltage", value=3.7, t=0.1, model_id="power")

        # Reader (observable, logger)
        entry = store.read("battery_voltage")
        if entry is not None:
            print(entry.value, entry.t, entry.model_id)

        # Snapshot (CSV logger, reporting)
        current_state = store.snapshot()
    """

    def __init__(self) -> None:
        self._store: dict[str, ParameterEntry] = {}
        self._lock = threading.RLock()

    def write(
        self,
        name: str,
        value: float,
        t: float,
        model_id: str,
    ) -> None:
        """
        Write a parameter value to the store.

        Args:
            name:     Parameter name (e.g. "battery_voltage")
            value:    Current value
            t:        Simulation time of this write
            model_id: ID of the writing model
        """
        with self._lock:
            self._store[name] = ParameterEntry(
                value=value,
                t=t,
                model_id=model_id,
            )
        logger.debug(f"[{model_id}] {name}={value} at t={t:.3f}")

    def read(self, name: str) -> Optional[ParameterEntry]:
        """
        Read the last written value of a parameter.

        Returns None if the parameter has never been written.
        Returns the last written entry regardless of when it was written.

        Args:
            name: Parameter name to read
        """
        with self._lock:
            return self._store.get(name)

    def snapshot(self) -> dict[str, ParameterEntry]:
        """
        Return a full copy of the current store state.

        Used by CsvLogger to record a consistent state at each tick,
        and by reporting tools to capture simulation state at a point in time.
        """
        with self._lock:
            return dict(self._store)

    def clear(self) -> None:
        """
        Clear all parameter values.
        Typically called between simulation runs.
        """
        with self._lock:
            self._store.clear()
        logger.debug("ParameterStore cleared")

    @property
    def parameter_names(self) -> list[str]:
        """Names of all parameters currently in the store."""
        with self._lock:
            return list(self._store.keys())

    def __len__(self) -> int:
        with self._lock:
            return len(self._store)
