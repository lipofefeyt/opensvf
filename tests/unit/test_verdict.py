"""
Tests for ECSS verdict mapper.
Implements: SVF-DEV-044
"""

import pytest
from svf.plugin.verdict import Verdict, VerdictRecorder, verdict_from_pytest_outcome


@pytest.mark.requirement("SVF-DEV-044")
def test_verdict_pass() -> None:
    assert verdict_from_pytest_outcome(passed=True, failed=False) == Verdict.PASS


@pytest.mark.requirement("SVF-DEV-044")
def test_verdict_fail() -> None:
    assert verdict_from_pytest_outcome(passed=False, failed=True) == Verdict.FAIL


@pytest.mark.requirement("SVF-DEV-044")
def test_verdict_error() -> None:
    assert verdict_from_pytest_outcome(
        passed=False, failed=False, error=RuntimeError("boom")
    ) == Verdict.ERROR


@pytest.mark.requirement("SVF-DEV-044")
def test_verdict_inconclusive() -> None:
    assert verdict_from_pytest_outcome(passed=False, failed=False) == Verdict.INCONCLUSIVE


@pytest.mark.requirement("SVF-DEV-044")
def test_verdict_recorder_records() -> None:
    recorder = VerdictRecorder()
    recorder.record("TC-001", Verdict.PASS)
    assert recorder.get("TC-001") == Verdict.PASS


@pytest.mark.requirement("SVF-DEV-044")
def test_verdict_recorder_summary() -> None:
    recorder = VerdictRecorder()
    recorder.record("TC-001", Verdict.PASS)
    recorder.record("TC-002", Verdict.FAIL)
    recorder.record("TC-003", Verdict.PASS)
    summary = recorder.summary
    assert summary["PASS"] == 2
    assert summary["FAIL"] == 1
    assert summary["INCONCLUSIVE"] == 0
    assert summary["ERROR"] == 0


@pytest.mark.requirement("SVF-DEV-044")
def test_verdict_recorder_unknown_test() -> None:
    recorder = VerdictRecorder()
    assert recorder.get("nonexistent") is None
