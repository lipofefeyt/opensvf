"""
SVF ECSS Verdict Mapper
Maps pytest outcomes to ECSS-compatible test verdicts.
Implements: SVF-DEV-044
"""

from __future__ import annotations

import enum
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class Verdict(enum.Enum):
    """
    ECSS-E-ST-10-02C compatible test verdict values.

    PASS        — test executed and all conditions were met
    FAIL        — test executed and at least one condition was not met
    INCONCLUSIVE — test executed but the result cannot be determined
    ERROR       — test could not be executed due to an infrastructure fault
    """
    PASS = "PASS"
    FAIL = "FAIL"
    INCONCLUSIVE = "INCONCLUSIVE"
    ERROR = "ERROR"


def verdict_from_pytest_outcome(
    passed: bool,
    failed: bool,
    error: Optional[Exception] = None,
) -> Verdict:
    """
    Derive an ECSS verdict from a pytest test outcome.

    Args:
        passed: True if the test passed
        failed: True if the test failed (assertion error)
        error:  Exception if the test errored (infrastructure fault)

    Returns:
        The corresponding ECSS Verdict value.
    """
    if error is not None:
        return Verdict.ERROR
    if failed:
        return Verdict.FAIL
    if passed:
        return Verdict.PASS
    return Verdict.INCONCLUSIVE


class VerdictRecorder:
    """
    Records test verdicts for reporting.
    Populated by the pytest plugin hook after each test.
    """

    def __init__(self) -> None:
        self._verdicts: dict[str, Verdict] = {}

    def record(self, test_id: str, verdict: Verdict) -> None:
        """Record a verdict for a test case."""
        self._verdicts[test_id] = verdict
        logger.info(f"Verdict [{verdict.value}]: {test_id}")

    def get(self, test_id: str) -> Optional[Verdict]:
        """Retrieve the verdict for a test case."""
        return self._verdicts.get(test_id)

    @property
    def all(self) -> dict[str, Verdict]:
        """All recorded verdicts."""
        return dict(self._verdicts)

    @property
    def summary(self) -> dict[str, int]:
        """Count of each verdict type."""
        counts: dict[str, int] = {v.value: 0 for v in Verdict}
        for verdict in self._verdicts.values():
            counts[verdict.value] += 1
        return counts
