"""
SVF Campaign Definitions
Dataclasses for spacecraft test campaign definitions.
Implements: SVF-DEV-050, SVF-DEV-051
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class TestCaseDefinition:
    """
    A single test case within a campaign.

    Attributes:
        id:      Unique test case identifier (e.g. TC-PWR-001)
        test:    pytest node ID (e.g. tests/spacecraft/test_eps.py::test_tc_pwr_001)
        timeout: Maximum wall-clock execution time in seconds
    """
    id: str
    test: str
    timeout: int = 60

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("Test case id cannot be empty")
        if not self.test:
            raise ValueError("Test case test node cannot be empty")
        if self.timeout <= 0:
            raise ValueError(f"Timeout must be positive, got {self.timeout}")


@dataclass(frozen=True)
class CampaignDefinition:
    """
    A spacecraft test campaign definition.

    Attributes:
        campaign_id:     Unique campaign identifier (e.g. EPS-VAL-001)
        description:     Human-readable campaign description
        svf_version:     SVF version this campaign targets
        model_baseline:  Model configuration baseline identifier
        requirements:    Requirement IDs under verification
        test_cases:      Ordered list of test cases to execute
        file_hash:       SHA-256 hash of the source YAML file
        source_file:     Path to the source YAML file
    """
    campaign_id: str
    description: str
    svf_version: str
    model_baseline: str
    requirements: tuple[str, ...]
    test_cases: tuple[TestCaseDefinition, ...]
    file_hash: str
    source_file: Path

    def __post_init__(self) -> None:
        if not self.campaign_id:
            raise ValueError("campaign_id cannot be empty")
        if not self.test_cases:
            raise ValueError("Campaign must define at least one test case")

    @property
    def test_node_ids(self) -> list[str]:
        """Pytest node IDs for all test cases in order."""
        return [tc.test for tc in self.test_cases]

    def __str__(self) -> str:
        return (
            f"Campaign {self.campaign_id}: "
            f"{len(self.test_cases)} test cases, "
            f"{len(self.requirements)} requirements"
        )
