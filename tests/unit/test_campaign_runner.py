"""Tests for CampaignRunner."""
from __future__ import annotations
import pytest
import yaml
from pathlib import Path
from svf.campaign.procedure import (
    Procedure, ProcedureContext, Verdict,
    ProcedureError, ProcedureInconclusiveError, ProcedureResult,
)
from svf.campaign.campaign_runner import CampaignRunner, CampaignReport


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


class InconclusiveProc(Procedure):
    id = "TC-CAMP-003"
    title = "Inconclusive procedure"
    requirement = "REQ-003"
    def run(self, ctx: ProcedureContext) -> None:
        self.step("Data not available")
        raise ProcedureInconclusiveError("sensor data not available")


EXAMPLES = Path(__file__).parent.parent.parent / "mission_mysat1"


class TestCampaignRunnerSuite:

    @pytest.mark.requirement("SVF-DEV-050", "SVF-DEV-051", "SVF-DEV-121")
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

    @pytest.mark.requirement("SVF-DEV-050", "SVF-DEV-121")
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

    @pytest.mark.requirement("SVF-DEV-054", "SVF-DEV-121")
    def test_pass_rate_computed(self) -> None:
        """Pass rate is correctly computed."""
        runner = CampaignRunner(
            campaign_name="Test Campaign",
            spacecraft_cfg=EXAMPLES / "spacecraft.yaml",
            procedures=[PassProc, PassProc, FailProc],
        )
        report = runner.run()
        assert report.pass_rate == pytest.approx(2/3, abs=0.01)

    @pytest.mark.requirement("SVF-DEV-052", "SVF-DEV-053", "SVF-DEV-121")
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

    @pytest.mark.requirement("SVF-DEV-157")
    def test_inconclusive_counted(self) -> None:
        """INCONCLUSIVE verdict from ProcedureInconclusiveError is counted."""
        runner = CampaignRunner(
            campaign_name="Test",
            spacecraft_cfg=EXAMPLES / "spacecraft.yaml",
            procedures=[InconclusiveProc],
        )
        report = runner.run()
        assert report.n_inconclusive == 1
        assert report.n_pass == 0
        assert report.n_fail == 0
        assert report.n_error == 0

    @pytest.mark.requirement("SVF-DEV-157")
    def test_inconclusive_verdict_in_result(self) -> None:
        """ProcedureResult has INCONCLUSIVE verdict when raised."""
        runner = CampaignRunner(
            campaign_name="Test",
            spacecraft_cfg=EXAMPLES / "spacecraft.yaml",
            procedures=[InconclusiveProc],
        )
        report = runner.run()
        assert report.results[0].verdict == Verdict.INCONCLUSIVE

    @pytest.mark.requirement("SVF-DEV-158")
    def test_declared_requirements_uncovered(self) -> None:
        """Declared requirement with no covering procedure appears as uncovered."""
        runner = CampaignRunner(
            campaign_name="Test",
            spacecraft_cfg=EXAMPLES / "spacecraft.yaml",
            procedures=[PassProc],
            declared_requirements=["REQ-001", "REQ-999"],
        )
        report = runner.run()
        assert "REQ-999" in report.uncovered_requirements
        assert "REQ-001" not in report.uncovered_requirements

    @pytest.mark.requirement("SVF-DEV-158")
    def test_all_declared_covered(self) -> None:
        """No uncovered requirements when all declared are exercised."""
        runner = CampaignRunner(
            campaign_name="Test",
            spacecraft_cfg=EXAMPLES / "spacecraft.yaml",
            procedures=[PassProc],
            declared_requirements=["REQ-001"],
        )
        report = runner.run()
        assert report.uncovered_requirements == []

    @pytest.mark.requirement("SVF-DEV-157", "SVF-DEV-158")
    def test_to_dict_includes_steps_and_new_fields(self) -> None:
        """to_dict() includes steps, n_inconclusive, declared/uncovered requirements."""
        runner = CampaignRunner(
            campaign_name="Test",
            spacecraft_cfg=EXAMPLES / "spacecraft.yaml",
            procedures=[PassProc],
            declared_requirements=["REQ-001", "REQ-MISSING"],
        )
        report = runner.run()
        d = report.to_dict()
        assert "n_inconclusive" in d
        assert "declared_requirements" in d
        assert "uncovered_requirements" in d
        assert "REQ-MISSING" in d["uncovered_requirements"]
        assert d["results"][0]["steps"] is not None


# ── CampaignReport unit tests (no simulation) ─────────────────────────────────

class TestCampaignReportUnit:

    @pytest.mark.requirement("SVF-DEV-158")
    def test_uncovered_requirements_property(self) -> None:
        """uncovered_requirements = declared - any procedure with that requirement."""
        report = CampaignReport(
            campaign_name="Test",
            spacecraft="spacecraft.yaml",
            n_procedures=1,
            n_pass=1,
            n_fail=0,
            n_error=0,
            duration_s=0.1,
            declared_requirements=["MIS-001", "MIS-002", "MIS-003"],
            results=[
                ProcedureResult(
                    procedure_id="TC-001", title="T", requirement="MIS-001",
                    verdict=Verdict.PASS, duration_s=0.1,
                ),
            ],
        )
        uncovered = report.uncovered_requirements
        assert "MIS-002" in uncovered
        assert "MIS-003" in uncovered
        assert "MIS-001" not in uncovered

    @pytest.mark.requirement("SVF-DEV-158")
    def test_failed_requirement_not_uncovered(self) -> None:
        """A FAILED procedure counts as 'attempted'  -  not UNCOVERED."""
        report = CampaignReport(
            campaign_name="Test",
            spacecraft="spacecraft.yaml",
            n_procedures=1,
            n_pass=0,
            n_fail=1,
            n_error=0,
            duration_s=0.1,
            declared_requirements=["MIS-001"],
            results=[
                ProcedureResult(
                    procedure_id="TC-001", title="T", requirement="MIS-001",
                    verdict=Verdict.FAIL, duration_s=0.1,
                ),
            ],
        )
        assert report.uncovered_requirements == []

    @pytest.mark.requirement("SVF-DEV-158")
    def test_from_yaml_loads_requirements(self, tmp_path: Path) -> None:
        """CampaignRunner.from_yaml() reads 'requirements:' from campaign YAML."""
        sc_path = EXAMPLES / "spacecraft.yaml"
        campaign_yaml = tmp_path / "campaign.yaml"
        campaign_yaml.write_text(
            f"campaign: Test\n"
            f"spacecraft: {sc_path}\n"
            f"procedures: []\n"
            f"requirements:\n  - MIS-AOCS-001\n  - MIS-POWER-001\n"
        )
        runner = CampaignRunner.from_yaml(campaign_yaml)
        assert "MIS-AOCS-001" in runner._declared_requirements
        assert "MIS-POWER-001" in runner._declared_requirements
