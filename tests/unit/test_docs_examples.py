"""
L1 checks of the example files the docs include (docs/examples/), without a
flight software binary. The L3 suite runs the integrate-obsw files against
obsw_sim (tests/system/test_integrate_obsw_example.py).

Implements: SVF-DEV-222, SVF-DEV-223, SVF-DEV-224
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock

import pytest

from svf.campaign.campaign_runner import CampaignRunner
from svf.config.validator import SpacecraftValidator

_REPO = Path(__file__).parents[2]
_EXAMPLE = _REPO / "docs" / "examples" / "integrate-obsw"


@pytest.mark.requirement("SVF-DEV-222")
def test_integrate_obsw_example_spacecraft_validates() -> None:
    issues = SpacecraftValidator.from_file(_EXAMPLE / "spacecraft.yaml")
    assert issues == []


@pytest.mark.requirement("SVF-DEV-222")
def test_integrate_obsw_example_campaign_loads_its_procedure() -> None:
    runner = CampaignRunner.from_yaml(_EXAMPLE / "campaign.yaml")
    procs = runner._procedures
    assert [p.id for p in procs] == ["TC-INT-001"]
    assert runner._declared_requirements == [procs[0].requirement]
    assert runner._spacecraft_cfg.name == "spacecraft.yaml"


def _load(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_LAYER = Path(__file__).parents[2] / "docs" / "examples" / "abstraction-layer"


@pytest.mark.requirement("SVF-DEV-223")
def test_abstraction_layer_composition_root_runs() -> None:
    root = _load(_LAYER / "composition_root.py")
    speed = root.main(Path(__file__).parents[2] / "srdb" / "baseline")
    assert speed > 0.0


@pytest.mark.requirement("SVF-DEV-223")
def test_abstraction_layer_factory_gives_distinct_ports() -> None:
    from svf.stores.command_store import CommandStore
    from svf.stores.parameter_store import ParameterStore

    factory = _load(_LAYER / "native_equipment.py").make_toy_wheel
    sync, store, cmd = MagicMock(), ParameterStore(), CommandStore()
    a = factory(sync, store, cmd, equipment_id="rw_x")
    b = factory(sync, store, cmd, equipment_id="rw_y")
    assert set(a.ports) == {"aocs.rw_x.torque_cmd", "aocs.rw_x.speed"}
    assert set(b.ports) == {"aocs.rw_y.torque_cmd", "aocs.rw_y.speed"}

    a.initialise()
    cmd.inject("aocs.rw_x.torque_cmd", 0.5, source_id="test")
    a.on_tick(0.0, 0.1)
    entry = store.read("aocs.rw_x.speed")
    assert entry is not None and entry.value == pytest.approx(5.0)
    assert store.read("aocs.rw_y.speed") is None


_GEN_DOCS = Path(__file__).parents[2] / "tools" / "gen_docs.py"


@pytest.mark.requirement("SVF-DEV-223")
def test_every_svf_import_shown_in_the_docs_imports() -> None:
    _load(_GEN_DOCS).check_doc_imports()


@pytest.mark.requirement("SVF-DEV-223")
def test_a_stale_import_in_a_page_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gen = _load(_GEN_DOCS)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "page.md").write_text(
        "```python\nfrom svf.campaign.procedure import Procedure\n"
        "from svf.procedure import (\n    Procedure,\n)\n```\n")
    monkeypatch.setattr(gen, "REPO", tmp_path)
    monkeypatch.setattr(gen, "OUT", tmp_path / "docs" / "_gen")
    with pytest.raises(gen.CheckError, match=r"docs/page.md:3: from svf.procedure"):
        gen.check_doc_imports()


@pytest.mark.requirement("SVF-DEV-224")
def test_validation_tables_count_tests_and_requirements(tmp_path: Path) -> None:
    gen = _load(_GEN_DOCS)
    f = tmp_path / "test_sample.py"
    f.write_text(
        "import pytest\n"
        "pytestmark = [pytest.mark.requirement('MOD-1')]\n"
        "@pytest.mark.requirement('A-1', 'A-2')\n"
        "def test_a(): pass\n"
        "def helper(): pass\n"
        "@pytest.mark.requirement('C-1')\n"
        "class ThingSuite:\n"
        "    def test_b(self): pass\n"
        "    @pytest.mark.requirement('B-1')\n"
        "    def test_c(self): pass\n"
        "class TestIgnored:\n"
        "    @pytest.mark.requirement('X-1')\n"
        "    def test_d(self): pass\n")
    n, reqs = gen._test_file(f)
    assert n == 3
    assert reqs == {"MOD-1", "A-1", "A-2", "C-1", "B-1"}


@pytest.mark.requirement("SVF-DEV-224")
def test_validation_tables_list_every_campaign() -> None:
    gen = _load(_GEN_DOCS)
    tables = gen.gen_validation()
    campaigns = sorted(p.name for p in (_REPO / "mission_mysat1" / "campaigns").glob("*.yaml"))
    assert all(f"`{c}`" in tables["validation-l4.md"] for c in campaigns)
    assert "`test_integrate_obsw_example.py`" in tables["validation-l3.md"]
