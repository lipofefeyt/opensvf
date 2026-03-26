"""
Tests for CampaignReporter.
Implements: SVF-DEV-071, SVF-DEV-073, SVF-DEV-074, SVF-DEV-075
"""

import pytest
from pathlib import Path
from unittest.mock import patch
from svf.campaign.loader import CampaignLoader
from svf.campaign.executor import CampaignExecutor
from svf.campaign.executor import CampaignRecord
from svf.campaign.reporter import CampaignReporter
from svf.campaign.definitions import CampaignDefinition


@pytest.fixture
def campaign_record(tmp_path: Path) -> tuple[CampaignRecord, CampaignDefinition]:
    """Run campaign with mocked pytest and return record + campaign."""
    loader = CampaignLoader()
    campaign = loader.load(Path("campaigns/eps_validation.yaml"))
    with patch("svf.campaign.executor.pytest.main", return_value=pytest.ExitCode.OK):
        executor = CampaignExecutor(output_dir=tmp_path)
        record = executor.run(campaign)
    return record, campaign


@pytest.mark.requirement("SVF-DEV-075")
def test_report_generated(
    campaign_record: tuple[CampaignRecord, CampaignDefinition], tmp_path: Path
) -> None:
    """HTML report is generated in output directory."""
    record, campaign = campaign_record
    reporter = CampaignReporter()
    report_path = reporter.generate(record, campaign, tmp_path)
    assert report_path.exists()
    assert report_path.suffix == ".html"


@pytest.mark.requirement("SVF-DEV-074")
def test_report_contains_metadata(
    campaign_record: tuple[CampaignRecord, CampaignDefinition], tmp_path: Path
) -> None:
    """Report contains campaign metadata."""
    record, campaign = campaign_record
    reporter = CampaignReporter()
    report_path = reporter.generate(record, campaign, tmp_path)
    content = report_path.read_text()
    assert "EPS-VAL-001" in content
    assert "eps_integrated_v1" in content
    assert record.file_hash in content


@pytest.mark.requirement("SVF-DEV-073")
def test_report_contains_requirements(
    campaign_record: tuple[CampaignRecord, CampaignDefinition], tmp_path: Path
) -> None:
    """Report contains requirements traceability table."""
    record, campaign = campaign_record
    reporter = CampaignReporter()
    report_path = reporter.generate(record, campaign, tmp_path)
    content = report_path.read_text()
    assert "EPS-011" in content
    assert "EPS-012" in content
    assert "EPS-013" in content


@pytest.mark.requirement("SVF-DEV-071")
def test_report_contains_verdicts(
    campaign_record: tuple[CampaignRecord, CampaignDefinition], tmp_path: Path
) -> None:
    """Report contains ECSS verdict for each test case."""
    record, campaign = campaign_record
    reporter = CampaignReporter()
    report_path = reporter.generate(record, campaign, tmp_path)
    content = report_path.read_text()
    assert "TC-PWR-001" in content
    assert "PASS" in content


@pytest.mark.requirement("SVF-DEV-075")
def test_report_is_self_contained(
    campaign_record: tuple[CampaignRecord, CampaignDefinition], tmp_path: Path
) -> None:
    """Report has no external dependencies — no external CSS or JS links."""
    record, campaign = campaign_record
    reporter = CampaignReporter()
    report_path = reporter.generate(record, campaign, tmp_path)
    content = report_path.read_text()
    assert 'href="http' not in content
    assert 'src="http' not in content
