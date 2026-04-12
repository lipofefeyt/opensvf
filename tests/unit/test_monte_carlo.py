"""Tests for MonteCarloRunner infrastructure."""
from __future__ import annotations
import math
import pytest
from svf.monte_carlo import MonteCarloRunner, MonteCarloResult, MonteCarloSummary


def _simple_run(seed: int) -> dict:
    """Deterministic test function — result depends on seed."""
    import random
    rng = random.Random(seed)
    value = rng.gauss(5.0, 1.0)
    return {
        "value": value,
        "converged": 1.0 if value < 6.5 else 0.0,
    }


def _failing_run(seed: int) -> dict:
    if seed % 3 == 0:
        raise RuntimeError("Simulated failure")
    return {"value": float(seed)}


class TestMonteCarloSuite:

    @pytest.mark.requirement("SVF-DEV-090")
    def test_runs_correct_count(self) -> None:
        """Runner executes exactly n_runs simulations."""
        runner = MonteCarloRunner(_simple_run, n_runs=10, base_seed=0)
        summary = runner.run()
        assert summary.n_runs == 10
        assert len(summary.results) == 10

    @pytest.mark.requirement("SVF-DEV-090")
    def test_different_seeds_give_different_results(self) -> None:
        """Different seeds produce different metric values."""
        runner = MonteCarloRunner(_simple_run, n_runs=10, base_seed=0)
        summary = runner.run()
        values = [r.metrics["value"] for r in summary.results if r.success]
        assert len(set(f"{v:.6f}" for v in values)) > 1

    @pytest.mark.requirement("SVF-DEV-090")
    def test_stats_computed_correctly(self) -> None:
        """Statistical summary contains mean, std, percentiles."""
        runner = MonteCarloRunner(_simple_run, n_runs=20, base_seed=42)
        summary = runner.run()
        assert "value" in summary.stats
        stat = summary.stats["value"]
        assert "mean" in stat
        assert "std" in stat
        assert "p95" in stat
        assert stat["min"] <= stat["median"] <= stat["max"]

    @pytest.mark.requirement("SVF-DEV-090")
    def test_pass_rate_computed(self) -> None:
        """Pass rate computed when threshold provided."""
        runner = MonteCarloRunner(
            _simple_run, n_runs=50, base_seed=0,
            pass_thresholds={"value": (6.5, True)}
        )
        summary = runner.run()
        assert "pass_rate" in summary.stats["value"]
        assert 0.0 <= summary.stats["value"]["pass_rate"] <= 1.0

    @pytest.mark.requirement("SVF-DEV-090")
    def test_failed_runs_counted(self) -> None:
        """Failed runs are counted separately, not included in stats."""
        runner = MonteCarloRunner(_failing_run, n_runs=9, base_seed=0)
        summary = runner.run()
        assert summary.n_failed == 3  # seeds 0, 3, 6 fail
        assert summary.n_success == 6

    @pytest.mark.requirement("SVF-DEV-090")
    def test_report_generates_string(self, tmp_path) -> None:  # type: ignore
        """Report generates valid string output."""
        runner = MonteCarloRunner(_simple_run, n_runs=5, base_seed=0)
        summary = runner.run(output_path=tmp_path / "report.txt")
        assert (tmp_path / "report.txt").exists()
        assert (tmp_path / "report.json").exists()
        content = (tmp_path / "report.txt").read_text()
        assert "Monte Carlo Summary" in content
        assert "mean" in content
