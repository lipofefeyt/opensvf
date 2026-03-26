"""
Tests for CampaignExecutor.
Implements: SVF-DEV-050, SVF-DEV-051, SVF-DEV-054
"""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from svf.campaign.loader import CampaignLoader
from svf.campaign.executor import CampaignExecutor, CampaignRecord, TestCaseResult
from svf.plugin.verdict import Verdict


@pytest.fixture
def eps_campaign() -> "CampaignDefinition":  # type: ignore[name-defined]
    """Load the real EPS campaign."""
    from svf.campaign.definitions import CampaignDefinition
    loader = CampaignLoader()
    return loader.load(Path("campaigns/eps_validation.yaml"))


@pytest.mark.requirement("SVF-DEV-050", "SVF-DEV-051")
def test_executor_runs_all_test_cases(
    eps_campaign: "CampaignDefinition", tmp_path: Path  # type: ignore[name-defined]
) -> None:
    """Executor runs all test cases and returns a record with correct count."""
    with patch("svf.campaign.executor.pytest.main", return_value=pytest.ExitCode.OK):
        executor = CampaignExecutor(output_dir=tmp_path)
        record = executor.run(eps_campaign)

    assert record.campaign_id == "EPS-VAL-001"
    assert len(record.results) == 5


@pytest.mark.requirement("SVF-DEV-051")
def test_results_in_order(
    eps_campaign: "CampaignDefinition", tmp_path: Path  # type: ignore[name-defined]
) -> None:
    """Results are in campaign-defined order."""
    with patch("svf.campaign.executor.pytest.main", return_value=pytest.ExitCode.OK):
        executor = CampaignExecutor(output_dir=tmp_path)
        record = executor.run(eps_campaign)

    ids = [r.id for r in record.results]
    assert ids == ["TC-PWR-001", "TC-PWR-002", "TC-PWR-003",
                   "TC-PWR-004", "TC-PWR-005"]


@pytest.mark.requirement("SVF-DEV-053")
def test_record_metadata(
    eps_campaign: "CampaignDefinition", tmp_path: Path  # type: ignore[name-defined]
) -> None:
    """Campaign record captures metadata correctly."""
    with patch("svf.campaign.executor.pytest.main", return_value=pytest.ExitCode.OK):
        executor = CampaignExecutor(output_dir=tmp_path)
        record = executor.run(eps_campaign)

    assert record.model_baseline == "eps_integrated_v1"
    assert record.file_hash == eps_campaign.file_hash
    assert record.started_at != ""
    assert record.finished_at != ""
    assert record.duration > 0


@pytest.mark.requirement("SVF-DEV-054")
def test_overall_verdict_pass_when_all_pass(
    eps_campaign: "CampaignDefinition", tmp_path: Path  # type: ignore[name-defined]
) -> None:
    """Overall verdict is PASS when all test cases pass."""
    with patch("svf.campaign.executor.pytest.main", return_value=pytest.ExitCode.OK):
        executor = CampaignExecutor(output_dir=tmp_path)
        record = executor.run(eps_campaign)

    assert record.passed == 5
    assert record.failed == 0
    assert record.errors == 0
    assert record.overall_verdict == Verdict.PASS


@pytest.mark.requirement("SVF-DEV-054")
def test_overall_verdict_fail_when_one_fails(
    eps_campaign: "CampaignDefinition", tmp_path: Path  # type: ignore[name-defined]
) -> None:
    """Overall verdict is FAIL when any test case fails."""
    side_effects = [
        pytest.ExitCode.OK,
        pytest.ExitCode.TESTS_FAILED,
        pytest.ExitCode.OK,
        pytest.ExitCode.OK,
        pytest.ExitCode.OK,
    ]
    with patch("svf.campaign.executor.pytest.main", side_effect=side_effects):
        executor = CampaignExecutor(output_dir=tmp_path)
        record = executor.run(eps_campaign)

    assert record.failed == 1
    assert record.overall_verdict == Verdict.FAIL


@pytest.mark.requirement("SVF-DEV-054")
def test_overall_verdict_error_when_one_errors(
    eps_campaign: "CampaignDefinition", tmp_path: Path  # type: ignore[name-defined]
) -> None:
    """Overall verdict is ERROR when any test case errors."""
    side_effects = [
        pytest.ExitCode.OK,
        pytest.ExitCode.INTERRUPTED,
        pytest.ExitCode.OK,
        pytest.ExitCode.OK,
        pytest.ExitCode.OK,
    ]
    with patch("svf.campaign.executor.pytest.main", side_effect=side_effects):
        executor = CampaignExecutor(output_dir=tmp_path)
        record = executor.run(eps_campaign)

    assert record.errors == 1
    assert record.overall_verdict == Verdict.ERROR


@pytest.mark.requirement("SVF-DEV-054")
def test_individual_failure_does_not_abort_campaign(
    eps_campaign: "CampaignDefinition", tmp_path: Path  # type: ignore[name-defined]
) -> None:
    """A failed test case does not abort the remaining campaign."""
    side_effects = [
        pytest.ExitCode.TESTS_FAILED,
        pytest.ExitCode.OK,
        pytest.ExitCode.OK,
        pytest.ExitCode.OK,
        pytest.ExitCode.OK,
    ]
    with patch("svf.campaign.executor.pytest.main", side_effect=side_effects):
        executor = CampaignExecutor(output_dir=tmp_path)
        record = executor.run(eps_campaign)

    assert len(record.results) == 5
    assert record.results[0].verdict == Verdict.FAIL
    assert record.results[1].verdict == Verdict.PASS
