"""Tests for SpacecraftLoader YAML configuration."""
from __future__ import annotations
import pytest
from pathlib import Path
from svf.config.spacecraft import SpacecraftLoader, SpacecraftConfigError


EXAMPLES_DIR = Path(__file__).parent.parent.parent / "mission_mysat1"


class TestSpacecraftLoaderSuite:

    @pytest.mark.requirement("SVF-DEV-110")
    def test_load_returns_simulation_master(self) -> None:
        """SpacecraftLoader.load() returns a SimulationMaster."""
        from svf.sim.simulation import SimulationMaster
        master = SpacecraftLoader.load(
            EXAMPLES_DIR / "spacecraft.yaml"
        )
        assert isinstance(master, SimulationMaster)

    @pytest.mark.requirement("SVF-DEV-110")
    def test_equipment_instantiated(self) -> None:
        """All equipment from YAML is instantiated."""
        master = SpacecraftLoader.load(
            EXAMPLES_DIR / "spacecraft.yaml"
        )
        model_ids = [m.equipment_id for m in master._models]
        assert "mag1" in model_ids
        assert "gyro1" in model_ids
        assert "mtq1" in model_ids
        assert "rw1" in model_ids
        assert "str1" in model_ids
        # kde (dynamics FMU) is optional — commented out in spacecraft.yaml
        # until the opensvf-kde binary is available

    @pytest.mark.requirement("SVF-DEV-110")
    def test_auto_wiring_inferred(self) -> None:
        """Auto-wiring is parsed and a WiringMap is attached to the master."""
        master = SpacecraftLoader.load(
            EXAMPLES_DIR / "spacecraft.yaml"
        )
        # wiring: auto: true → WiringMap is created (connection count depends
        # on equipment set; kde FMU omitted in demo config so count may be 0)
        assert master._wiring is not None

    @pytest.mark.requirement("SVF-DEV-110")
    def test_missing_config_raises(self) -> None:
        """Loading a non-existent file raises SpacecraftConfigError."""
        with pytest.raises(SpacecraftConfigError):
            SpacecraftLoader.load("nonexistent.yaml")

    @pytest.mark.requirement("SVF-DEV-110")
    def test_bus_configuration_loaded(self, tmp_path: Path) -> None:
        """Bus adapters are instantiated from YAML buses section."""
        master = SpacecraftLoader.load(
            EXAMPLES_DIR / "spacecraft_with_buses.yaml"
        )
        model_ids = [m.equipment_id for m in master._models]
        assert "bus.aocs_bus" in model_ids

    @pytest.mark.requirement("SVF-DEV-110")
    def test_unknown_model_raises(self, tmp_path: Path) -> None:
        """Unknown model name raises SpacecraftConfigError."""
        cfg = tmp_path / "bad.yaml"
        cfg.write_text("""
spacecraft: Test
equipment:
  - id: bad1
    model: nonexistent_model
simulation:
  dt: 0.1
  stop_time: 1.0
""")
        with pytest.raises(SpacecraftConfigError):
            SpacecraftLoader.load(cfg)
