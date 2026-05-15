"""
Unit tests for ObtParamFile — time-tagged parameter initialisation.
Implements: SVF-DEV-149, SVF-DEV-150, SVF-DEV-151
"""
from __future__ import annotations

import textwrap
import pytest
from pathlib import Path

from svf.sim.obt_param_file import ObtParamFile, ObtEntry
from svf.core.abstractions import SyncProtocol
from svf.stores.parameter_store import ParameterStore
from svf.stores.command_store import CommandStore
from svf.sim.simulation import SimulationMaster
from svf.sim.software_tick import SoftwareTickSource


# ── helpers ───────────────────────────────────────────────────────────────────

def _write_tsv(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "init.tsv"
    p.write_text(textwrap.dedent(content))
    return p


class _NoSync(SyncProtocol):
    def reset(self) -> None:
        pass

    def publish_ready(self, model_id: str, t: float) -> None:
        pass

    def wait_for_ready(self, expected: list[str], timeout: float) -> bool:
        return True


# ── ObtParamFile parsing ──────────────────────────────────────────────────────

@pytest.mark.requirement("SVF-DEV-149")
def test_obt_parse_happy_path(tmp_path: Path) -> None:
    """Three valid entries are parsed and sorted by OBT."""
    p = _write_tsv(tmp_path, """\
        60.0   eps.solar_array.illumination  0.0
        0.0    eps.battery.soc              0.72
        0.0    aocs.rw1.speed_rpm           3200.0
    """)
    obf = ObtParamFile.load(p)
    assert len(obf) == 3
    assert obf.entries[0] == ObtEntry(obt=0.0, name="eps.battery.soc", value=0.72)
    assert obf.entries[1] == ObtEntry(obt=0.0, name="aocs.rw1.speed_rpm", value=3200.0)
    assert obf.entries[2] == ObtEntry(obt=60.0, name="eps.solar_array.illumination", value=0.0)


@pytest.mark.requirement("SVF-DEV-149")
def test_obt_ignores_comment_lines(tmp_path: Path) -> None:
    """Lines starting with '#' and blank lines are skipped."""
    p = _write_tsv(tmp_path, """\
        # This is a comment
        0.0    param.a   1.0

        # Another comment
        1.0    param.b   2.0
    """)
    obf = ObtParamFile.load(p)
    assert len(obf) == 2


@pytest.mark.requirement("SVF-DEV-149")
def test_obt_out_of_order_sorted(tmp_path: Path) -> None:
    """Entries provided out of OBT order are returned sorted ascending."""
    p = _write_tsv(tmp_path, """\
        30.0   param.c   3.0
        10.0   param.a   1.0
        20.0   param.b   2.0
    """)
    obf = ObtParamFile.load(p)
    assert [e.obt for e in obf.entries] == [10.0, 20.0, 30.0]


@pytest.mark.requirement("SVF-DEV-149")
def test_obt_empty_file(tmp_path: Path) -> None:
    """An all-comment file produces an empty ObtParamFile."""
    p = _write_tsv(tmp_path, """\
        # no data here
    """)
    obf = ObtParamFile.load(p)
    assert len(obf) == 0


@pytest.mark.requirement("SVF-DEV-149")
def test_obt_missing_file_raises() -> None:
    """FileNotFoundError is raised for a nonexistent path."""
    with pytest.raises(FileNotFoundError):
        ObtParamFile.load("/nonexistent/path/init.tsv")


@pytest.mark.requirement("SVF-DEV-149")
def test_obt_wrong_column_count_raises(tmp_path: Path) -> None:
    """Lines with fewer than 3 fields raise ValueError."""
    p = _write_tsv(tmp_path, "0.0   only_two_fields\n")
    with pytest.raises(ValueError, match="3 tab/space-separated fields"):
        ObtParamFile.load(p)


@pytest.mark.requirement("SVF-DEV-149")
def test_obt_non_numeric_obt_raises(tmp_path: Path) -> None:
    """Non-numeric OBT raises ValueError."""
    p = _write_tsv(tmp_path, "START   param.x   1.0\n")
    with pytest.raises(ValueError, match="OBT column is not numeric"):
        ObtParamFile.load(p)


@pytest.mark.requirement("SVF-DEV-149")
def test_obt_non_numeric_value_raises(tmp_path: Path) -> None:
    """Non-numeric VALUE raises ValueError."""
    p = _write_tsv(tmp_path, "0.0   param.x   ON\n")
    with pytest.raises(ValueError, match="VALUE column is not numeric"):
        ObtParamFile.load(p)


# ── entries_due cursor ────────────────────────────────────────────────────────

@pytest.mark.requirement("SVF-DEV-150")
def test_entries_due_returns_only_past_entries(tmp_path: Path) -> None:
    """entries_due returns entries with OBT <= t only."""
    p = _write_tsv(tmp_path, """\
        0.0    param.a   1.0
        0.5    param.b   2.0
        1.0    param.c   3.0
    """)
    obf = ObtParamFile.load(p)
    due = obf.entries_due(t=0.5)
    assert len(due) == 2
    assert due[0].name == "param.a"
    assert due[1].name == "param.b"


@pytest.mark.requirement("SVF-DEV-150")
def test_entries_due_each_entry_returned_once(tmp_path: Path) -> None:
    """Each entry is returned by entries_due exactly once."""
    p = _write_tsv(tmp_path, """\
        0.0    param.a   1.0
        0.5    param.b   2.0
    """)
    obf = ObtParamFile.load(p)
    first  = obf.entries_due(t=1.0)
    second = obf.entries_due(t=1.0)
    assert len(first) == 2
    assert len(second) == 0


@pytest.mark.requirement("SVF-DEV-150")
def test_entries_due_reset_replays(tmp_path: Path) -> None:
    """After reset(), entries_due returns all entries again."""
    p = _write_tsv(tmp_path, "0.0   param.a   1.0\n")
    obf = ObtParamFile.load(p)
    obf.entries_due(t=0.0)
    obf.reset()
    assert len(obf.entries_due(t=0.0)) == 1


# ── SVF-DEV-151: spacecraft config loader path resolution ────────────────────

@pytest.mark.requirement("SVF-DEV-151")
def test_obt_path_resolved_relative_to_yaml_dir(tmp_path: Path) -> None:
    """
    The path written in spacecraft.yaml is resolved relative to the YAML
    directory — matching what SpacecraftLoader does with (path.parent / obt_init_path).
    """
    init_tsv = tmp_path / "init.tsv"
    init_tsv.write_text("0.0\tparam.x\t42.0\n")

    # Simulate what SpacecraftLoader does:
    yaml_dir   = tmp_path
    obt_init_path = "init.tsv"
    resolved   = yaml_dir / obt_init_path

    obf = ObtParamFile.load(resolved)
    assert len(obf) == 1
    assert obf.entries[0] == ObtEntry(obt=0.0, name="param.x", value=42.0)


@pytest.mark.requirement("SVF-DEV-151")
def test_spacecraft_loader_passes_obt_file_to_master(tmp_path: Path) -> None:
    """SpacecraftLoader wires obt_init_file into SimulationMaster._obt_param_file."""
    import yaml
    from svf.config.spacecraft import SpacecraftLoader

    init_tsv = tmp_path / "init.tsv"
    init_tsv.write_text("0.0\tparam.x\t7.0\n")

    spacecraft_yaml = tmp_path / "spacecraft.yaml"
    spacecraft_yaml.write_text(yaml.dump({
        "version": 1,
        "spacecraft": "TestSat",
        "obsw": {"type": "stub"},
        "simulation": {
            "dt": 0.1,
            "stop_time": 0.1,
            "obt_init_file": "init.tsv",
        },
    }))

    master = SpacecraftLoader.load(spacecraft_yaml)
    assert master._obt_param_file is not None
    assert len(master._obt_param_file) == 1
    assert master._obt_param_file.entries[0].value == pytest.approx(7.0)


# ── SimulationMaster integration ──────────────────────────────────────────────

@pytest.mark.requirement("SVF-DEV-150")
def test_simulation_master_injects_obt_entries_at_correct_time(
    tmp_path: Path,
) -> None:
    """SimulationMaster injects OBT entries into CommandStore at the right tick."""
    from svf.core.native_equipment import NativeEquipment
    from svf.core.equipment import PortDefinition, PortDirection

    injected: list[tuple[float, str, float]] = []

    def _step(eq: NativeEquipment, t: float, dt: float) -> None:
        cmd_store = eq._command_store
        if cmd_store is None:
            return
        for name in ("param.early", "param.late"):
            entry = cmd_store.take(name)
            if entry is not None:
                injected.append((t, entry.name, entry.value))

    sync      = _NoSync()
    store     = ParameterStore()
    cmd_store = CommandStore()

    eq = NativeEquipment(
        equipment_id="probe",
        ports=[PortDefinition("probe.out", PortDirection.OUT)],
        step_fn=_step,
        sync_protocol=sync,
        store=store,
        command_store=cmd_store,
    )

    p = _write_tsv(tmp_path, """\
        0.0   param.early   10.0
        0.5   param.late    20.0
    """)
    obf = ObtParamFile.load(p)

    master = SimulationMaster(
        tick_source=SoftwareTickSource(),
        sync_protocol=sync,
        models=[eq],
        dt=0.1,
        stop_time=1.0,
        command_store=cmd_store,
        param_store=store,
        obt_param_file=obf,
    )
    master.run()

    names  = [i[1] for i in injected]
    assert "param.early" in names
    assert "param.late"  in names

    # early must have been seen before late
    t_early = next(i[0] for i in injected if i[1] == "param.early")
    t_late  = next(i[0] for i in injected if i[1] == "param.late")
    assert t_early < t_late

    # early at t=0.0 (first tick), late at or after t=0.5
    assert t_early == pytest.approx(0.0)
    assert t_late  >= 0.5
