"""
checksmp - SMP-aligned catalogue consistency check.

Verifies that smp/opensvf.smpcat:
  1. Exists and is well-formed XML
  2. Carries the opensvf SMP-aligned namespace (not the ESA SMP one)
  3. Has exactly one Field per SRDB parameter (no drift)
  4. Maps TM -> Output and TC -> Input with no cross-contamination

Exit code 0 = all checks pass, 1 = one or more failures.

Usage: checksmp  (registered as a project script)
"""

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from svf.smp.interfaces import SMP_ALIGNED_NS as _NS

_SMPCAT   = Path("smp/opensvf.smpcat")
_SRDB_DIR = Path("srdb/baseline")


def _load_srdb():
    from svf.srdb.definitions import Classification
    from svf.srdb.loader import SrdbLoader
    loader = SrdbLoader()
    for baseline in sorted(_SRDB_DIR.glob("*.yaml")):
        loader.load_baseline(baseline)
    return loader.build(), Classification


def _ok(msg: str) -> None:
    print(f"  [PASS] {msg}")


def _fail(msg: str) -> None:
    print(f"  [FAIL] {msg}", file=sys.stderr)


def run_checks() -> int:
    failures = 0

    print("checksmp: SMP-aligned catalogue consistency")
    print("=" * 44)

    # ── check 1: file exists ──────────────────────────────────────────────────
    if not _SMPCAT.exists():
        _fail(f"{_SMPCAT} not found - run: python3 tools/generate_smpcat.py > {_SMPCAT}")
        return 1
    _ok(f"{_SMPCAT} exists")

    # ── check 2: well-formed XML ──────────────────────────────────────────────
    try:
        root = ET.parse(str(_SMPCAT)).getroot()
    except ET.ParseError as exc:
        _fail(f"XML parse error: {exc}")
        return 1
    _ok("well-formed XML")

    # ── check 3: correct namespace ────────────────────────────────────────────
    if root.tag != f"{{{_NS}}}Catalogue":
        _fail(f"root tag '{root.tag}' - expected '{{{_NS}}}Catalogue'")
        failures += 1
    else:
        _ok(f"namespace {_NS}")

    # ── check 4: field count matches SRDB ────────────────────────────────────
    try:
        srdb, Classification = _load_srdb()
    except Exception as exc:
        _fail(f"SRDB load failed: {exc}")
        return failures + 1

    srdb_count  = len(srdb.parameter_names)
    field_count = sum(1 for _ in root.iter(f"{{{_NS}}}Field"))

    if field_count != srdb_count:
        _fail(
            f"field count mismatch: smpcat has {field_count}, "
            f"SRDB has {srdb_count} - regenerate with tools/generate_smpcat.py"
        )
        failures += 1
    else:
        _ok(f"field count matches SRDB ({srdb_count} parameters)")

    # ── check 5: direction mapping ────────────────────────────────────────────
    output_names = {
        f.attrib["Name"]
        for f in root.iter(f"{{{_NS}}}Field")
        if f.attrib.get("Kind") == "Output"
    }
    input_names = {
        f.attrib["Name"]
        for f in root.iter(f"{{{_NS}}}Field")
        if f.attrib.get("Kind") == "Input"
    }

    tm_violations = [
        p.name for p in srdb.by_classification(Classification.TM)
        if (".".join(p.name.split(".")[2:]) or p.name.split(".")[-1]) not in output_names
    ]
    tc_violations = [
        p.name for p in srdb.by_classification(Classification.TC)
        if (".".join(p.name.split(".")[2:]) or p.name.split(".")[-1]) not in input_names
    ]

    if tm_violations:
        _fail(f"TM params not mapped to Output: {tm_violations[:5]}")
        failures += 1
    else:
        _ok(f"all TM parameters map to Kind=Output")

    if tc_violations:
        _fail(f"TC params not mapped to Input: {tc_violations[:5]}")
        failures += 1
    else:
        _ok(f"all TC parameters map to Kind=Input")

    # ── summary ───────────────────────────────────────────────────────────────
    print()
    if failures:
        print(f"checksmp: {failures} check(s) failed")
    else:
        print("checksmp: all checks passed")

    return failures


def main() -> None:
    sys.exit(run_checks())
