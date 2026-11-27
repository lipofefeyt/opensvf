"""
L1 tests for tools/build_datapack.py: the data pack Markdown is the site
pages with snippets expanded, admonitions as block quotes and page links
pointing at the versioned site. pandoc is not run here.

Implements: SVF-DEV-226
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

_REPO = Path(__file__).parents[2]


def _tool() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "build_datapack", _REPO / "tools" / "build_datapack.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.requirement("SVF-DEV-226")
def test_snippets_expand_files_and_sections_with_indentation(tmp_path: Path) -> None:
    dp = _tool()
    (tmp_path / "table.md").write_text("| a |\n|---|\n| 1 |\n")
    (tmp_path / "code.py").write_text("x = 0\n# --8<-- [start:part]\ny = 1\n# --8<-- [end:part]\nz = 2\n")
    page = ('Intro\n--8<-- "table.md"\n\n1. step:\n\n    --8<-- "code.py:part"\n')
    out = dp.expand_snippets(page, repo=tmp_path)
    assert "| 1 |" in out and "--8<--" not in out
    assert "    y = 1" in out and "x = 0" not in out and "z = 2" not in out


@pytest.mark.requirement("SVF-DEV-226")
def test_missing_snippet_or_section_is_an_error(tmp_path: Path) -> None:
    dp = _tool()
    (tmp_path / "code.py").write_text("y = 1\n")
    with pytest.raises(dp.DatapackError, match="not found"):
        dp.expand_snippets('--8<-- "absent.md"\n', repo=tmp_path)
    with pytest.raises(dp.DatapackError, match="no snippet section"):
        dp.expand_snippets('--8<-- "code.py:part"\n', repo=tmp_path)


@pytest.mark.requirement("SVF-DEV-226")
def test_admonition_becomes_a_block_quote() -> None:
    out = _tool().convert_admonitions(
        'Before\n\n!!! warning "Print the banner"\n    Line one\n    line two.\n\nAfter\n')
    assert "> **Print the banner.**" in out
    assert "> Line one" in out and "> line two." in out
    assert "!!!" not in out and "After" in out


@pytest.mark.requirement("SVF-DEV-226")
def test_page_links_point_at_the_versioned_site() -> None:
    out = _tool().rewrite_links(
        "See [ICD](icd.md#one-tick), [home](index.md), [here](#local), "
        "[gh](https://github.com/x).\n```\n[not](code.md)\n```\n", "1.4.0")
    assert "](https://opensvf.readthedocs.io/en/1.4.0/icd/#one-tick)" in out
    assert "](https://opensvf.readthedocs.io/en/1.4.0/)" in out
    assert "](#local)" in out and "](https://github.com/x)" in out
    assert "[not](code.md)" in out


@pytest.mark.requirement("SVF-DEV-226")
def test_every_document_builds_from_the_repository_pages() -> None:
    dp = _tool()
    for doc, pages in dp.DOCUMENTS.items():
        assert all((_REPO / "docs" / p).is_file() for p in pages)
        md = dp.build_markdown(doc, "9.9.9", "2026-01-01") \
            if (_REPO / "docs" / "_gen").is_dir() else None
        if md is None:
            pytest.skip("docs/_gen not generated")
        assert md.startswith("---\n") and "opensvf 9.9.9" in md and "{version}" not in md
        assert "--8<--" not in md and "\n!!! " not in md
