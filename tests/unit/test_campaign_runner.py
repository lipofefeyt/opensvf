"""Tests for CampaignRunner."""
from __future__ import annotations
import pytest
from pathlib import Path
from svf.procedure import Procedure, ProcedureContext, Verdict
from svf.campaign_runner import CampaignRunner, CampaignReport


class PassProc(Procedure):
    id = "TC-CAMP-001"
    title = "Passing procedure"
    requirement = "REQ-001"
    def run(self, ctx: ProcedureContext) -> None:
        self.step("Always passes")


class FailProc(Procedure):
    id = "TC-CAMP-002"
    title = "Failing procedure"
    requirement = "REQ-002"
    def run(self, ctx: ProcedureContext) -> None:
        self.step("Always fails")
        ctx.assert_parameter("nonexistent", less_than=1.0)


EXAMPLES = Path(__file__).parent.parent.parent / "examples"


class TestCampaignRunnerSuite:

    @pytest.mark.requirement("SVF-DEV-121")
    def test_campaign_runs_all_procedures(self) -> None:
        """Campaign runs all procedures and collects results."""
        runner = CampaignRunner(
            campaign_name="Test Campaign",
            spacecraft_cfg=EXAMPLES / "spacecraft.yaml",
            procedures=[PassProc, FailProc],
        )
        report = runner.run()
        assert report.n_procedures == 2
        assert len(report.results) == 2

    @pytest.mark.requirement("SVF-DEV-121")
    def test_campaign_counts_verdicts(self) -> None:
        """Campaign correctly counts pass/fail/error."""
        runner = CampaignRunner(
            campaign_name="Test Campaign",
            spacecraft_cfg=EXAMPLES / "spacecraft.yaml",
            procedures=[PassProc, FailProc],
        )
        report = runner.run()
        assert report.n_pass == 1
        assert report.n_fail == 1

    @pytest.mark.requirement("SVF-DEV-121")
    def test_failure_does_not_stop_campaign(self) -> None:
        """A failing procedure does not stop subsequent procedures."""
        runner = CampaignRunner(
            campaign_name="Test Campaign",
            spacecraft_cfg=EXAMPLES / "spacecraft.yaml",
            procedures=[FailProc, PassProc],
        )
        report = runner.run()
        # Both ran
        assert report.n_procedures == 2
        verdicts = [r.verdict for r in report.results]
        assert Verdict.FAIL in verdicts
        assert Verdict.PASS in verdicts

    @pytest.mark.requirement("SVF-DEV-121")
    def test_pass_rate_computed(self) -> None:
        """Pass rate is correctly computed."""
        runner = CampaignRunner(
            campaign_name="Test Campaign",
            spacecraft_cfg=EXAMPLES / "spacecraft.yaml",
            procedures=[PassProc, PassProc, FailProc],
        )
        report = runner.run()
        assert report.pass_rate == pytest.approx(2/3, abs=0.01)

    @pytest.mark.requirement("SVF-DEV-121")
    def test_report_to_dict(self) -> None:
        """CampaignReport.to_dict() returns serialisable dict."""
        runner = CampaignRunner(
            campaign_name="Test Campaign",
            spacecraft_cfg=EXAMPLES / "spacecraft.yaml",
            procedures=[PassProc],
        )
        report = runner.run()
        d = report.to_dict()
        assert d["campaign"] == "Test Campaign"
        assert d["pass_rate"] == pytest.approx(1.0)
        assert len(d["results"]) == 1

    @pytest.mark.requirement("SVF-DEV-121")
    def test_json_output(self, tmp_path: Path) -> None:
        """Campaign saves JSON results when output_path provided."""
        runner = CampaignRunner(
            campaign_name="Test Campaign",
            spacecraft_cfg=EXAMPLES / "spacecraft.yaml",
            procedures=[PassProc],
        )
        out = tmp_path / "report.json"
        runner.run(output_path=out)
        assert out.exists()
        import json
        data = json.loads(out.read_text())
        assert data["n_procedures"] == 1
