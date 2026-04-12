"""
SVF Monte Carlo Runner

Runs a simulation scenario N times with different seeds and collects
metrics from each run. Produces statistical summary: mean, std,
percentiles, pass rate.

Usage:
    from svf.monte_carlo import MonteCarloRunner, Metric

    def run_one(seed: int) -> dict:
        master, store, cmd_store = make_system(seed=seed)
        master.run()
        rate_x = store.read("aocs.truth.rate_x").value
        rate_y = store.read("aocs.truth.rate_y").value
        rate_z = store.read("aocs.truth.rate_z").value
        return {
            "final_rate": (rate_x**2 + rate_y**2 + rate_z**2) ** 0.5,
            "converged": final_rate < 1.0,
        }

    runner = MonteCarloRunner(run_one, n_runs=100, n_workers=4)
    results = runner.run()
    results.report()

Implements: SVF-DEV-090
"""
from __future__ import annotations

import json
import logging
import math
import statistics
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


@dataclass
class MonteCarloResult:
    """Results from a single Monte Carlo run."""
    seed:    int
    metrics: dict[str, Any]
    elapsed: float
    error:   Optional[str] = None

    @property
    def success(self) -> bool:
        return self.error is None


@dataclass
class MonteCarloSummary:
    """Statistical summary of all Monte Carlo runs."""
    n_runs:    int
    n_success: int
    n_failed:  int
    elapsed_total: float
    results:   list[MonteCarloResult] = field(default_factory=list)
    stats:     dict[str, dict[str, float]] = field(default_factory=dict)

    @property
    def success_rate(self) -> float:
        return self.n_success / self.n_runs if self.n_runs > 0 else 0.0

    def report(self, output_path: Optional[Path] = None) -> str:
        """Generate a text report of the Monte Carlo results."""
        lines = [
            "=" * 60,
            "SVF Monte Carlo Summary",
            "=" * 60,
            f"Runs:         {self.n_runs}",
            f"Success:      {self.n_success} ({self.success_rate*100:.1f}%)",
            f"Failed:       {self.n_failed}",
            f"Total time:   {self.elapsed_total:.1f}s",
            f"Time/run:     {self.elapsed_total/self.n_runs:.2f}s",
            "",
            "Metrics:",
            "-" * 60,
        ]

        for metric_name, stat in self.stats.items():
            lines.append(f"  {metric_name}:")
            lines.append(f"    mean:   {stat['mean']:.4f}")
            lines.append(f"    std:    {stat['std']:.4f}")
            lines.append(f"    min:    {stat['min']:.4f}")
            lines.append(f"    p25:    {stat['p25']:.4f}")
            lines.append(f"    median: {stat['median']:.4f}")
            lines.append(f"    p75:    {stat['p75']:.4f}")
            lines.append(f"    p95:    {stat['p95']:.4f}")
            lines.append(f"    max:    {stat['max']:.4f}")
            if "pass_rate" in stat:
                lines.append(f"    pass:   {stat['pass_rate']*100:.1f}%")
            lines.append("")

        if self.n_failed > 0:
            lines.append("Failed runs:")
            for r in self.results:
                if not r.success:
                    lines.append(f"  seed={r.seed}: {r.error}")

        report_str = "\n".join(lines)
        print(report_str)

        if output_path is not None:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(report_str)
            # Also save JSON
            json_path = output_path.with_suffix(".json")
            json_path.write_text(json.dumps({
                "n_runs": self.n_runs,
                "n_success": self.n_success,
                "success_rate": self.success_rate,
                "elapsed_total": self.elapsed_total,
                "stats": self.stats,
                "runs": [
                    {
                        "seed": r.seed,
                        "elapsed": r.elapsed,
                        "error": r.error,
                        "metrics": {
                            k: v for k, v in r.metrics.items()
                            if isinstance(v, (int, float, bool, str))
                        },
                    }
                    for r in self.results
                ],
            }, indent=2))
            logger.info(f"Monte Carlo results saved to {output_path}")

        return report_str


def _compute_stats(
    results: list[MonteCarloResult],
    metric_key: str,
    pass_threshold: Optional[float] = None,
    pass_below: bool = True,
) -> dict[str, float]:
    """Compute statistics for a single metric across all runs."""
    values = [
        r.metrics[metric_key]
        for r in results
        if r.success and metric_key in r.metrics
        and isinstance(r.metrics[metric_key], (int, float))
    ]
    if not values:
        return {}

    sorted_vals = sorted(values)
    n = len(sorted_vals)

    def percentile(p: float) -> float:
        idx = (p / 100) * (n - 1)
        lo, hi = int(idx), min(int(idx) + 1, n - 1)
        return float(sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (idx - lo))

    stat: dict[str, float] = {
        "mean":   statistics.mean(values),
        "std":    statistics.stdev(values) if len(values) > 1 else 0.0,
        "min":    sorted_vals[0],
        "p25":    percentile(25),
        "median": percentile(50),
        "p75":    percentile(75),
        "p95":    percentile(95),
        "max":    sorted_vals[-1],
        "count":  float(n),
    }

    if pass_threshold is not None:
        if pass_below:
            passed = sum(1 for v in values if v < pass_threshold)
        else:
            passed = sum(1 for v in values if v > pass_threshold)
        stat["pass_rate"] = passed / n

    return stat


class MonteCarloRunner:
    """
    Runs a simulation scenario N times with different seeds.

    Args:
        run_fn:      Function(seed: int) -> dict[str, Any]
                     Must return a dict of metric_name → value.
                     Should be importable (for multiprocessing).
        n_runs:      Number of Monte Carlo runs.
        base_seed:   Starting seed (runs use base_seed + i).
        n_workers:   Parallel workers (1 = sequential).
        pass_thresholds: {metric: (threshold, pass_below)} for pass/fail reporting.
    """

    def __init__(
        self,
        run_fn: Callable[[int], dict[str, Any]],
        n_runs: int = 100,
        base_seed: int = 0,
        n_workers: int = 1,
        pass_thresholds: Optional[dict[str, tuple[float, bool]]] = None,
    ) -> None:
        self._run_fn = run_fn
        self._n_runs = n_runs
        self._base_seed = base_seed
        self._n_workers = n_workers
        self._pass_thresholds = pass_thresholds or {}

    def run(
        self,
        output_path: Optional[Path] = None,
    ) -> MonteCarloSummary:
        """Run all Monte Carlo scenarios and return summary."""
        logger.info(
            f"Monte Carlo: {self._n_runs} runs, "
            f"{self._n_workers} workers, base_seed={self._base_seed}"
        )
        seeds = [self._base_seed + i for i in range(self._n_runs)]
        results: list[MonteCarloResult] = []
        t_start = time.monotonic()

        if self._n_workers == 1:
            # Sequential — simpler, better for debugging
            for i, seed in enumerate(seeds):
                result = self._run_one(seed)
                results.append(result)
                status = "OK" if result.success else f"FAIL: {result.error}"
                logger.info(
                    f"  Run {i+1}/{self._n_runs} seed={seed} "
                    f"t={result.elapsed:.1f}s {status}"
                )
        else:
            # Parallel via ProcessPoolExecutor
            with ProcessPoolExecutor(max_workers=self._n_workers) as executor:
                futures = {
                    executor.submit(self._run_one, seed): seed
                    for seed in seeds
                }
                for i, future in enumerate(as_completed(futures)):
                    result = future.result()
                    results.append(result)
                    status = "OK" if result.success else f"FAIL: {result.error}"
                    logger.info(
                        f"  Run {i+1}/{self._n_runs} seed={result.seed} "
                        f"t={result.elapsed:.1f}s {status}"
                    )

        elapsed_total = time.monotonic() - t_start

        # Compute stats
        successful = [r for r in results if r.success]
        all_metric_keys: set[str] = set()
        for r in successful:
            all_metric_keys.update(r.metrics.keys())

        stats: dict[str, dict[str, float]] = {}
        for key in sorted(all_metric_keys):
            threshold_info = self._pass_thresholds.get(key)
            if threshold_info:
                threshold, pass_below = threshold_info
                stats[key] = _compute_stats(
                    successful, key, threshold, pass_below
                )
            else:
                stats[key] = _compute_stats(successful, key)

        summary = MonteCarloSummary(
            n_runs=self._n_runs,
            n_success=len(successful),
            n_failed=len(results) - len(successful),
            elapsed_total=elapsed_total,
            results=results,
            stats=stats,
        )

        summary.report(output_path=output_path)
        return summary

    def _run_one(self, seed: int) -> MonteCarloResult:
        t0 = time.monotonic()
        try:
            metrics = self._run_fn(seed)
            return MonteCarloResult(
                seed=seed,
                metrics=metrics,
                elapsed=time.monotonic() - t0,
            )
        except Exception as e:
            return MonteCarloResult(
                seed=seed,
                metrics={},
                elapsed=time.monotonic() - t0,
                error=str(e),
            )
