"""
SVF Campaign Executor
Runs a CampaignDefinition via pytest and produces a structured execution record.
Implements: SVF-DEV-050, SVF-DEV-051, SVF-DEV-054
"""

from __future__ import annotations

import importlib.metadata
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pytest

from svf.campaign.definitions import CampaignDefinition
from svf.plugin.verdict import Verdict

logger = logging.getLogger(__name__)


@dataclass
class TestCaseResult:
    """
    Execution result for a single test case.

    Attributes:
        id:          Test case ID (e.g. TC-PWR-001)
        test:        pytest node ID
        verdict:     ECSS verdict
        duration:    Wall-clock execution time in seconds
        error:       Error message if verdict is ERROR or FAIL
    """
    id: str
    test: str
    verdict: Verdict
    duration: float
    error: Optional[str] = None


@dataclass
class CampaignRecord:
    """
    Full execution record for a campaign run.

    Attributes:
        campaign_id:     Campaign identifier
        svf_version:     SVF version used
        model_baseline:  Model configuration baseline
        file_hash:       SHA-256 hash of the campaign YAML
        started_at:      UTC timestamp when campaign started
        finished_at:     UTC timestamp when campaign finished
        results:         Ordered list of test case results
    """
    campaign_id: str
    svf_version: str
    model_baseline: str
    file_hash: str
    started_at: str
    finished_at: str
    results: list[TestCaseResult] = field(default_factory=list)

    @property
    def duration(self) -> float:
        """Total campaign duration in seconds."""
        fmt = "%Y-%m-%dT%H:%M:%S.%f%z"
        start = datetime.strptime(self.started_at, fmt)
        end = datetime.strptime(self.finished_at, fmt)
        return (end - start).total_seconds()

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.verdict == Verdict.PASS)

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if r.verdict == Verdict.FAIL)

    @property
    def errors(self) -> int:
        return sum(1 for r in self.results if r.verdict == Verdict.ERROR)

    @property
    def inconclusive(self) -> int:
        return sum(
            1 for r in self.results if r.verdict == Verdict.INCONCLUSIVE
        )

    @property
    def overall_verdict(self) -> Verdict:
        """Overall campaign verdict — PASS only if all tests pass."""
        if any(r.verdict == Verdict.ERROR for r in self.results):
            return Verdict.ERROR
        if any(r.verdict == Verdict.FAIL for r in self.results):
            return Verdict.FAIL
        if any(r.verdict == Verdict.INCONCLUSIVE for r in self.results):
            return Verdict.INCONCLUSIVE
        return Verdict.PASS


class CampaignExecutor:
    """
    Runs a CampaignDefinition via pytest and returns a CampaignRecord.

    Each test case is run individually via pytest.main() so that:
    - Per-test-case timeouts can be enforced
    - Individual failures don't abort the campaign
    - Results are captured in order

    Usage:
        loader = CampaignLoader()
        campaign = loader.load(Path("campaigns/eps_validation.yaml"))

        executor = CampaignExecutor()
        record = executor.run(campaign)

        print(record.overall_verdict)
        for result in record.results:
            print(f"{result.id}: {result.verdict.value}")
    """

    def __init__(self, output_dir: Optional[Path] = None) -> None:
        self._output_dir = output_dir or Path("results")

    def run(self, campaign: CampaignDefinition) -> CampaignRecord:
        """
        Execute all test cases in the campaign in order.
        Returns a CampaignRecord regardless of individual test outcomes.
        """
        try:
            svf_version = importlib.metadata.version("opensvf")
        except importlib.metadata.PackageNotFoundError:
            svf_version = "dev"

        started_at = datetime.now(timezone.utc).isoformat()
        logger.info(
            f"Starting campaign '{campaign.campaign_id}' "
            f"({len(campaign.test_cases)} test cases)"
        )

        # Prepare output directory
        campaign_dir = self._output_dir / campaign.campaign_id
        campaign_dir.mkdir(parents=True, exist_ok=True)

        results: list[TestCaseResult] = []

        for tc in campaign.test_cases:
            logger.info(f"Running {tc.id}: {tc.test}")
            result = self._run_test_case(tc, campaign_dir)
            results.append(result)
            logger.info(f"{tc.id}: {result.verdict.value} ({result.duration:.1f}s)")

        finished_at = datetime.now(timezone.utc).isoformat()

        record = CampaignRecord(
            campaign_id=campaign.campaign_id,
            svf_version=svf_version,
            model_baseline=campaign.model_baseline,
            file_hash=campaign.file_hash,
            started_at=started_at,
            finished_at=finished_at,
            results=results,
        )

        logger.info(
            f"Campaign '{campaign.campaign_id}' complete: "
            f"{record.passed} PASS, {record.failed} FAIL, "
            f"{record.errors} ERROR — {record.overall_verdict.value}"
        )

        # Generate HTML report
        from svf.campaign.reporter import CampaignReporter
        reporter = CampaignReporter()
        report_path = reporter.generate(record, campaign, campaign_dir)
        logger.info(f"Report: {report_path}")

        return record

    def _run_test_case(
        self,
        tc: "TestCaseDefinition",  # type: ignore[name-defined]
        output_dir: Path,
    ) -> TestCaseResult:
        """Run a single test case and return its result."""
        from svf.campaign.definitions import TestCaseDefinition

        junit_xml = output_dir / f"{tc.id}.xml"
        start = time.monotonic()

        try:
            exit_code = pytest.main([
                tc.test,
                f"--timeout={tc.timeout}",
                f"--junit-xml={junit_xml}",
                "-q",
                "--tb=short",
            ])
        except Exception as e:
            duration = time.monotonic() - start
            return TestCaseResult(
                id=tc.id,
                test=tc.test,
                verdict=Verdict.ERROR,
                duration=duration,
                error=str(e),
            )

        duration = time.monotonic() - start

        if exit_code == pytest.ExitCode.OK:
            verdict = Verdict.PASS
            error = None
        elif exit_code == pytest.ExitCode.TESTS_FAILED:
            verdict = Verdict.FAIL
            error = "Test assertions failed"
        elif exit_code == pytest.ExitCode.INTERRUPTED:
            verdict = Verdict.ERROR
            error = f"Test interrupted (timeout={tc.timeout}s)"
        elif exit_code == pytest.ExitCode.NO_TESTS_COLLECTED:
            verdict = Verdict.ERROR
            error = f"No tests collected — check test node ID: {tc.test}"
        else:
            verdict = Verdict.ERROR
            error = f"pytest exit code: {exit_code}"

        return TestCaseResult(
            id=tc.id,
            test=tc.test,
            verdict=verdict,
            duration=duration,
            error=error,
        )
