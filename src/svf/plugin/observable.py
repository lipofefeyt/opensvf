"""
SVF Observable Assertion API
Fluent API for time-bounded telemetry assertions via ParameterStore polling.
Implements: SVF-DEV-043
"""

from __future__ import annotations

import logging
import time

from typing import Callable, Optional, cast, Any

from svf.parameter_store import ParameterStore

logger = logging.getLogger(__name__)


class ConditionNotMet(AssertionError):
    """Raised when an observable condition is not met within the timeout."""
    pass


class WithinClause:
    """
    Final clause of the observable assertion chain.
    Polls the ParameterStore until condition met or timeout expires.
    """

    def __init__(
        self,
        store: ParameterStore,
        variable: str,
        condition: Callable[[float], bool],
        condition_desc: str,
        session: Optional[Any] = None,  # SimulationSession reference
    ) -> None:
        self._store = store
        self._variable = variable
        self._condition = condition
        self._condition_desc = condition_desc
        self._session = session

    def within(self, seconds: float) -> float:
        deadline = time.monotonic() + seconds
        last_value: Optional[float] = None

        while time.monotonic() < deadline:
            entry = self._store.read(self._variable)
            if entry is not None:
                last_value = entry.value
                if self._condition(entry.value):
                    logger.info(
                        f"Observable [{self._variable}] "
                        f"{self._condition_desc}: "
                        f"got {entry.value} at t={entry.t:.3f}"
                    )
                    return entry.value

            # If simulation is done and condition still not met — fail fast
            if self._session is not None and self._session._done:
                break

            time.sleep(0.001)

        raise ConditionNotMet(
            f"Observable condition not met within {seconds}s: "
            f"{self._variable} {self._condition_desc} "
            f"(last value: {last_value})"
        )


class ReachesClause:
    """Intermediate clause — specifies the condition to wait for."""

    def __init__(
        self, store: ParameterStore, variable: str, session: Optional[Any] = None
    ) -> None:
        self._store = store
        self._variable = variable
        self._session = session

    def reaches(self, value: float, tolerance: float = 1e-6) -> WithinClause:
        return WithinClause(
            store=self._store,
            variable=self._variable,
            condition=lambda v: v >= value - tolerance,
            condition_desc=f"reaches {value}",
            session=self._session,
        )

    def exceeds(self, threshold: float) -> WithinClause:
        return WithinClause(
            store=self._store,
            variable=self._variable,
            condition=lambda v: v > threshold,
            condition_desc=f"exceeds {threshold}",
            session=self._session,
        )

    def drops_below(self, threshold: float) -> WithinClause:
        return WithinClause(
            store=self._store,
            variable=self._variable,
            condition=lambda v: v <= threshold,
            condition_desc=f"drops below {threshold}",
            session=self._session,
        )

    def satisfies(
        self,
        condition: Callable[[float], bool],
        description: str = "satisfies condition",
    ) -> WithinClause:
        return WithinClause(
            store=self._store,
            variable=self._variable,
            condition=condition,
            condition_desc=description,
            session=self._session,
        )


class ObservableFactory:
    """
    Entry point for the observable assertion API.
    Injected into test procedures via the svf_session fixture.

    Usage:
        def test_counter(svf_session):
            svf_session.observe("counter").reaches(1.0).within(2.0)
    """

    def __init__(self, store: ParameterStore, session: Optional[Any] = None) -> None:
        self._store = store
        self._session = session

    def __call__(self, variable: str) -> ReachesClause:
        return ReachesClause(
            store=self._store,
            variable=variable,
            session=self._session,
        )