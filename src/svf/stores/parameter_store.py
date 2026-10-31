"""
SVF ParameterStore
Thread-safe central state store for all simulation outputs.
Optionally validates writes against SRDB definitions.
Implements: SVF-DEV-031, SVF-DEV-032, SVF-DEV-033, SVF-DEV-094, SVF-DEV-095
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, Optional

if TYPE_CHECKING:
    from svf.srdb.loader import Srdb
    from svf.srdb.definitions import Classification

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
    read from here on demand, or subscribe() to see every write of one
    parameter (temporal monitors do, so no value is missed between polls).

    Optionally accepts an Srdb instance for runtime validation:
      - Warns when a value falls outside valid_range
      - Warns when a TC-classified parameter is written by a model

    Warnings are logged, never raised as exceptions  -  the simulation
    continues regardless of validation findings.

    Usage:
        store = ParameterStore()                          # no validation
        store = ParameterStore(srdb=loaded_srdb)          # with validation
    """

    def __init__(self, srdb: Optional[Srdb] = None) -> None:
        self._store: dict[str, ParameterEntry] = {}
        self._lock = threading.RLock()
        self._srdb = srdb
        self._subscribers: dict[str, list[Callable[[ParameterEntry], None]]] = {}

    def write(
        self,
        name: str,
        value: float,
        t: float,
        model_id: str,
    ) -> None:
        """
        Write a parameter value to the store.

        If an SRDB is configured, validates:
          - Value is within valid_range (warning if violated)
          - Parameter is TM-classified (warning if TC written by model)

        Args:
            name:     Parameter name (SRDB canonical name preferred)
            value:    Current value
            t:        Simulation time of this write
            model_id: ID of the writing model
        """
        if self._srdb is not None:
            defn = self._srdb.get(name)
            if defn is not None:
                # Check TM/TC classification
                from svf.srdb.definitions import Classification
                if defn.classification == Classification.TC:
                    logger.warning(
                        f"[SRDB] Model '{model_id}' wrote to TC-classified "
                        f"parameter '{name}'  -  TM/TC separation violation"
                    )
                # Check valid range
                if not defn.is_in_range(value):
                    lo, hi = defn.valid_range  # type: ignore[misc]
                    logger.warning(
                        f"[SRDB] Parameter '{name}' value {value} is outside "
                        f"valid range [{lo}, {hi}] "
                        f"(written by model '{model_id}' at t={t:.3f})"
                    )
            else:
                logger.debug(
                    f"[SRDB] Parameter '{name}' not found in SRDB "
                    f"(written by '{model_id}')"
                )

        entry = ParameterEntry(value=value, t=t, model_id=model_id)
        with self._lock:
            self._store[name] = entry
            subscribers = list(self._subscribers.get(name, ()))
        # Called outside the lock, in the writer's thread, once per write.
        for callback in subscribers:
            callback(entry)
        logger.debug(f"[{model_id}] {name}={value} at t={t:.3f}")

    def subscribe(
        self, name: str, callback: Callable[[ParameterEntry], None]
    ) -> Callable[[], None]:
        """
        Call ``callback(entry)`` on every write of ``name``, in the writer's
        thread. Returns a function that removes the subscription.

        Implements: SVF-DEV-213
        """
        with self._lock:
            self._subscribers.setdefault(name, []).append(callback)

        def unsubscribe() -> None:
            with self._lock:
                callbacks = self._subscribers.get(name, [])
                if callback in callbacks:
                    callbacks.remove(callback)

        return unsubscribe

    def read(self, name: str) -> Optional[ParameterEntry]:
        """
        Read the last written value of a parameter.
        Returns None if the parameter has never been written.
        """
        with self._lock:
            return self._store.get(name)

    def snapshot(self) -> dict[str, ParameterEntry]:
        """Return a full copy of the current store state."""
        with self._lock:
            return dict(self._store)

    def clear(self) -> None:
        """Clear all parameter values."""
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
