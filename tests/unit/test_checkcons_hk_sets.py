"""
L1 tests for checkcons check [9/9]: the TM(3,25) housekeeping set layouts
opensvf ships against openobsw's hk_sets.yaml and parameters.yaml.

The openobsw side is written to tmp_path from the layouts under test, then
changed the way openobsw could change, so no openobsw checkout is needed.

Implements: SVF-DEV-217
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import pytest
import yaml

from svf.srdb.loader import load_bundled_hk_sets
from svf.tools.checkcons import CheckResult, check_hk_set_layouts

_REPO = Path(__file__).parents[2]


def _openobsw_srdb() -> tuple[dict[str, Any], dict[str, Any]]:
    """openobsw hk_sets.yaml and parameters.yaml content matching the bundled layouts."""
    sets = load_bundled_hk_sets()
    hk = {"hk_sets": [
        {"id": i, "name": s.name, "parameters": [p.obsw_name for p in s.parameters]}
        for i, s in sorted(sets.items())]}
    params = {"parameters": [
        {"name": p.obsw_name, "type": p.wire_type.value}
        for s in sets.values() for p in s.parameters]}
    return hk, params


def _obsw(tmp_path: Path, hk: dict[str, Any], params: dict[str, Any]) -> Path:
    data = tmp_path / "openobsw" / "srdb" / "data"
    data.mkdir(parents=True)
    (data / "hk_sets.yaml").write_text(yaml.safe_dump(hk), encoding="utf-8")
    (data / "parameters.yaml").write_text(yaml.safe_dump(params), encoding="utf-8")
    return tmp_path / "openobsw"


def _run(obsw_root: Path | None, svf_root: Path = _REPO) -> CheckResult:
    result = CheckResult()
    check_hk_set_layouts(svf_root, obsw_root, result)
    return result


def _set(hk: dict[str, Any], set_id: int) -> dict[str, Any]:
    return next(s for s in hk["hk_sets"] if s["id"] == set_id)  # type: ignore[no-any-return]


def _param(params: dict[str, Any], name: str) -> dict[str, Any]:
    return next(p for p in params["parameters"] if p["name"] == name)  # type: ignore[no-any-return]


@pytest.mark.requirement("SVF-DEV-217")
def test_bundled_layouts_pass_without_openobsw() -> None:
    result = _run(None)
    assert result.errors == []
    assert any("7 housekeeping sets loaded" in n for n in result.info)
    assert any("openobsw side skipped" in n for n in result.info)


@pytest.mark.requirement("SVF-DEV-217")
def test_bundled_layouts_match_an_identical_openobsw(tmp_path: Path) -> None:
    result = _run(_obsw(tmp_path, *_openobsw_srdb()))
    assert result.errors == [] and result.warnings == []
    assert any("7 housekeeping sets compared with openobsw" in n for n in result.info)


def _add_param(hk: dict[str, Any], params: dict[str, Any]) -> None:
    """openobsw #122-style change: a parameter appended to nominal_hk."""
    _set(hk, 1)["parameters"].append("obc_thermal_valid")
    params["parameters"].append({"name": "obc_thermal_valid", "type": "uint8"})


def _reorder(hk: dict[str, Any], params: dict[str, Any]) -> None:
    p = _set(hk, 1)["parameters"]
    p[1], p[2] = p[2], p[1]


def _retype_same_size(hk: dict[str, Any], params: dict[str, Any]) -> None:
    _param(params, "obc_temperature")["type"] = "uint16"


def _retype_wider(hk: dict[str, Any], params: dict[str, Any]) -> None:
    _param(params, "obc_reset_count")["type"] = "uint32"


def _drop_set(hk: dict[str, Any], params: dict[str, Any]) -> None:
    hk["hk_sets"].remove(_set(hk, 7))


def _new_set(hk: dict[str, Any], params: dict[str, Any]) -> None:
    hk["hk_sets"].append({"id": 8, "name": "payload_hk", "parameters": ["obc_uptime"]})


def _rename_set(hk: dict[str, Any], params: dict[str, Any]) -> None:
    _set(hk, 2)["name"] = "fdir_statistics_hk"


def _unknown_type(hk: dict[str, Any], params: dict[str, Any]) -> None:
    _param(params, "obc_uptime")["type"] = "uint24"


@pytest.mark.requirement("SVF-DEV-217")
@pytest.mark.parametrize("change, expected", [
    (_add_param, ["set 1 (nominal_hk) parameters differ"]),
    (_reorder, ["set 1 (nominal_hk) parameters differ"]),
    (_retype_same_size, ["'obc_temperature' is uint16 in openobsw and int16 in hk_sets.yaml"]),
    (_retype_wider, ["'obc_reset_count' is uint32 in openobsw and uint16 in hk_sets.yaml",
                     "openobsw binds sizes {1, 4, 1, 1, 1, 4, 1} (SRDB_HK_DHS_OBC_HK_SIZES), "
                     "hk_sets.yaml gives {1, 4, 1, 1, 1, 2, 1}"]),
    (_drop_set, ["hk_sets.yaml defines set 7 (aocs_bdot_hk) but openobsw does not"]),
    (_new_set, ["openobsw defines set 8 (payload_hk) but hk_sets.yaml does not"]),
    (_rename_set, ["set 2 is 'fdir_hk' in hk_sets.yaml and 'fdir_statistics_hk' in openobsw"]),
    (_unknown_type, ["'obc_uptime' is uint24 in openobsw and uint32 in hk_sets.yaml",
                     "openobsw type 'uint24' of 'obc_uptime' is not one opensvf can decode"]),
])
def test_openobsw_drift_is_an_error(
    tmp_path: Path,
    change: Callable[[dict[str, Any], dict[str, Any]], None],
    expected: list[str],
) -> None:
    hk, params = _openobsw_srdb()
    change(hk, params)
    errors = _run(_obsw(tmp_path, hk, params)).errors
    assert len(errors) == len(expected), errors
    for fragment in expected:
        assert any(fragment in e for e in errors), (fragment, errors)


@pytest.mark.requirement("SVF-DEV-217")
def test_unreadable_openobsw_side_is_a_warning_not_a_pass(tmp_path: Path) -> None:
    result = _run(tmp_path / "no-such-checkout")
    assert result.errors == []
    assert len(result.warnings) == 2          # hk_sets.yaml and parameters.yaml
    assert all("skipping the openobsw side" in w for w in result.warnings)
    assert not any("compared with openobsw" in n for n in result.info)


@pytest.mark.requirement("SVF-DEV-217")
def test_gitingest_snapshot_is_read_like_a_checkout(tmp_path: Path) -> None:
    hk, params = _openobsw_srdb()
    _retype_wider(hk, params)
    bar = "=" * 48
    snapshot = tmp_path / "lipofefeyt-openobsw.txt"
    snapshot.write_text(
        f"{bar}\nFILE: srdb/data/hk_sets.yaml\n{bar}\n{yaml.safe_dump(hk)}\n"
        f"{bar}\nFILE: srdb/data/parameters.yaml\n{bar}\n{yaml.safe_dump(params)}\n",
        encoding="utf-8")
    errors = _run(snapshot).errors
    assert len(errors) == 2 and any("SRDB_HK_DHS_OBC_HK_SIZES" in e for e in errors)


def _svf_root(tmp_path: Path, hk_sets_yaml: str | None) -> Path:
    root = tmp_path / "opensvf"
    data = root / "src" / "svf" / "data" / "srdb"
    data.mkdir(parents=True)
    if hk_sets_yaml is not None:
        (data / "hk_sets.yaml").write_text(hk_sets_yaml, encoding="utf-8")
    return root


@pytest.mark.requirement("SVF-DEV-217")
@pytest.mark.parametrize("hk_sets_yaml, fragment", [
    (None, "hk_sets.yaml not found"),
    ("hk_sets:\n  - {id: 1, name: a, parameters: [{key: dhs.obc.x, obsw: x, type: uint24}]}\n",
     "could not load"),
    ("hk_sets:\n  - {id: 1, name: a, parameters: [{key: dhs.obc.temp, obsw: obc_temperature, "
     "type: int16}]}\n", "key 'dhs.obc.temp' for openobsw parameter 'obc_temperature' is not "
     "'dhs.obc.obc_temperature'"),
])
def test_python_side_problems_are_errors(
    tmp_path: Path, hk_sets_yaml: str | None, fragment: str,
) -> None:
    errors = _run(None, _svf_root(tmp_path, hk_sets_yaml)).errors
    assert len(errors) == 1 and fragment in errors[0]
