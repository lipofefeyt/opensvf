#!/usr/bin/env python3
"""
Generate the reference tables of the documentation site into docs/_gen/.

Run before `mkdocs build` (Read the Docs runs it as a pre_build job, CI in
the docs job). The pages include the tables with pymdownx.snippets, so a
table is never edited by hand and never committed: it is rebuilt from its
source at every build.

  compatibility-current.md   pyproject.toml, .openobsw-version, the adapter's
                             wire protocol constants, the CI Python version
  compatibility-history.md   docs/compatibility.yaml, checked against the above
  equipment-summary.md       the spacecraft loader's model registry, fidelity
                             from checkcov's EQUIPMENT_FIDELITY
  equipment-ports.md         every port each registry model declares
  fidelity.md                checkcov fidelity rows (SRDB TM params, curves)
  yamcs-tm.md, yamcs-parameters.md, yamcs-commands.md
                             yamcs/mdb/opensvf.xml, checked to be what
                             tools/generate_xtce.py produces from the SRDB

Exits non-zero, writing nothing, when a check fails.

Usage:
    python3 tools/gen_docs.py
"""

from __future__ import annotations

import importlib
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import yaml

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

OUT = REPO / "docs" / "_gen"
XTCE = REPO / "yamcs" / "mdb" / "opensvf.xml"
NS = {"x": "http://www.omg.org/spec/XTCE/20180204"}

# An example TLE so the orbital environment can be built to list its ports.
_TLE = (
    "1 25544U 98067A   26001.50000000  .00002182  00000-0  40084-4 0  9995",
    "2 25544  51.6416  87.8613 0006828  93.5613  23.7542 15.49499526431108",
)


class CheckError(Exception):
    """A documentation source disagrees with the code it describes."""


def _cell(text: Any) -> str:
    """Make a value safe for a Markdown table cell."""
    return str(text).replace("|", "\\|").replace("\n", " ").strip()


def _table(header: list[str], rows: list[list[Any]]) -> str:
    lines = ["| " + " | ".join(header) + " |",
             "|" + "|".join("---" for _ in header) + "|"]
    lines += ["| " + " | ".join(_cell(c) for c in row) + " |" for row in rows]
    return "\n".join(lines) + "\n"


# ── Compatibility ────────────────────────────────────────────────────────────

def _current() -> dict[str, Any]:
    from svf.models.dhs import obc_emulator
    pyproject = (REPO / "pyproject.toml").read_text()
    version = re.search(r'^version\s*=\s*"([^"]+)"', pyproject, re.M)
    python = re.search(r'^requires-python\s*=\s*"([^"]+)"', pyproject, re.M)
    ci = re.findall(r'python-version:\s*"([^"]+)"',
                    (REPO / ".github" / "workflows" / "ci.yml").read_text())
    if not (version and python and ci):
        raise CheckError("version, requires-python or CI python-version not found")
    return {
        "opensvf": version.group(1),
        "openobsw": (REPO / ".openobsw-version").read_text().strip(),
        "wire_protocol": obc_emulator.WIRE_PROTOCOL_VERSION,
        "sensor_frame_bytes": obc_emulator._SENSOR_LEN,
        "python": python.group(1),
        "python_ci": ", ".join(sorted(set(ci))),
    }


def gen_compatibility() -> dict[str, str]:
    cur = _current()
    current = _table(
        ["", "This version"],
        [["opensvf", cur["opensvf"]],
         ["openobsw (pinned in `.openobsw-version`)", f"`{cur['openobsw']}`"],
         ["Wire protocol", f"v{cur['wire_protocol']}"],
         ["Sensor frame (type `0x02`)", f"{cur['sensor_frame_bytes']} bytes"],
         ["Python", f"`{cur['python']}`; CI runs {cur['python_ci']}"]])

    history = yaml.safe_load((REPO / "docs" / "compatibility.yaml").read_text())
    releases = history["releases"]
    mine = [r for r in releases if str(r["opensvf"]) == cur["opensvf"]]
    if not mine:
        raise CheckError(
            f"docs/compatibility.yaml has no row for opensvf {cur['opensvf']}")
    row = mine[0]
    for key in ("openobsw", "wire_protocol", "sensor_frame_bytes"):
        if row[key] != cur[key]:
            raise CheckError(
                f"docs/compatibility.yaml opensvf {cur['opensvf']}: {key} is "
                f"{row[key]!r}, the code says {cur[key]!r}")
    rows = [[r["opensvf"],
             f"`{r['openobsw']}`" if r.get("openobsw") else "not pinned",
             f"v{r['wire_protocol']}" if r.get("wire_protocol") else "",
             f"{r['sensor_frame_bytes']} B" if r.get("sensor_frame_bytes") else "",
             r.get("notes", "")]
            for r in releases]
    return {
        "compatibility-current.md": current,
        "compatibility-history.md": _table(
            ["opensvf", "openobsw", "Wire protocol", "Sensor frame", "Notes"], rows),
    }


# ── Equipment ────────────────────────────────────────────────────────────────

def _models() -> list[tuple[str, str, Any]]:
    """(registry name, factory, equipment) for every registry model."""
    from svf.config.spacecraft import _MODEL_REGISTRY
    from svf.stores.command_store import CommandStore
    from svf.stores.parameter_store import ParameterStore
    out = []
    for name, (module, factory_name) in sorted(_MODEL_REGISTRY.items()):
        factory = getattr(importlib.import_module(module), factory_name)
        kwargs: dict[str, Any] = {}
        if name == "orbital_environment":
            kwargs = {"tle_line1": _TLE[0], "tle_line2": _TLE[1]}
        eq = factory(MagicMock(), ParameterStore(), CommandStore(), **kwargs)
        out.append((name, f"{module}.{factory_name}", eq))
    return out


def gen_equipment() -> dict[str, str]:
    from svf.core.equipment import PortDirection
    from svf.tools.checkcov import EQUIPMENT_FIDELITY
    summary, sections = [], []
    for name, factory, eq in _models():
        ports = list(eq.ports.values())
        n_in = sum(1 for p in ports if p.direction == PortDirection.IN)
        level = (EQUIPMENT_FIDELITY.get(eq.equipment_id)
                 or EQUIPMENT_FIDELITY.get(name))
        summary.append([f"[`{name}`](#{name})",
                        f"`{factory}()`", f"`{eq.equipment_id}`",
                        n_in, len(ports) - n_in,
                        level[0] if level else "not declared"])
        sections.append(
            f"### {name}\n\n`{factory}()`, default equipment ID "
            f"`{eq.equipment_id}`.\n\n"
            + _table(["Port", "Direction", "Unit", "Description"],
                     [[f"`{p.name}`", p.direction.name, p.unit or "",
                       p.description or ""] for p in ports]))
    return {
        "equipment-summary.md": _table(
            ["Model (`model:` in spacecraft YAML)", "Factory", "Default ID",
             "IN", "OUT", "Fidelity"], summary),
        "equipment-ports.md": "\n".join(sections),
    }


def gen_fidelity() -> dict[str, str]:
    from svf.tools.checkcov import fidelity_rows
    rows = fidelity_rows(REPO / "srdb" / "baseline")
    bad = [r for r in rows if r.error]
    if bad:
        raise CheckError("; ".join(f"{r.model_id}: {r.error}" for r in bad))
    return {"fidelity.md": _table(
        ["SRDB model", "Name", "Level", "TM parameters", "Calibrated", "Next step"],
        [[f"`{r.model_id}`", r.display, r.level, r.tm_params, r.calibrated,
          r.upgrade] for r in rows])}


# ── YAMCS mission database ───────────────────────────────────────────────────

def _check_xtce() -> None:
    generated = subprocess.run(
        [sys.executable, str(REPO / "tools" / "generate_xtce.py")],
        cwd=REPO, capture_output=True, text=True, check=True,
        env={"PYTHONPATH": str(REPO / "src"), "PATH": "/usr/bin:/bin"},
    ).stdout
    if generated != XTCE.read_text():
        raise CheckError(
            "yamcs/mdb/opensvf.xml is not what tools/generate_xtce.py produces "
            "from the SRDB; regenerate it")


def gen_yamcs() -> dict[str, str]:
    _check_xtce()
    root = ET.parse(XTCE).getroot()

    def desc(el: ET.Element) -> str:
        d = el.find("x:LongDescription", NS)
        return d.text.strip() if d is not None and d.text else ""

    params = [[f"`{p.get('name')}`", f"`{p.get('parameterTypeRef')}`", desc(p)]
              for p in root.iterfind(".//x:ParameterSet/x:Parameter", NS)]

    containers = {c.get("name"): c for c in
                  root.iterfind(".//x:ContainerSet/x:SequenceContainer", NS)}

    def criteria(c: ET.Element) -> dict[str, str]:
        """Restriction criteria of a container and all its base containers."""
        out: dict[str, str] = {}
        base = c.find("x:BaseContainer", NS)
        if base is not None:
            parent = containers.get(base.get("containerRef"))
            if parent is not None:
                out.update(criteria(parent))
            for k in base.iterfind(".//x:Comparison", NS):
                out[str(k.get("parameterRef"))] = str(k.get("value"))
        return out

    tm = []
    for name, c in containers.items():
        if c.get("abstract") == "true":
            continue
        cmp = criteria(c)
        packet = f"TM({cmp.pop('pus_svc', '?')},{cmp.pop('pus_subsvc', '?')})"
        if cmp:
            packet += ", " + ", ".join(f"`{k}` = {v}" for k, v in cmp.items())
        entries = [e.get("parameterRef")
                   for e in c.iterfind("x:EntryList/x:ParameterRefEntry", NS)]
        tm.append([f"`{name}`", packet,
                   ", ".join(f"`{e}`" for e in entries) or "none", desc(c)])

    cmds = []
    for m in root.iterfind(".//x:MetaCommandSet/x:MetaCommand", NS):
        args = [a.get("name") for a in m.iterfind("x:ArgumentList/x:Argument", NS)]
        cmds.append([f"`{m.get('name')}`",
                     ", ".join(f"`{a}`" for a in args) or "none", desc(m)])

    return {
        "yamcs-tm.md": _table(["Container", "Packet", "Parameters", "Description"], tm),
        "yamcs-parameters.md": _table(["Parameter", "Type", "Description"], params),
        "yamcs-commands.md": _table(["Command", "Arguments", "Description"], cmds),
    }


def main() -> int:
    try:
        pages: dict[str, str] = {}
        for gen in (gen_compatibility, gen_equipment, gen_fidelity, gen_yamcs):
            pages.update(gen())
    except CheckError as e:
        print(f"gen_docs: {e}", file=sys.stderr)
        return 1
    OUT.mkdir(parents=True, exist_ok=True)
    for name, text in sorted(pages.items()):
        (OUT / name).write_text(text)
    print(f"gen_docs: wrote {len(pages)} tables to {OUT.relative_to(REPO)}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
