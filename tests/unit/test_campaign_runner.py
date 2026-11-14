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


# ── Step events in the campaign JSON (SVF-DEV-218) ────────────────────────────

class EventfulProc(Procedure):
    id = "TC-CAMP-004"
    title = "Procedure that records events"
    requirement = "REQ-004"
    def run(self, ctx: ProcedureContext) -> None:
        self.step("Inject and wait")
        ctx.inject("eps.solar_array.illumination", 1.0)
        ctx.wait(0.2)
        self.step("Second step")


def _report_with_events() -> CampaignReport:
    from svf.campaign.procedure import EventType, SimEvent, StepResult
    steps = [
        StepResult("Bind the limit", Verdict.PASS, events=[
            SimEvent(1.0, EventType.STEP, "Bind the limit"),
            SimEvent(1.1, EventType.COMMAND, "Sent TC(12,3) to obc", details="1810c001"),
            SimEvent(1.2, EventType.TELEMETRY, "Received TM(1,7)"),
        ]),
        StepResult("Drive the fault", Verdict.FAIL, detail="limit not crossed", events=[
            SimEvent(2.0, EventType.INJECTION, "Set dhs.obc.temperature_raw = 1300.0"),
            SimEvent(2.5, EventType.MONITOR, "Active invariant: dhs.obc.mode"),
            SimEvent(3.0, EventType.INFO, "Waiting 1.0s (until t=4.0s)"),
        ]),
        StepResult("No events here", Verdict.PASS),
    ]
    result = ProcedureResult(procedure_id="TC-EV-001", title="Events", requirement="REQ-EV",
                             verdict=Verdict.FAIL, duration_s=1.0, steps=steps)
    return CampaignReport(campaign_name="Events", spacecraft="sc.yaml", n_procedures=1,
                          n_pass=0, n_fail=1, n_error=0, duration_s=1.0, results=[result])


class StepEventsJsonSuite:

    @pytest.mark.requirement("SVF-DEV-218")
    def test_to_dict_serialises_step_events_in_order(self) -> None:
        steps = _report_with_events().to_dict()["results"][0]["steps"]  # type: ignore[index]
        assert [s["name"] for s in steps] == ["Bind the limit", "Drive the fault", "No events here"]
        assert steps[0]["events"] == [
            {"t": 1.0, "type": "STEP", "description": "Bind the limit", "details": None},
            {"t": 1.1, "type": "TC", "description": "Sent TC(12,3) to obc", "details": "1810c001"},
            {"t": 1.2, "type": "TM", "description": "Received TM(1,7)", "details": None},
        ]
        assert [e["type"] for e in steps[1]["events"]] == ["INJECT", "MONITOR", "INFO"]
        assert [e["t"] for e in steps[1]["events"]] == [2.0, 2.5, 3.0]

    @pytest.mark.requirement("SVF-DEV-218")
    def test_step_without_events_has_an_empty_list(self) -> None:
        steps = _report_with_events().to_dict()["results"][0]["steps"]  # type: ignore[index]
        assert steps[2] == {"name": "No events here", "verdict": "PASS", "detail": "",
                            "events": []}

    @pytest.mark.requirement("SVF-DEV-218")
    def test_existing_step_fields_are_unchanged(self) -> None:
        step = _report_with_events().to_dict()["results"][0]["steps"][1]  # type: ignore[index]
        assert (step["name"], step["verdict"], step["detail"]) == (
            "Drive the fault", "FAIL", "limit not crossed")

    @pytest.mark.requirement("SVF-DEV-218")
    def test_events_survive_a_json_round_trip(self) -> None:
        """What the CLI writes with json.dumps reads back identical: plain types only."""
        import json
        d = _report_with_events().to_dict()
        assert json.loads(json.dumps(d)) == d

    @pytest.mark.requirement("SVF-DEV-218", "SVF-DEV-121")
    def test_events_of_a_real_run_reach_the_json(self) -> None:
        """Events a procedure records through ProcedureContext, not hand-built ones."""
        import json
        report = CampaignRunner(
            campaign_name="Events",
            spacecraft_cfg=EXAMPLES / "spacecraft.yaml",
            procedures=[EventfulProc],
        ).run()
        assert report.results[0].verdict == Verdict.PASS, report.results[0].error
        steps = json.loads(json.dumps(report.to_dict()))["results"][0]["steps"]
        assert [s["name"] for s in steps] == ["Inject and wait", "Second step"]
        first = steps[0]["events"]
        assert [e["type"] for e in first][:2] == ["STEP", "INJECT"]
        assert first[1]["description"] == "Set eps.solar_array.illumination = 1.0"
        assert any(e["type"] == "INFO" and e["description"].startswith("Waiting 0.2s")
                   for e in first)
        assert all(isinstance(e["t"], float) for e in first)
        assert [e["t"] for e in first] == sorted(e["t"] for e in first)
        assert steps[1]["events"][0]["type"] == "STEP"
        # The serialised timeline is the one the HTML report renders.
        recorded = report.results[0].steps[0].events
        assert [(e["t"], e["type"], e["description"]) for e in first] == [
            (e.t, e.event_type.value, e.description) for e in recorded]
