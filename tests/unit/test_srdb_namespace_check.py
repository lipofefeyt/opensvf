"""
Unit tests for the SRDB namespace linting check (M33).
Exercises check_srdb_namespace() from tools/srdb_consistency_check.py.
Implements: SVF-DEV-154
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ── Load the tool module without it being a package ──────────────────────────

_TOOL_PATH = Path(__file__).parents[2] / "tools" / "srdb_consistency_check.py"


def _load_tool() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("srdb_consistency_check", _TOOL_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["srdb_consistency_check"] = mod  # required for @dataclass forward refs
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


_tool = _load_tool()
check_srdb_namespace = _tool.check_srdb_namespace
CheckResult = _tool.CheckResult
KNOWN_NAMESPACE_GAPS: dict[str, str] = _tool.KNOWN_NAMESPACE_GAPS
_NAMESPACE_CHECK_MODELS: dict[str, Any] = _tool._NAMESPACE_CHECK_MODELS


# ── helpers ───────────────────────────────────────────────────────────────────

def _svf_root() -> Path:
    return Path(__file__).parents[2]


def _errors(result: Any) -> list[str]:
    return result.errors  # type: ignore[no-any-return]


def _warnings(result: Any) -> list[str]:
    return result.warnings  # type: ignore[no-any-return]


# ── CheckResult structure ─────────────────────────────────────────────────────

def test_checkresult_ok_when_no_errors() -> None:
    r = CheckResult()
    assert r.ok()


def test_checkresult_not_ok_when_error_added() -> None:
    r = CheckResult()
    r.error("something broke")
    assert not r.ok()


def test_checkresult_ok_with_only_warnings() -> None:
    r = CheckResult()
    r.warn("heads up")
    assert r.ok()


# ── KNOWN_NAMESPACE_GAPS completeness ─────────────────────────────────────────

@pytest.mark.requirement("SVF-DEV-154")
def test_known_gaps_all_have_justifications() -> None:
    """Every entry in the gaps dict must have a non-empty justification."""
    for port, reason in KNOWN_NAMESPACE_GAPS.items():
        assert reason.strip(), (
            f"KNOWN_NAMESPACE_GAPS['{port}'] has an empty justification. "
            "Add a reason explaining why this port has no SRDB definition."
        )


@pytest.mark.requirement("SVF-DEV-154")
def test_namespace_check_models_registry_non_empty() -> None:
    assert len(_NAMESPACE_CHECK_MODELS) >= 10, (
        "Expected at least 10 models in the namespace check registry"
    )


# ── Integration: run against the real codebase ───────────────────────────────

@pytest.mark.requirement("SVF-DEV-154")
def test_check_srdb_namespace_passes_on_current_codebase() -> None:
    """
    The full check must exit with 0 errors on the current codebase.
    All known orphan ports must be listed in KNOWN_NAMESPACE_GAPS.
    """
    result = CheckResult()
    check_srdb_namespace(_svf_root(), result)
    errors = _errors(result)
    assert errors == [], (
        f"check_srdb_namespace found {len(errors)} unexpected error(s):\n"
        + "\n".join(f"  {e}" for e in errors)
    )


@pytest.mark.requirement("SVF-DEV-154")
def test_dead_tm_definitions_reported_as_warnings_not_errors() -> None:
    """SRDB TM params with no model OUT port must be warnings, not errors."""
    result = CheckResult()
    check_srdb_namespace(_svf_root(), result)
    # Any SRDB-NS dead definitions must appear in warnings, not errors
    dead_in_errors = [e for e in _errors(result) if "no model declares it" in e]
    assert dead_in_errors == [], (
        "Dead SRDB TM definitions should be warnings, not errors: "
        + str(dead_in_errors)
    )


# ── Orphan detection: mock an unknown port ────────────────────────────────────

@pytest.mark.requirement("SVF-DEV-154")
def test_new_orphan_port_is_flagged_as_error() -> None:
    """
    An OUT port that is not in the SRDB and not in KNOWN_NAMESPACE_GAPS
    must produce an error.
    """
    from svf.core.abstractions import SyncProtocol
    from svf.core.equipment import PortDefinition, PortDirection
    from svf.core.native_equipment import NativeEquipment
    from svf.stores.parameter_store import ParameterStore
    from svf.stores.command_store import CommandStore

    class _Sync(SyncProtocol):
        def reset(self) -> None: pass
        def publish_ready(self, m: str, t: float) -> None: pass
        def wait_for_ready(self, e: list[str], t: float) -> bool: return True

    def _step(eq: NativeEquipment, t: float, dt: float) -> None:
        eq.write_port("unknown.orphan.xyz", 0.0)

    orphan_eq = NativeEquipment(
        equipment_id="orphan_test",
        ports=[PortDefinition("unknown.orphan.xyz", PortDirection.OUT, unit="")],
        step_fn=_step,
        sync_protocol=_Sync(),
        store=ParameterStore(),
    )

    # Patch the model registry to inject our orphan model
    fake_registry = {"orphan_model": ("_fake_module", "_fake_factory")}

    import importlib as _il

    def _fake_import(name: str) -> object:
        fake_mod = MagicMock()
        fake_mod._fake_factory = MagicMock(return_value=orphan_eq)
        return fake_mod

    with patch.dict(_tool.KNOWN_NAMESPACE_GAPS, {}, clear=False):
        with patch.dict(_tool._NAMESPACE_CHECK_MODELS, fake_registry, clear=True):
            with patch("importlib.import_module", side_effect=_fake_import):
                result = CheckResult()
                check_srdb_namespace(_svf_root(), result)

    errors = _errors(result)
    assert any("unknown.orphan.xyz" in e for e in errors), (
        f"Expected error for 'unknown.orphan.xyz' but got: {errors}"
    )


@pytest.mark.requirement("SVF-DEV-154")
def test_known_gap_port_is_not_an_error() -> None:
    """
    A port listed in KNOWN_NAMESPACE_GAPS must not produce an error,
    only a note.
    """
    from svf.core.abstractions import SyncProtocol
    from svf.core.equipment import PortDefinition, PortDirection
    from svf.core.native_equipment import NativeEquipment
    from svf.stores.parameter_store import ParameterStore

    class _Sync(SyncProtocol):
        def reset(self) -> None: pass
        def publish_ready(self, m: str, t: float) -> None: pass
        def wait_for_ready(self, e: list[str], t: float) -> bool: return True

    def _step(eq: NativeEquipment, t: float, dt: float) -> None:
        eq.write_port("gps.position_x", 0.0)  # in KNOWN_NAMESPACE_GAPS

    gap_eq = NativeEquipment(
        equipment_id="gps_test",
        ports=[PortDefinition("gps.position_x", PortDirection.OUT, unit="km")],
        step_fn=_step,
        sync_protocol=_Sync(),
        store=ParameterStore(),
    )

    fake_registry = {"gps_model": ("_fake_module", "_fake_factory")}

    def _fake_import(name: str) -> object:
        fake_mod = MagicMock()
        fake_mod._fake_factory = MagicMock(return_value=gap_eq)
        return fake_mod

    with patch.dict(_tool._NAMESPACE_CHECK_MODELS, fake_registry, clear=True):
        with patch("importlib.import_module", side_effect=_fake_import):
            result = CheckResult()
            check_srdb_namespace(_svf_root(), result)

    errors = _errors(result)
    assert not any("gps.position_x" in e for e in errors), (
        f"Known gap port 'gps.position_x' must not produce an error: {errors}"
    )
