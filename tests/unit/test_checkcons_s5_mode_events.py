"""
L1 tests for checkcons check [8/9]: the S5 mode-event mapping used by
OBCEmulatorAdapter against the checkcons table and openobsw's events.yaml.

The openobsw side is exercised with event definitions written to tmp_path,
so the tests do not need an openobsw checkout.

Implements: SVF-DEV-216
"""
from __future__ import annotations

from pathlib import Path

import pytest

from svf.tools.checkcons import (
    S5_MODE_EVENT_TABLE,
    CheckResult,
    check_s5_mode_events,
)

_REPO = Path(__file__).parents[2]

# openobsw srdb/data/events.yaml, reduced to the fields the check reads plus
# one non-mode event with auxiliary data.
_EVENTS_YAML = """\
events:
  - id: 0x0001
    name: boot_complete
    severity: INFO
  - id: 0x0002
    name: safe_mode_entry
    severity: HIGH
    auxiliary_data:
      - name: trigger_source
        type: uint8
  - id: 0x0004
    name: standby_entry
    severity: INFO
  - id: 0x0005
    name: nominal_entry
    severity: INFO
  - id: 0x0051
    name: temperature_hard_limit
    severity: HIGH
    safe_trigger: true
"""

_ADAPTER_TABLE = """\
S5_MODE_EVENTS: dict[int, int] = {
    0x0002: MODE_SAFE,
    0x0004: MODE_STANDBY,
    0x0005: MODE_NOMINAL,
}
"""


def _obsw(tmp_path: Path, events_yaml: str = _EVENTS_YAML) -> Path:
    root = tmp_path / "openobsw"
    (root / "srdb" / "data").mkdir(parents=True)
    (root / "srdb" / "data" / "events.yaml").write_text(events_yaml, encoding="utf-8")
    return root


def _svf(tmp_path: Path, adapter_source: str) -> Path:
    root = tmp_path / "opensvf"
    dhs = root / "src" / "svf" / "models" / "dhs"
    dhs.mkdir(parents=True)
    (dhs / "obc_emulator.py").write_text(adapter_source, encoding="utf-8")
    return root


def _run(svf_root: Path, obsw_root: Path | None) -> CheckResult:
    result = CheckResult()
    check_s5_mode_events(svf_root, obsw_root, result)
    return result


@pytest.mark.requirement("SVF-DEV-216")
def test_repo_adapter_matches_the_checkcons_table() -> None:
    """The Python side holds for this checkout, with no openobsw needed."""
    result = _run(_REPO, None)
    assert result.errors == []
    assert any("openobsw side skipped" in n for n in result.info)


@pytest.mark.requirement("SVF-DEV-216")
def test_repo_adapter_matches_openobsw_event_definitions(tmp_path: Path) -> None:
    result = _run(_REPO, _obsw(tmp_path))
    assert result.errors == []
    assert result.warnings == []
    assert any("3 mode events compared with openobsw" in n for n in result.info)


@pytest.mark.requirement("SVF-DEV-216")
def test_pre_fix_adapter_mapping_is_an_error(tmp_path: Path) -> None:
    """The mapping before SVF-DEV-216: 0x0002 and 0x0003 only."""
    old = "S5_MODE_EVENTS = {\n    0x0002: MODE_SAFE,\n    0x0003: MODE_NOMINAL,\n}\n"
    errors = _run(_svf(tmp_path, old), None).errors
    assert len(errors) == 3
    assert any("0x0004 (standby_entry)" in e and "does not map it" in e for e in errors)
    assert any("0x0005 (nominal_entry)" in e and "does not map it" in e for e in errors)
    assert any("0x0003" in e and "S5_MODE_EVENT_TABLE has no such mode event" in e
               for e in errors)


@pytest.mark.requirement("SVF-DEV-216")
def test_adapter_mapping_an_event_to_the_wrong_mode_is_an_error(tmp_path: Path) -> None:
    wrong = _ADAPTER_TABLE.replace("0x0004: MODE_STANDBY", "0x0004: MODE_SAFE")
    errors = _run(_svf(tmp_path, wrong), None).errors
    assert len(errors) == 1
    assert "0x0004 (standby_entry)" in errors[0]
    assert "maps it to SAFE" in errors[0] and "says STANDBY" in errors[0]


@pytest.mark.requirement("SVF-DEV-216")
def test_adapter_mapping_an_unlisted_event_is_an_error(tmp_path: Path) -> None:
    """An ID added to the adapter alone would never be compared with openobsw."""
    extra = _ADAPTER_TABLE.replace("}\n", "    0x0006: MODE_SAFE,\n}\n")
    errors = _run(_svf(tmp_path, extra), None).errors
    assert len(errors) == 1
    assert "0x0006" in errors[0] and "S5_MODE_EVENT_TABLE has no such mode event" in errors[0]


@pytest.mark.requirement("SVF-DEV-216")
@pytest.mark.parametrize("source", [
    "MODE_SAFE = 1\n",                                         # table missing
    "S5_MODE_EVENTS = build_table()\n",                        # not a literal
    "S5_MODE_EVENTS = {0x0002: 1, 0x0005: 2}\n",               # modes not MODE_x names
])
def test_unreadable_adapter_table_is_an_error(tmp_path: Path, source: str) -> None:
    errors = _run(_svf(tmp_path, source), None).errors
    assert len(errors) == 1 and "S5_MODE_EVENTS not found" in errors[0]


@pytest.mark.requirement("SVF-DEV-216")
def test_event_removed_from_openobsw_is_an_error(tmp_path: Path) -> None:
    """How the removal of 0x0003 safe_mode_exit was caught; here with standby_entry."""
    without_standby = _EVENTS_YAML.replace(
        "  - id: 0x0004\n    name: standby_entry\n    severity: INFO\n", "")
    assert "standby_entry" not in without_standby
    errors = _run(_REPO, _obsw(tmp_path, without_standby)).errors
    assert len(errors) == 1
    assert "no longer defines event 'standby_entry'" in errors[0]
    assert "0x0004 -> STANDBY" in errors[0]


@pytest.mark.requirement("SVF-DEV-216")
def test_openobsw_v0_18_safe_mode_exit_is_a_warning(tmp_path: Path) -> None:
    """v0.18 still defines 0x0003, which nothing emits: reported, not an error."""
    v0_18 = _EVENTS_YAML.replace(
        "  - id: 0x0004\n", "  - id: 0x0003\n    name: safe_mode_exit\n"
        "    severity: INFO\n  - id: 0x0004\n")
    result = _run(_REPO, _obsw(tmp_path, v0_18))
    assert result.errors == []
    assert len(result.warnings) == 1
    assert "'safe_mode_exit' (0x0003)" in result.warnings[0]


@pytest.mark.requirement("SVF-DEV-216")
def test_event_renumbered_in_openobsw_is_an_error(tmp_path: Path) -> None:
    moved = _EVENTS_YAML.replace("id: 0x0005\n    name: nominal_entry",
                                 "id: 0x0006\n    name: nominal_entry")
    errors = _run(_REPO, _obsw(tmp_path, moved)).errors
    assert len(errors) == 1
    assert "'nominal_entry' is 0x0006" in errors[0] and "0x0005 -> NOMINAL" in errors[0]


@pytest.mark.requirement("SVF-DEV-216")
def test_event_renamed_in_openobsw_names_what_the_id_is_now(tmp_path: Path) -> None:
    renamed = _EVENTS_YAML.replace("name: standby_entry", "name: standby_mode_entry")
    result = _run(_REPO, _obsw(tmp_path, renamed))
    assert len(result.errors) == 1
    assert "no longer defines event 'standby_entry'" in result.errors[0]
    assert "0x0004 is now 'standby_mode_entry'" in result.errors[0]
    # The new name still reads as a mode transition the adapter does not handle.
    assert any("'standby_mode_entry' (0x0004)" in w for w in result.warnings)


@pytest.mark.requirement("SVF-DEV-216")
def test_new_openobsw_mode_event_is_a_warning(tmp_path: Path) -> None:
    grown = _EVENTS_YAML + "  - id: 0x0006\n    name: payload_entry\n    severity: INFO\n"
    result = _run(_REPO, _obsw(tmp_path, grown))
    assert result.errors == []
    assert len(result.warnings) == 1
    assert "'payload_entry' (0x0006)" in result.warnings[0]


@pytest.mark.requirement("SVF-DEV-216")
def test_gitingest_snapshot_is_read_like_a_checkout(tmp_path: Path) -> None:
    """--obsw may be a gitingest .txt; only its events.yaml section is read."""
    bar = "=" * 48
    snapshot = tmp_path / "lipofefeyt-openobsw.txt"
    snapshot.write_text(
        f"{bar}\nFILE: srdb/data/events.yaml\n{bar}\n"
        + _EVENTS_YAML.replace("id: 0x0005\n    name: nominal_entry",
                               "id: 0x0006\n    name: nominal_entry")
        + f"\n{bar}\nFILE: srdb/data/parameters.yaml\n{bar}\n"
        "parameters:\n  - id: 0x0005\n    name: nominal_entry\n",
        encoding="utf-8",
    )
    errors = _run(_REPO, snapshot).errors
    assert len(errors) == 1 and "'nominal_entry' is 0x0006" in errors[0]


@pytest.mark.requirement("SVF-DEV-216")
@pytest.mark.parametrize("make_obsw", [
    lambda p: p / "no-such-checkout",                          # no events.yaml
    lambda p: _obsw(p, "events: [not, a, mapping]\n"),         # unreadable definitions
    lambda p: (p / "snapshot.txt", (p / "snapshot.txt").write_text("no sections\n"))[0],
])
def test_unreadable_openobsw_side_is_a_warning_not_a_pass(
    tmp_path: Path, make_obsw,  # type: ignore[no-untyped-def]
) -> None:
    """A skipped comparison must be visible: one warning, no errors, no 'compared' note."""
    result = _run(_REPO, make_obsw(tmp_path))
    assert result.errors == []
    assert len(result.warnings) == 1 and "skipping the openobsw side" in result.warnings[0]
    assert not any("compared with openobsw" in n for n in result.info)


@pytest.mark.requirement("SVF-DEV-216")
def test_table_ids_are_unique() -> None:
    """Two names on one ID would make the adapter comparison ambiguous."""
    ids = [eid for eid, _ in S5_MODE_EVENT_TABLE.values()]
    assert len(ids) == len(set(ids))
