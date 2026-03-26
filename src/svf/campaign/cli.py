"""
SVF Campaign CLI
Entry point for running campaigns from the command line.
Usage: svf run campaigns/eps_validation.yaml
Implements: SVF-DEV-050
"""

from __future__ import annotations

import sys
from pathlib import Path


def run_campaign(campaign_path: str) -> int:
    """
    Run a campaign from a YAML file.
    Returns exit code: 0=all pass, 1=failures, 2=errors.
    """
    from svf.campaign.loader import CampaignLoader, CampaignLoadError
    from svf.campaign.executor import CampaignExecutor
    from svf.plugin.verdict import Verdict

    path = Path(campaign_path)
    try:
        loader = CampaignLoader()
        campaign = loader.load(path)
    except CampaignLoadError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    executor = CampaignExecutor()
    record = executor.run(campaign)

    print(f"\nCampaign: {record.campaign_id}")
    print(f"Baseline: {record.model_baseline}")
    print(f"Duration: {record.duration:.1f}s")
    print(f"\n{'ID':<16} {'Verdict':<14} {'Duration':>10}")
    print("-" * 44)
    for result in record.results:
        print(
            f"{result.id:<16} {result.verdict.value:<14} "
            f"{result.duration:>9.1f}s"
        )
    print("-" * 44)
    print(f"Overall: {record.overall_verdict.value}")

    if record.overall_verdict == Verdict.PASS:
        return 0
    elif record.overall_verdict == Verdict.FAIL:
        return 1
    else:
        return 2


def main() -> None:
    if len(sys.argv) < 3 or sys.argv[1] != "run":
        print("Usage: svf run <campaign.yaml>")
        sys.exit(2)
    sys.exit(run_campaign(sys.argv[2]))


if __name__ == "__main__":
    main()
