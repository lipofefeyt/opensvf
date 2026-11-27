"""
L1 tests for checkcons check [10/10] (compatibility pin and docs) and for
check [3/10] reading the frame structs from sim/sensor_inject.h only.

The opensvf and openobsw sides are written to tmp_path, so no openobsw
checkout is needed.

Implements: SVF-DEV-221
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from svf.models.dhs import obc_emulator
from svf.tools.checkcons import (
    ACTUATOR_FRAME_FIELD_TO_CMDSTORE_KEY,
    SENSOR_FRAME_FIELD_TO_SVF_PORT,
    CheckResult,
    check_compatibility_pin,
    check_wire_protocol_c_side,
)

_PIN = "v0.20"
_VERSION = "9.9.9"


def _svf(tmp_path: Path, *, yaml_pin: str = _PIN, readme_pin: str = _PIN,
         readme_wire: int = obc_emulator.WIRE_PROTOCOL_VERSION,
         pin: str = _PIN) -> Path:
    root = tmp_path / "opensvf"
    (root / "docs").mkdir(parents=True)
    (root / "pyproject.toml").write_text(f'[project]\nversion = "{_VERSION}"\n')
    (root / ".openobsw-version").write_text(pin + "\n")
    (root / "docs" / "compatibility.yaml").write_text(yaml.safe_dump({"releases": [{
        "opensvf": _VERSION, "openobsw": yaml_pin,
        "wire_protocol": obc_emulator.WIRE_PROTOCOL_VERSION,
        "sensor_frame_bytes": obc_emulator._SENSOR_LEN}]}))
    (root / "README.md").write_text(
        "| Package | Version | Notes |\n|---|---|---|\n"
        f"| opensvf | v{_VERSION} | Python 3.12 |\n"
        f"| openobsw | {readme_pin} (pinned in `.openobsw-version`) | "
        f"C11, wire protocol v{readme_wire} |\n")
    return root


def _errors(root: Path) -> list[str]:
    result = CheckResult()
    check_compatibility_pin(root, None, result)
    return result.errors


@pytest.mark.requirement("SVF-DEV-221")
def test_compatibility_in_agreement_passes(tmp_path: Path) -> None:
    assert _errors(_svf(tmp_path)) == []


@pytest.mark.requirement("SVF-DEV-221")
def test_compatibility_row_disagreeing_with_pin_is_an_error(tmp_path: Path) -> None:
    errors = _errors(_svf(tmp_path, yaml_pin="v0.19"))
    assert len(errors) == 1
    assert "compatibility.yaml" in errors[0] and "v0.19" in errors[0]


@pytest.mark.requirement("SVF-DEV-221")
def test_missing_compatibility_row_is_an_error(tmp_path: Path) -> None:
    root = _svf(tmp_path)
    (root / "pyproject.toml").write_text('[project]\nversion = "9.9.10"\n')
    errors = _errors(root)
    assert any("no row for opensvf 9.9.10" in e for e in errors)


@pytest.mark.requirement("SVF-DEV-221")
def test_readme_disagreeing_with_pin_or_protocol_is_an_error(tmp_path: Path) -> None:
    errors = _errors(_svf(tmp_path, readme_pin="v0.18", readme_wire=3))
    assert any("README.md" in e and "v0.18" in e for e in errors)
    assert any("README.md" in e and "wire protocol v3" in e for e in errors)


@pytest.mark.requirement("SVF-DEV-221")
def test_pin_that_is_not_a_release_tag_is_an_error(tmp_path: Path) -> None:
    errors = _errors(_svf(tmp_path, pin="main", yaml_pin="main", readme_pin="main"))
    assert errors and all("not a release tag" in e for e in errors)


@pytest.mark.requirement("SVF-DEV-221")
def test_repository_compatibility_agrees_with_pin() -> None:
    assert _errors(Path(__file__).parents[2]) == []


def _struct(name: str, fields: list[str]) -> str:
    body = "\n".join(f"    float {f};" for f in fields)
    return f"typedef struct {{\n{body}\n}} {name};\n"


def _obsw(tmp_path: Path, canonical: bool = True) -> Path:
    """An openobsw tree whose non-canonical frame copy has a renamed field."""
    root = tmp_path / "openobsw"
    sensor = list(SENSOR_FRAME_FIELD_TO_SVF_PORT)
    actuator = list(ACTUATOR_FRAME_FIELD_TO_CMDSTORE_KEY)
    stale = root / "contrib" / "svf_protocol" / "obsw_svf_protocol.h"
    stale.parent.mkdir(parents=True)
    stale.write_text(_struct("obsw_sensor_frame_t", ["renamed"] + sensor[1:])
                     + _struct("obsw_actuator_frame_t", actuator))
    if canonical:
        header = root / "sim" / "sensor_inject.h"
        header.parent.mkdir(parents=True)
        header.write_text(_struct("obsw_sensor_frame_t", sensor)
                          + _struct("obsw_actuator_frame_t", actuator))
    return root


@pytest.mark.requirement("SVF-DEV-221")
def test_c_structs_are_read_from_sensor_inject_h_only(tmp_path: Path) -> None:
    result = CheckResult()
    check_wire_protocol_c_side(_obsw(tmp_path), result)
    assert result.errors == []
    assert any("sensor_inject.h" in n for n in result.info)


@pytest.mark.requirement("SVF-DEV-221")
def test_missing_sensor_inject_h_warns_instead_of_reading_a_copy(tmp_path: Path) -> None:
    result = CheckResult()
    check_wire_protocol_c_side(_obsw(tmp_path, canonical=False), result)
    assert result.errors == []
    assert any("sensor_inject.h not found" in w for w in result.warnings)
