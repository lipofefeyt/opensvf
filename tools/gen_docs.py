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
    from svf.tools.checkcons import current_compatibility
    pyproject = (REPO / "pyproject.toml").read_text()
    python = re.search(r'^requires-python\s*=\s*"([^"]+)"', pyproject, re.M)
    ci = re.findall(r'python-version:\s*"([^"]+)"',
                    (REPO / ".github" / "workflows" / "ci.yml").read_text())
    if not (python and ci):
        raise CheckError("requires-python or CI python-version not found")
    return {
        **current_compatibility(REPO),
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

    from svf.tools.checkcons import compatibility_mismatches
    problems = compatibility_mismatches(REPO, cur)
    if problems:
        raise CheckError("; ".join(problems))
    releases = yaml.safe_load(
        (REPO / "docs" / "compatibility.yaml").read_text())["releases"]
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


# ── ICD: what the OBC adapter sends and decodes ──────────────────────────────

OPENOBSW_DOCS = "https://openobsw.readthedocs.io/en/{pin}/"


def gen_icd() -> dict[str, str]:
    from svf.models.dhs import obc_emulator as emu
    from svf.models.dhs.obc import MODE_NOMINAL, MODE_SAFE, MODE_STANDBY
    from svf.srdb.loader import load_bundled_hk_sets
    from svf.stores.parameter_store import ParameterStore

    pin = (REPO / ".openobsw-version").read_text().strip()
    base = OPENOBSW_DOCS.format(pin=pin)
    links = (
        f"openobsw `{pin}` (the pinned release) owns the frame definitions: "
        f"[wire protocol ICD]({base}icd/), "
        f"[SRDB parameters]({base}srdb/parameters/), "
        f"[events]({base}srdb/events/), "
        f"[telecommands]({base}srdb/telecommands/) and "
        f"[housekeeping sets]({base}srdb/hk-sets/).\n")
    tree = f"https://github.com/lipofefeyt/openobsw/tree/{pin}/"
    contrib = (
        f"openobsw `{pin}` ships a drop-in implementation of the wire protocol "
        f"for other flight software, "
        f"[`contrib/svf_protocol/`]({tree}contrib/svf_protocol): "
        f"`obsw_svf_protocol.h` and `.c`, with platform glue for Linux stdio "
        f"and the ZynqMP UART. Its "
        f"[integration guide]({base}integration-guide/#adding-the-wire-protocol-to-another-obsw) "
        f"shows the main loop.\n")
    banner = ("```text\n[OBSW] Host sim started "
              f"(wire protocol v{emu.WIRE_PROTOCOL_VERSION}).\n```\n")

    names = {MODE_STANDBY: "STANDBY", MODE_SAFE: "SAFE", MODE_NOMINAL: "NOMINAL"}
    adapter = emu.OBCEmulatorAdapter(sim_path=None, sync_protocol=MagicMock(),
                                     store=ParameterStore())
    tcs = []
    for mode, fid in sorted(emu._S8_MODE_FUNCTION.items()):
        adapter._tc_seq = 0
        tcs.append([f"`dhs.obc.mode_cmd` = {mode} ({names[mode]})",
                    f"TC(8,1), function ID {fid}",
                    f"`{adapter._build_s8_perform(fid).hex()}`"])
    adapter._tc_seq = 0
    tcs.append(["`dhs.obc.watchdog_kick` > 0.5", "TC(17,1)",
                f"`{adapter._build_s17_ping().hex()}`"])
    tcs.append(["`dhs.obc.time_sync_cmd` = 1000 (any value >= 0)",
                "TC(9,128), OBT in seconds",
                f"`{adapter._build_s9_set_obt(1000.0).hex()}`"])

    events = [[f"`0x{eid:04X}`", f"{mode} ({names[mode]})"]
              for eid, mode in sorted(emu.S5_MODE_EVENTS.items())]
    codes = [[f"`0x{c:04X}`", n] for c, n in sorted(emu.S1_FAILURE_CODES.items())]

    sets = []
    for sid, hk in sorted(load_bundled_hk_sets().items()):
        sets.append([sid, f"`{hk.name}`",
                     ", ".join(f"`{p.obsw_name}` {p.wire_type.value}"
                               for p in hk.parameters)])

    checks = re.findall(r'print\("  \[(\d+)/\d+\] (.+?)(?:\.\.\.|")',
                        (REPO / "src" / "svf" / "tools" / "checkcons.py").read_text())
    seen: dict[int, str] = {}
    for n, title in checks:
        seen.setdefault(int(n), title.strip())
    return {
        "openobsw-links.md": links,
        "openobsw-contrib.md": contrib,
        "openobsw-targets.md": (
            f"Which openobsw `{pin}` targets run in CI and which were bench-tested, "
            f"and the PUS services each one routes, is on the openobsw "
            f"[targets]({base}targets/) page.\n"),
        "obsw-banner.md": banner,
        "icd-adapter-tcs.md": _table(
            ["Set by a procedure", "TC sent", "Example bytes"], tcs),
        "icd-s5-mode-events.md": _table(["Event ID", "Mode hint (`obc_mode`)"], events),
        "icd-s1-codes.md": _table(["Failure code", "Meaning"], codes),
        "icd-hk-sets.md": _table(["Set", "Name", "Parameters in report order"], sets),
        "icd-checkcons.md": "\n".join(f"{n}. {t}" for n, t in sorted(seen.items())) + "\n",
    }


# ── PUS services ─────────────────────────────────────────────────────────────

def gen_pus() -> dict[str, str]:
    import ast
    rows = []
    for f in sorted((REPO / "src" / "svf" / "pus" / "services").glob("s[0-9]*.py")):
        doc = ast.get_docstring(ast.parse(f.read_text())) or ""
        m = re.match(r"PUS Service (\d+)\s+-\s+(.+?)\.?$", doc.splitlines()[0] if doc else "")
        if m is None:
            raise CheckError(f"{f.name}: docstring does not start with "
                             f"'PUS Service <n>  -  <name>.'")
        rows.append([f"S{m.group(1)}", m.group(2), f"`svf.pus.services.{f.stem}`"])
    pin = (REPO / ".openobsw-version").read_text().strip()
    note = (f"\nWhich services openobsw `{pin}` implements on each target is on its "
            f"[targets]({OPENOBSW_DOCS.format(pin=pin)}targets/) page.\n")
    return {"pus-services.md": _table(["Service", "Name", "Module"], rows) + note}


# ── Imports shown in the docs ────────────────────────────────────────────────

_IMPORT_RE = re.compile(r"^[ \t>]*(from[ \t]+svf[\w.]*[ \t]+import[ \t]+(?:\([^)]*\)|[^\n#]+)"
                        r"|import[ \t]+svf[\w.]*)", re.M)


def check_doc_imports() -> None:
    """Every `from svf... import` / `import svf...` line in a docs page imports."""
    bad = []
    for md in sorted((REPO / "docs").rglob("*.md")):
        if OUT in md.parents:
            continue
        for m in _IMPORT_RE.finditer(md.read_text()):
            stmt = " ".join(m.group(1).split())
            try:
                exec(stmt, {})  # noqa: S102 - our own docs
            except Exception as e:  # noqa: BLE001
                line = md.read_text()[:m.start()].count("\n") + 1
                bad.append(f"{md.relative_to(REPO)}:{line}: {stmt}: {e}")
    if bad:
        raise CheckError("imports in the docs that fail:\n  " + "\n  ".join(bad))


def main() -> int:
    try:
        pages: dict[str, str] = {}
        check_doc_imports()
        for gen in (gen_compatibility, gen_equipment, gen_fidelity, gen_yamcs,
                    gen_icd, gen_pus):
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
