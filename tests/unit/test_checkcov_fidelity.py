"""
Unit tests for the fidelity coverage section of checkcov (M34).
Exercises fidelity_report() and EQUIPMENT_FIDELITY from tools/check_coverage.py.
Implements: SVF-DEV-155
"""
from __future__ import annotations

import importlib.util
import sys
import types
from io import StringIO
from pathlib import Path

import pytest

# ── Load tool module ──────────────────────────────────────────────────────────

_TOOL_PATH = Path(__file__).parents[2] / "tools" / "check_coverage.py"


def _load_tool() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("check_coverage", _TOOL_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["check_coverage"] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


_tool = _load_tool()
fidelity_report   = _tool.fidelity_report
EQUIPMENT_FIDELITY: dict[str, tuple[str, str, str]] = _tool.EQUIPMENT_FIDELITY

_SVF_ROOT  = Path(__file__).parents[2]
_SRDB_DIR  = _SVF_ROOT / "srdb" / "baseline"


# ── EQUIPMENT_FIDELITY table invariants ───────────────────────────────────────

@pytest.mark.requirement("SVF-DEV-155")
def test_all_fidelity_entries_have_valid_level() -> None:
    valid = {"F1", "F2", "F3", "F4"}
    for model_id, (level, name, _) in EQUIPMENT_FIDELITY.items():
        assert level in valid, (
            f"EQUIPMENT_FIDELITY['{model_id}'] has invalid level '{level}'. "
            f"Must be one of {valid}."
        )


@pytest.mark.requirement("SVF-DEV-155")
def test_all_fidelity_entries_have_display_name() -> None:
    for model_id, (_, name, _) in EQUIPMENT_FIDELITY.items():
        assert name.strip(), (
            f"EQUIPMENT_FIDELITY['{model_id}'] has an empty display name."
        )


@pytest.mark.requirement("SVF-DEV-155")
def test_f2_entries_have_upgrade_notes() -> None:
    for model_id, (level, name, note) in EQUIPMENT_FIDELITY.items():
        if level == "F2":
            assert note.strip(), (
                f"F2 model '{model_id}' ({name}) has no F3 upgrade note. "
                "Add a concrete upgrade path so validation engineers know what's needed."
            )


@pytest.mark.requirement("SVF-DEV-155")
def test_at_least_one_f2_model() -> None:
    f2_models = [k for k, (l, _, _) in EQUIPMENT_FIDELITY.items() if l == "F2"]
    assert len(f2_models) >= 10, (
        f"Expected at least 10 F2 models; got {len(f2_models)}. "
        "The fidelity table may be incomplete."
    )


@pytest.mark.requirement("SVF-DEV-155")
def test_at_least_one_f3_or_f4_model() -> None:
    high_fi = [k for k, (l, _, _) in EQUIPMENT_FIDELITY.items() if l in ("F3", "F4")]
    assert len(high_fi) >= 1, "Expected at least one F3/F4 model in the table."


# ── fidelity_report() integration ────────────────────────────────────────────

@pytest.mark.requirement("SVF-DEV-155")
def test_fidelity_report_returns_true_on_clean_srdb(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """fidelity_report() must return True (no errors) on the current SRDB."""
    ok = fidelity_report(_SRDB_DIR)
    assert ok is True


@pytest.mark.requirement("SVF-DEV-155")
def test_fidelity_report_prints_fidelity_section(
    capsys: pytest.CaptureFixture[str],
) -> None:
    fidelity_report(_SRDB_DIR)
    out = capsys.readouterr().out
    assert "fidelity" in out.lower() or "F2" in out, (
        "Expected fidelity section in checkcov output."
    )


@pytest.mark.requirement("SVF-DEV-155")
def test_fidelity_report_identifies_f2_upgrade_candidates(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """At least one F2→F3 upgrade candidate must appear in output."""
    fidelity_report(_SRDB_DIR)
    out = capsys.readouterr().out
    assert "F3" in out or "upgrade" in out.lower(), (
        "Expected at least one F2→F3 upgrade candidate in output."
    )


@pytest.mark.requirement("SVF-DEV-155")
def test_fidelity_report_magnetometer_is_f2_candidate(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Magnetometer is F2 with uncalibrated TM params → must appear as candidate."""
    fidelity_report(_SRDB_DIR)
    out = capsys.readouterr().out
    assert "Magnetometer" in out, (
        "Expected 'Magnetometer' in fidelity output."
    )
    assert "F2" in out, "Expected F2 level shown for Magnetometer."


@pytest.mark.requirement("SVF-DEV-155")
def test_fidelity_report_missing_srdb_dir_returns_true(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """If SRDB dir doesn't exist, report skips gracefully and returns True."""
    ok = fidelity_report(tmp_path / "nonexistent")
    assert ok is True


@pytest.mark.requirement("SVF-DEV-155")
def test_fidelity_report_detects_calibration_inconsistency(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """
    A model listed as F2 that has a CalibrationCurve in the SRDB must
    produce an error (inconsistency) and return False.
    """
    # Write a minimal SRDB YAML with a calibration curve on an F2 model
    srdb_yaml = tmp_path / "aocs_test.yaml"
    srdb_yaml.write_text(
        "parameters:\n"
        "  mag.field_x:\n"
        "    description: 'X component'\n"
        "    unit: 'T'\n"
        "    dtype: float\n"
        "    classification: TM\n"
        "    domain: AOCS\n"
        "    model_id: mag\n"
        "    calibration:\n"
        "      type: polynomial\n"
        "      coefficients: [0.0, 1.0]\n"
    )

    ok = fidelity_report(tmp_path)
    out = capsys.readouterr().out

    assert ok is False, (
        "Expected fidelity_report() to return False when calibration curve "
        "exists on an F2 model (INCONSISTENCY)."
    )
    assert "INCONSISTENCY" in out or "ERR" in out, (
        f"Expected inconsistency marker in output. Got:\n{out}"
    )
