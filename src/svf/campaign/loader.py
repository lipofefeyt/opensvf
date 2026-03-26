"""
SVF Campaign Loader
Parses YAML campaign definition files into typed CampaignDefinition objects.
Implements: SVF-DEV-050, SVF-DEV-051, SVF-DEV-052, SVF-DEV-053
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any

import yaml

from svf.campaign.definitions import CampaignDefinition, TestCaseDefinition

logger = logging.getLogger(__name__)


class CampaignLoadError(Exception):
    """Raised when campaign YAML parsing or validation fails."""
    pass


class CampaignLoader:
    """
    Loads and validates a campaign YAML file.

    Usage:
        loader = CampaignLoader()
        campaign = loader.load(Path("campaigns/eps_validation.yaml"))
        print(campaign.campaign_id)
        print(campaign.file_hash)
    """

    REQUIRED_FIELDS = [
        "campaign_id",
        "description",
        "svf_version",
        "model_baseline",
        "requirements",
        "test_cases",
    ]

    def load(self, path: Path) -> CampaignDefinition:
        """
        Load and validate a campaign YAML file.

        Records the SHA-256 hash of the file for audit trail.
        Raises CampaignLoadError on any schema or validation error.
        """
        logger.info(f"Loading campaign: {path}")

        if not path.exists():
            raise CampaignLoadError(f"Campaign file not found: {path}")

        raw_bytes = path.read_bytes()
        file_hash = hashlib.sha256(raw_bytes).hexdigest()

        try:
            raw = yaml.safe_load(raw_bytes.decode("utf-8"))
        except yaml.YAMLError as e:
            raise CampaignLoadError(f"{path}: YAML parse error: {e}") from e

        if not isinstance(raw, dict):
            raise CampaignLoadError(
                f"{path}: YAML root must be a mapping"
            )

        # Check required fields
        for field in self.REQUIRED_FIELDS:
            if field not in raw:
                raise CampaignLoadError(
                    f"{path}: missing required field '{field}'"
                )

        # Parse test cases
        raw_cases = raw["test_cases"]
        if not isinstance(raw_cases, list) or not raw_cases:
            raise CampaignLoadError(
                f"{path}: 'test_cases' must be a non-empty list"
            )

        test_cases = []
        seen_ids: set[str] = set()
        for i, case in enumerate(raw_cases):
            if not isinstance(case, dict):
                raise CampaignLoadError(
                    f"{path}: test_case at index {i} must be a mapping"
                )
            for required in ["id", "test"]:
                if required not in case:
                    raise CampaignLoadError(
                        f"{path}: test_case at index {i} "
                        f"missing required field '{required}'"
                    )
            tc_id = str(case["id"])
            if tc_id in seen_ids:
                raise CampaignLoadError(
                    f"{path}: duplicate test case id '{tc_id}'"
                )
            seen_ids.add(tc_id)

            try:
                test_cases.append(TestCaseDefinition(
                    id=tc_id,
                    test=str(case["test"]),
                    timeout=int(case.get("timeout", 60)),
                ))
            except ValueError as e:
                raise CampaignLoadError(
                    f"{path}: test_case '{tc_id}': {e}"
                ) from e

        # Parse requirements
        raw_reqs = raw["requirements"]
        if not isinstance(raw_reqs, list):
            raise CampaignLoadError(
                f"{path}: 'requirements' must be a list"
            )

        try:
            campaign = CampaignDefinition(
                campaign_id=str(raw["campaign_id"]),
                description=str(raw["description"]),
                svf_version=str(raw["svf_version"]),
                model_baseline=str(raw["model_baseline"]),
                requirements=tuple(str(r) for r in raw_reqs),
                test_cases=tuple(test_cases),
                file_hash=file_hash,
                source_file=path.resolve(),
            )
        except ValueError as e:
            raise CampaignLoadError(f"{path}: {e}") from e

        logger.info(
            f"Loaded campaign '{campaign.campaign_id}': "
            f"{len(test_cases)} test cases, "
            f"hash={file_hash[:8]}..."
        )
        return campaign
