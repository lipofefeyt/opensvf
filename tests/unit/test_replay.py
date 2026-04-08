"""
Tests for deterministic replay seed management.
Implements: SVF-DEV-038
"""

import pytest
from pathlib import Path
from svf.replay import SeedManager, derive_seed, generate_seed


@pytest.mark.requirement("SVF-DEV-038")
def test_derive_seed_is_deterministic() -> None:
    """Same master + model_id always gives same seed."""
    assert derive_seed(42, "mag") == derive_seed(42, "mag")
    assert derive_seed(42, "gyro") == derive_seed(42, "gyro")


@pytest.mark.requirement("SVF-DEV-038")
def test_derive_seed_differs_per_model() -> None:
    """Different model_ids get different seeds."""
    assert derive_seed(42, "mag") != derive_seed(42, "gyro")
    assert derive_seed(42, "mag") != derive_seed(42, "css")


@pytest.mark.requirement("SVF-DEV-038")
def test_derive_seed_differs_per_master() -> None:
    """Different master seeds give different per-model seeds."""
    assert derive_seed(42, "mag") != derive_seed(43, "mag")


@pytest.mark.requirement("SVF-DEV-038")
def test_seed_manager_uses_provided_seed() -> None:
    """SeedManager uses provided master seed."""
    sm = SeedManager(master_seed=42)
    assert sm.master_seed == 42


@pytest.mark.requirement("SVF-DEV-038")
def test_seed_manager_generates_seed_when_none() -> None:
    """SeedManager generates a seed when none provided."""
    sm = SeedManager()
    assert sm.master_seed is not None
    assert isinstance(sm.master_seed, int)


@pytest.mark.requirement("SVF-DEV-038")
def test_seed_manager_seed_for_deterministic() -> None:
    """seed_for() returns same value for same model_id."""
    sm = SeedManager(master_seed=42)
    assert sm.seed_for("mag") == sm.seed_for("mag")


@pytest.mark.requirement("SVF-DEV-038")
def test_seed_manager_two_instances_same_master() -> None:
    """Two SeedManagers with same master produce identical per-model seeds."""
    sm1 = SeedManager(master_seed=99)
    sm2 = SeedManager(master_seed=99)
    assert sm1.seed_for("mag")  == sm2.seed_for("mag")
    assert sm1.seed_for("gyro") == sm2.seed_for("gyro")
    assert sm1.seed_for("css")  == sm2.seed_for("css")


@pytest.mark.requirement("SVF-DEV-038")
def test_seed_manager_save(tmp_path: Path) -> None:
    """save() writes seed.json with master seed."""
    import json
    sm = SeedManager(master_seed=42)
    sm.seed_for("mag")
    sm.save(results_dir=tmp_path)
    manifest = json.loads((tmp_path / "seed.json").read_text())
    assert manifest["master_seed"] == 42
    assert "mag" in manifest["derived_seeds"]
    assert manifest["derived_seeds"]["mag"] == derive_seed(42, "mag")
