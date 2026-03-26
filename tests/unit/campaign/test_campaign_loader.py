"""
Tests for CampaignLoader and CampaignDefinition.
Implements: SVF-DEV-050, SVF-DEV-051, SVF-DEV-052, SVF-DEV-053
"""

import pytest
from pathlib import Path
from svf.campaign.loader import CampaignLoader, CampaignLoadError
from svf.campaign.definitions import CampaignDefinition, TestCaseDefinition

VALID_YAML = """
campaign_id: EPS-VAL-001
description: EPS validation campaign
svf_version: "0.1"
model_baseline: eps_integrated_v1
requirements:
  - EPS-011
  - EPS-012
test_cases:
  - id: TC-PWR-001
    test: tests/spacecraft/test_eps.py::test_tc_pwr_001
    timeout: 60
  - id: TC-PWR-002
    test: tests/spacecraft/test_eps.py::test_tc_pwr_002
    timeout: 60
"""


@pytest.fixture
def valid_campaign_file(tmp_path: Path) -> Path:
    f = tmp_path / "campaign.yaml"
    f.write_text(VALID_YAML)
    return f


# ── CampaignLoader tests ──────────────────────────────────────────────────────

@pytest.mark.requirement("SVF-DEV-050", "SVF-DEV-051")
def test_load_valid_campaign(valid_campaign_file: Path) -> None:
    """Valid campaign YAML loads correctly."""
    loader = CampaignLoader()
    campaign = loader.load(valid_campaign_file)
    assert campaign.campaign_id == "EPS-VAL-001"
    assert campaign.description == "EPS validation campaign"
    assert campaign.svf_version == "0.1"
    assert campaign.model_baseline == "eps_integrated_v1"
    assert len(campaign.test_cases) == 2
    assert len(campaign.requirements) == 2


@pytest.mark.requirement("SVF-DEV-053")
def test_file_hash_recorded(valid_campaign_file: Path) -> None:
    """SHA-256 hash of campaign file is recorded."""
    import hashlib
    loader = CampaignLoader()
    campaign = loader.load(valid_campaign_file)
    expected = hashlib.sha256(valid_campaign_file.read_bytes()).hexdigest()
    assert campaign.file_hash == expected


@pytest.mark.requirement("SVF-DEV-053")
def test_source_file_recorded(valid_campaign_file: Path) -> None:
    """Source file path is recorded."""
    loader = CampaignLoader()
    campaign = loader.load(valid_campaign_file)
    assert campaign.source_file == valid_campaign_file.resolve()


@pytest.mark.requirement("SVF-DEV-051")
def test_test_cases_ordered(valid_campaign_file: Path) -> None:
    """Test cases are in declared order."""
    loader = CampaignLoader()
    campaign = loader.load(valid_campaign_file)
    assert campaign.test_cases[0].id == "TC-PWR-001"
    assert campaign.test_cases[1].id == "TC-PWR-002"


@pytest.mark.requirement("SVF-DEV-051")
def test_test_node_ids(valid_campaign_file: Path) -> None:
    """test_node_ids returns pytest node IDs in order."""
    loader = CampaignLoader()
    campaign = loader.load(valid_campaign_file)
    assert campaign.test_node_ids[0] == "tests/spacecraft/test_eps.py::test_tc_pwr_001"


@pytest.mark.requirement("SVF-DEV-051")
def test_default_timeout(tmp_path: Path) -> None:
    """Default timeout is 60 seconds when not specified."""
    f = tmp_path / "campaign.yaml"
    f.write_text("""
campaign_id: TEST-001
description: test
svf_version: "0.1"
model_baseline: test
requirements: [EPS-001]
test_cases:
  - id: TC-001
    test: tests/test_something.py::test_it
""")
    loader = CampaignLoader()
    campaign = loader.load(f)
    assert campaign.test_cases[0].timeout == 60


# ── Error handling tests ──────────────────────────────────────────────────────

@pytest.mark.requirement("SVF-DEV-052")
def test_missing_file_raises(tmp_path: Path) -> None:
    """Missing file raises CampaignLoadError."""
    loader = CampaignLoader()
    with pytest.raises(CampaignLoadError, match="not found"):
        loader.load(tmp_path / "nonexistent.yaml")


@pytest.mark.requirement("SVF-DEV-052")
def test_missing_required_field_raises(tmp_path: Path) -> None:
    """Missing required field raises CampaignLoadError."""
    f = tmp_path / "bad.yaml"
    f.write_text("""
campaign_id: TEST-001
description: test
""")
    loader = CampaignLoader()
    with pytest.raises(CampaignLoadError, match="missing required field"):
        loader.load(f)


@pytest.mark.requirement("SVF-DEV-052")
def test_empty_test_cases_raises(tmp_path: Path) -> None:
    """Empty test_cases list raises CampaignLoadError."""
    f = tmp_path / "bad.yaml"
    f.write_text("""
campaign_id: TEST-001
description: test
svf_version: "0.1"
model_baseline: test
requirements: [EPS-001]
test_cases: []
""")
    loader = CampaignLoader()
    with pytest.raises(CampaignLoadError, match="non-empty"):
        loader.load(f)


@pytest.mark.requirement("SVF-DEV-052")
def test_duplicate_test_case_id_raises(tmp_path: Path) -> None:
    """Duplicate test case ID raises CampaignLoadError."""
    f = tmp_path / "bad.yaml"
    f.write_text("""
campaign_id: TEST-001
description: test
svf_version: "0.1"
model_baseline: test
requirements: [EPS-001]
test_cases:
  - id: TC-001
    test: tests/test.py::test_a
  - id: TC-001
    test: tests/test.py::test_b
""")
    loader = CampaignLoader()
    with pytest.raises(CampaignLoadError, match="duplicate"):
        loader.load(f)


@pytest.mark.requirement("SVF-DEV-052")
def test_invalid_timeout_raises(tmp_path: Path) -> None:
    """Negative timeout raises CampaignLoadError."""
    f = tmp_path / "bad.yaml"
    f.write_text("""
campaign_id: TEST-001
description: test
svf_version: "0.1"
model_baseline: test
requirements: [EPS-001]
test_cases:
  - id: TC-001
    test: tests/test.py::test_a
    timeout: -1
""")
    loader = CampaignLoader()
    with pytest.raises(CampaignLoadError, match="Timeout"):
        loader.load(f)


@pytest.mark.requirement("SVF-DEV-050", "SVF-DEV-051")
def test_load_real_eps_campaign() -> None:
    """Real EPS campaign YAML loads cleanly."""
    campaign_file = Path("campaigns/eps_validation.yaml")
    loader = CampaignLoader()
    campaign = loader.load(campaign_file)
    assert campaign.campaign_id == "EPS-VAL-001"
    assert len(campaign.test_cases) == 5
    assert "EPS-011" in campaign.requirements
