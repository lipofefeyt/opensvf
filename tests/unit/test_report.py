"""Tests for HTML report generator."""
from __future__ import annotations
import pytest
from pathlib import Path
from svf.campaign.procedure import Procedure, ProcedureContext, Verdict, ProcedureResult
from svf.campaign.campaign_runner import CampaignReport
from svf.campaign.reporter import generate_html_report


def make_report(n_pass: int = 2, n_fail: int = 1) -> CampaignReport:
    results = []
    for i in range(n_pass):
        results.append(ProcedureResult(
            procedure_id=f"TC-PASS-{i+1:03d}",
            title=f"Passing procedure {i+1}",
            requirement=f"REQ-{i+1:03d}",
            verdict=Verdict.PASS,
            duration_s=1.5,
        ))
    for i in range(n_fail):
        results.append(ProcedureResult(
            procedure_id=f"TC-FAIL-{i+1:03d}",
            title=f"Failing procedure {i+1}",
            requirement=f"REQ-{n_pass+i+1:03d}",
            verdict=Verdict.FAIL,
            duration_s=0.5,
            error="Parameter out of range",
        ))
    return CampaignReport(
        campaign_name="MySat-1 AOCS Validation",
        spacecraft="spacecraft.yaml",
        n_procedures=n_pass+n_fail,
        n_pass=n_pass,
        n_fail=n_fail,
        n_error=0,
        duration_s=10.0,
        results=results,
    )


class TestReportSuite:

    @pytest.mark.requirement("SVF-DEV-122")
    def test_generates_html_file(self, tmp_path: Path) -> None:
        """generate_html_report creates an HTML file."""
        report = make_report()
        out = generate_html_report(report, tmp_path / "report.html")
        assert out.exists()
        assert out.suffix == ".html"

    @pytest.mark.requirement("SVF-DEV-122")
    def test_html_contains_campaign_name(self, tmp_path: Path) -> None:
        """Report HTML includes campaign name."""
        report = make_report()
        out = generate_html_report(report, tmp_path / "report.html")
        content = out.read_text()
        assert "MySat-1 AOCS Validation" in content

    @pytest.mark.requirement("SVF-DEV-122")
    def test_html_contains_procedure_ids(self, tmp_path: Path) -> None:
        """Report HTML includes all procedure IDs."""
        report = make_report(n_pass=2, n_fail=1)
        out = generate_html_report(report, tmp_path / "report.html")
        content = out.read_text()
        assert "TC-PASS-001" in content
        assert "TC-PASS-002" in content
        assert "TC-FAIL-001" in content

    @pytest.mark.requirement("SVF-DEV-122")
    def test_html_contains_verdicts(self, tmp_path: Path) -> None:
        """Report HTML includes PASS and FAIL verdicts."""
        report = make_report(n_pass=1, n_fail=1)
        out = generate_html_report(report, tmp_path / "report.html")
        content = out.read_text()
        assert "PASS" in content
        assert "FAIL" in content

    @pytest.mark.requirement("SVF-DEV-122")
    def test_html_contains_requirements(self, tmp_path: Path) -> None:
        """Report HTML includes requirement coverage table."""
        report = make_report()
        out = generate_html_report(report, tmp_path / "report.html")
        content = out.read_text()
        assert "REQ-001" in content
        assert "Requirement Coverage" in content

    @pytest.mark.requirement("SVF-DEV-122")
    def test_html_is_self_contained(self, tmp_path: Path) -> None:
        """Report HTML has no external dependencies."""
        report = make_report()
        out = generate_html_report(report, tmp_path / "report.html")
        content = out.read_text()
        assert "cdn." not in content
        assert "http" not in content.lower().replace("https://github", "")

    @pytest.mark.requirement("SVF-DEV-122")
    def test_creates_parent_directory(self, tmp_path: Path) -> None:
        """Report creates parent directories if needed."""
        report = make_report()
        out = generate_html_report(
            report, tmp_path / "nested" / "dir" / "report.html"
        )
        assert out.exists()
