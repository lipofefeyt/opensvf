"""Tests for SVF CLI entry point."""
from __future__ import annotations
import pytest
from pathlib import Path
from unittest.mock import patch
import sys
from svf.campaign.cli import main, cmd_profiles, cmd_check

EXAMPLES = Path(__file__).parent.parent.parent / "examples"


class TestCliSuite:

    @pytest.mark.requirement("GAP-014")
    def test_check_valid_config_returns_zero(self, tmp_path: Path) -> None:
        """svf check returns 0 for valid spacecraft.yaml."""
        import argparse
        args = argparse.Namespace(config=str(EXAMPLES / "spacecraft.yaml"))
        result = cmd_check(args)
        assert result == 0

    @pytest.mark.requirement("GAP-014")
    def test_check_missing_config_returns_one(self, tmp_path: Path) -> None:
        """svf check returns 1 for missing file."""
        import argparse
        args = argparse.Namespace(config="nonexistent.yaml")
        result = cmd_check(args)
        assert result == 1

    @pytest.mark.requirement("GAP-014")
    def test_profiles_returns_zero(self) -> None:
        """svf profiles returns 0 when profiles exist."""
        import argparse
        args = argparse.Namespace()
        result = cmd_profiles(args)
        assert result == 0

    @pytest.mark.requirement("GAP-014")
    def test_help_exits_cleanly(self) -> None:
        """svf --help exits with code 0."""
        with pytest.raises(SystemExit) as exc:
            with patch("sys.argv", ["svf", "--help"]):
                main()
        assert exc.value.code == 0

    @pytest.mark.requirement("GAP-014")
    def test_unknown_command_exits_nonzero(self) -> None:
        """svf unknown-command exits with non-zero code."""
        with pytest.raises(SystemExit) as exc:
            with patch("sys.argv", ["svf", "nonexistent"]):
                main()
        assert exc.value.code != 0

    @pytest.mark.requirement("GAP-014")
    def test_check_invalid_model_returns_one(self, tmp_path: Path) -> None:
        """svf check returns 1 for config with unknown model."""
        import argparse
        cfg = tmp_path / "bad.yaml"
        cfg.write_text("""
spacecraft: Test
equipment:
  - id: bad
    model: nonexistent_model
simulation:
  dt: 0.1
  stop_time: 1.0
""")
        args = argparse.Namespace(config=str(cfg))
        result = cmd_check(args)
        assert result == 1
