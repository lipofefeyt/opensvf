"""
L1 checks of the example files the docs include (docs/examples/), without a
flight software binary. The L3 suite runs the same files against obsw_sim
(tests/system/test_integrate_obsw_example.py).

Implements: SVF-DEV-222
"""
from __future__ import annotations

from pathlib import Path

import pytest

from svf.campaign.campaign_runner import CampaignRunner
from svf.config.validator import SpacecraftValidator

_EXAMPLE = Path(__file__).parents[2] / "docs" / "examples" / "integrate-obsw"


@pytest.mark.requirement("SVF-DEV-222")
def test_integrate_obsw_example_spacecraft_validates() -> None:
    issues = SpacecraftValidator.from_file(_EXAMPLE / "spacecraft.yaml")
    assert issues == []


@pytest.mark.requirement("SVF-DEV-222")
def test_integrate_obsw_example_campaign_loads_its_procedure() -> None:
    runner = CampaignRunner.from_yaml(_EXAMPLE / "campaign.yaml")
    procs = runner._procedures
    assert [p.id for p in procs] == ["TC-INT-001"]
    assert runner._declared_requirements == [procs[0].requirement]
    assert runner._spacecraft_cfg.name == "spacecraft.yaml"
