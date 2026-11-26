"""
L3: the first campaign on the integrate-obsw docs page, run as written
against the real openobsw obsw_sim.

The example files in docs/examples/integrate-obsw/ are copied to a temporary
directory with obsw_sim as bin/my_obsw, the name the page tells the reader
to use, and run through the same CampaignRunner as `svf campaign`.

Implements: SVF-DEV-222
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from svf.campaign.campaign_runner import CampaignRunner
from svf.campaign.procedure import Verdict

_repo = Path(__file__).parent.parent.parent
_example = _repo / "docs" / "examples" / "integrate-obsw"
_candidates = [
    Path(p) for p in (os.environ.get("OBSW_SIM"),) if p
] + [
    _repo / "bin" / "obsw_sim",
    _repo.parent / "openobsw" / "build" / "sim" / "obsw_sim",
]
OBSW_SIM = next((p for p in _candidates if p.exists()), _candidates[0])

pytestmark = pytest.mark.skipif(
    not OBSW_SIM.exists(), reason=f"obsw_sim not found at {OBSW_SIM}"
)


@pytest.mark.requirement("SVF-DEV-222")
def test_integrate_obsw_example_campaign_passes(tmp_path: Path) -> None:
    mission = tmp_path / "my_mission"
    shutil.copytree(_example, mission)
    (mission / "bin").mkdir()
    shutil.copy2(OBSW_SIM, mission / "bin" / "my_obsw")

    report = CampaignRunner.from_yaml(mission / "campaign.yaml").run()

    assert [r.procedure_id for r in report.results] == ["TC-INT-001"]
    result = report.results[0]
    assert result.verdict == Verdict.PASS, result.error
    assert report.uncovered_requirements == []
    assert result.link is not None
    assert result.link["tm_dropped"] == 0
    assert result.link["tm_parsed"] > 0
