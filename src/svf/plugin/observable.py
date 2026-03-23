"""
SVF Observable Assertion API
Fluent API for time-bounded telemetry assertions via ParameterStore polling.
Implements: SVF-DEV-043
"""

from __future__ import annotations

import logging
import time
from typing import Callable, Optional, cast

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
    ) -> None:
        self._store = store
        self._variable = variable
        self._condition = condition
        self._condition_desc = condition_desc

    def within(self, seconds: float) -> float:
        """
        Poll until condition met or timeout expires.

        Returns the value that satisfied the condition.
        Raises ConditionNotMet with a descriptive message on timeout.
        """
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
            time.sleep(0.001)

        raise ConditionNotMet(
            f"Observable condition not met within {seconds}s: "
            f"{self._variable} {self._condition_desc} "
            f"(last value: {last_value})"
        )


class ReachesClause:
    """Intermediate clause — specifies the condition to wait for."""

    def __init__(self, store: ParameterStore, variable: str) -> None:
        self._store = store
        self._variable = variable

    def reaches(self, value: float, tolerance: float = 1e-6) -> WithinClause:
        """Assert the variable reaches at least this value."""
        return WithinClause(
            store=self._store,
            variable=self._variable,
            condition=lambda v: v >= value - tolerance,
            condition_desc=f"reaches {value}",
    )

    def exceeds(self, threshold: float) -> WithinClause:
        """Assert the variable exceeds a threshold."""
        return WithinClause(
            store=self._store,
            variable=self._variable,
            condition=lambda v: v > threshold,
            condition_desc=f"exceeds {threshold}",
        )

    def drops_below(self, threshold: float) -> WithinClause:
        """Assert the variable drops to or below a threshold."""
        return WithinClause(
            store=self._store,
            variable=self._variable,
            condition=lambda v: v <= threshold,
            condition_desc=f"drops below {threshold}",
        )

    def satisfies(
        self,
        condition: Callable[[float], bool],
        description: str = "satisfies condition",
    ) -> WithinClause:
        """Assert the variable satisfies an arbitrary condition."""
        return WithinClause(
            store=self._store,
            variable=self._variable,
            condition=condition,
            condition_desc=description,
        )


class ObservableFactory:
    """
    Entry point for the observable assertion API.
    Injected into test procedures via the svf_session fixture.

    Usage:
        def test_counter(svf_session):
            svf_session.observe("counter").reaches(1.0).within(2.0)
    """

    def __init__(self, store: ParameterStore) -> None:
        self._store = store

    def __call__(self, variable: str) -> ReachesClause:
        """
        Begin an observable assertion for the named parameter.

        Args:
            variable: The parameter name (e.g. "counter")

        Returns:
            A ReachesClause to complete the assertion chain.
        """
        return ReachesClause(store=self._store, variable=variable)