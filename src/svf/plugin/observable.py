"""
SVF Observable Assertion API
Fluent API for time-bounded telemetry assertions via DDS subscriptions.
Implements: SVF-DEV-043
"""

from __future__ import annotations

import logging
import time
from typing import Callable, Optional, cast

from cyclonedds.domain import DomainParticipant
from cyclonedds.sub import Subscriber, DataReader
from cyclonedds.topic import Topic
from cyclonedds.core import Qos, Policy

from svf.fmu_adapter import TelemetrySample

logger = logging.getLogger(__name__)


class ConditionNotMet(AssertionError):
    """Raised when an observable condition is not met within the timeout."""
    pass


class WithinClause:
    """
    Final clause of the observable assertion chain.
    Blocks until the condition is met or timeout expires.

    Usage:
        observe("counter").reaches(1.0).within(2.0)
    """

    def __init__(
        self,
        reader: DataReader,  # type: ignore[type-arg]
        variable: str,
        condition: Callable[[float], bool],
        condition_desc: str,
    ) -> None:
        self._reader = reader
        self._variable = variable
        self._condition = condition
        self._condition_desc = condition_desc

    def within(self, seconds: float) -> float:
        """
        Block until the condition is met or timeout expires.

        Returns the value that satisfied the condition.
        Raises ConditionNotMet with a descriptive message on timeout.
        """
        deadline = time.monotonic() + seconds
        last_value: Optional[float] = None

        while time.monotonic() < deadline:
            samples = self._reader.take()
            for sample in samples:
                last_value = sample.value
                if self._condition(sample.value):
                    logger.info(
                        f"Observable [{self._variable}] "
                        f"{self._condition_desc}: "
                        f"got {sample.value} at t={sample.t:.3f}"
                    )
                    return cast(float, sample.value)
            time.sleep(0.001)

        raise ConditionNotMet(
            f"Observable condition not met within {seconds}s: "
            f"{self._variable} {self._condition_desc} "
            f"(last value: {last_value})"
        )


class ReachesClause:
    """
    Intermediate clause — specifies the condition to wait for.

    Usage:
        observe("counter").reaches(1.0).within(2.0)
        observe("counter").satisfies(lambda v: v > 0.5).within(2.0)
    """

    def __init__(
        self,
        reader: DataReader,  # type: ignore[type-arg]
        variable: str,
    ) -> None:
        self._reader = reader
        self._variable = variable

    def reaches(self, value: float, tolerance: float = 1e-6) -> WithinClause:
        """Assert the variable reaches a specific value."""
        return WithinClause(
            reader=self._reader,
            variable=self._variable,
            condition=lambda v: abs(v - value) <= tolerance,
            condition_desc=f"reaches {value} (±{tolerance})",
        )

    def exceeds(self, threshold: float) -> WithinClause:
        """Assert the variable exceeds a threshold."""
        return WithinClause(
            reader=self._reader,
            variable=self._variable,
            condition=lambda v: v > threshold,
            condition_desc=f"exceeds {threshold}",
        )

    def drops_below(self, threshold: float) -> WithinClause:
        """Assert the variable drops below a threshold."""
        return WithinClause(
            reader=self._reader,
            variable=self._variable,
            condition=lambda v: v < threshold,
            condition_desc=f"drops below {threshold}",
        )

    def satisfies(
        self, condition: Callable[[float], bool], description: str = "satisfies condition"
    ) -> WithinClause:
        """Assert the variable satisfies an arbitrary condition."""
        return WithinClause(
            reader=self._reader,
            variable=self._variable,
            condition=condition,
            condition_desc=description,
        )


class ObservableFactory:
    """
    Entry point for the observable assertion API.
    Injected into test procedures via the pytest fixture.

    Usage:
        def test_counter(simulation, observe):
            observe("counter").reaches(1.0).within(2.0)
    """

    TOPIC_PREFIX = "SVF/Telemetry/"

    def __init__(self, participant: DomainParticipant) -> None:
        self._participant = participant
        self._readers: dict[str, DataReader] = {}  # type: ignore[type-arg]

    def __call__(self, variable: str) -> ReachesClause:
        """
        Begin an observable assertion for the named telemetry variable.

        Args:
            variable: The telemetry variable name (e.g. "counter")

        Returns:
            A ReachesClause to complete the assertion chain.
        """
        if variable not in self._readers:
            subscriber = Subscriber(self._participant)
            topic = Topic(
                self._participant,
                f"{self.TOPIC_PREFIX}{variable}",
                TelemetrySample,
            )
            qos = Qos(Policy.History.KeepAll)
            self._readers[variable] = DataReader(subscriber, topic, qos=qos)
            time.sleep(0.05)  # Allow DDS discovery to settle

        return ReachesClause(
            reader=self._readers[variable],
            variable=variable,
        )
