"""
SVF Requirement Coverage Checker
Cross-references REQUIREMENTS.md BASELINED requirements against
the traceability matrix. Reports uncovered requirements.
Also reports a fidelity coverage section (F1–F4 per model, calibration gap).

Usage: python3 tools/check_coverage.py (alias: checkcov)

Implements: SVF-DEV-155
"""

import re
import sys
from pathlib import Path

# Requirements that are BASELINED but not yet implemented.
# Each entry must have a justification and target milestone.
# Requirements that are BASELINED/IMPLEMENTED but verified by process/CI, not code.
KNOWN_GAPS: dict[str, str] = {
    "SVF-DEV-060": "Verified by validate_fmpy.py script",
    "SVF-DEV-136": "Verified by generate_xtce.py tool — XTCE output inspected manually",
    "SVF-DEV-137": "Verified by start-yamcs.sh/stop-yamcs.sh scripts in CI",
    "SVF-DEV-138": "Verified by yamcs.opensvf.yaml config — PusPacketPreprocessor with useLocalGenerationTime=true",
    "SVF-DEV-070": "Verified by JUnit XML presence in results/",
    "SVF-DEV-072": "Verified by traceability.txt generation",
    "SVF-DEV-080": "Verified by pyproject.toml presence",
    "SVF-DEV-081": "Verified by CI pipeline on Ubuntu-latest",
    "SVF-DEV-087": "Verified by CI pipeline coverage gate",
    "SVF-DEV-088": "Verified by CI pipeline mypy gate",

    # 1553 bus fault injection — tested via test_bus.py (generic bus)
    # and test_mil1553.py. Specific fault type markers need adding.
    "1553-007": "Verified by test_fault_is_active_immediately in test_bus.py",
    "1553-008": "Verified by test_fault_expires_after_duration in test_bus.py",
    "1553-009": "Verified by test_fault_injected_via_command_store in test_bus.py and test_mil1553.py",

    # svf_command_schedule — implemented, test marker pending
    "SVF-DEV-048": "Verified by test_tc_pwr_003_charging_in_sunlight (uses svf_command_schedule)",

    # Reporting
    "SVF-DEV-071": "Verified by JUnit XML and HTML report generation in CI",

    # Hardware/infrastructure — verified by CI or hardware tests
    "SVF-DEV-100": "Verified by tests/hardware/test_aarch64_obsw.py (excluded from default run)",
    "SVF-DEV-101": "Verified by tests/hardware/test_renode_zynqmp.py (excluded from default run)",
    "SVF-DEV-130": "Verified by HardwareProfile bundled search — exercised by every campaign run",
}


# ── Fidelity table ────────────────────────────────────────────────────────────
#
# Maps SRDB model_id → (fidelity_level, display_name, f3_upgrade_note)
# Derived from docs/equipment-library.md.  Update here when a model is
# promoted; checkcov will catch inconsistencies with the SRDB automatically.
#
# F1 = functional stub   F2 = behavioural   F3 = high-fidelity   F4 = validated
#
EQUIPMENT_FIDELITY: dict[str, tuple[str, str, str]] = {
    # model_id            level   display name           F3 upgrade path
    "mag":    ("F2", "Magnetometer",       "Add polynomial calibration for field_x/y/z bias and scale"),
    "gyro":   ("F2", "Gyroscope",          "Add Allan-variance noise model + temperature calibration"),
    "rw1":    ("F2", "Reaction Wheel",     "Add nonlinear friction and bearing temperature model"),
    "str1":   ("F2", "Star Tracker",       "Add centroiding noise model + aberration correction"),
    "css":    ("F2", "Coarse Sun Sensor",  "Add cosine response calibration polynomial per face"),
    "gps":    ("F2", "GPS Receiver",       "Add ionospheric/tropospheric delay model"),
    "mtq":    ("F2", "Magnetorquer",       "Add hysteresis model + cross-coupling matrix"),
    "aocs":   ("F2", "AOCS (generic)",     "Promote constituent sensor models to F3 individually"),
    "pcdu":   ("F2", "PCDU",               "Add temperature-dependent efficiency curves"),
    "eps":    ("F2", "EPS (generic)",      "Add MPPT nonlinear I-V curve + thermal derating"),
    "sbt":    ("F2", "S-Band Transponder", "Add link budget model with rain fade and Doppler"),
    "ttc":    ("F2", "TTC (generic)",      "Add channel model with AWGN and Doppler"),
    "thermal":("F2", "Thermal Model",      "Add radiation view-factor matrix + MLI model"),
    "obc":    ("F2", "OBC",                "Use OBCEmulatorAdapter with real OBSW binary for F4"),
    "obdh":   ("F2", "OBDH (generic)",     "Add realistic memory and CPU load model"),
    # F3 and F4 models
    "dynamics": ("F3", "KDE Dynamics (FMI)", "Add flex modes from modal test data for F4"),
    # Functional stubs
    "obc_stub": ("F1", "OBC Stub",         "Use OBCEmulatorAdapter for F4"),
    "obc_emulator": ("F4", "OBC Emulator", "Already F4 — real OBSW binary in the loop"),
}


# ── Requirement coverage ──────────────────────────────────────────────────────

def parse_baselined_requirements(req_file: Path) -> set[str]:
    """Extract all BASELINED and IMPLEMENTED requirement IDs from REQUIREMENTS.md."""
    content = req_file.read_text()
    required_ids = set()
    pattern = re.compile(
        r'\*\*([\w-]+)\*\*\s+`\[[\w\d]+\]`\s+`(BASELINED|IMPLEMENTED)`',
        re.MULTILINE
    )
    for match in pattern.finditer(content):
        required_ids.add(match.group(1))
    return required_ids


def parse_covered_requirements(matrix_file: Path) -> set[str]:
    """Extract all requirement IDs from the traceability matrix."""
    if not matrix_file.exists():
        return set()
    covered = set()
    for line in matrix_file.read_text().splitlines():
        parts = line.split()
        if parts and re.match(r'^[\w-]+-\d+$', parts[0]):
            covered.add(parts[0])
    return covered


# ── Fidelity report ───────────────────────────────────────────────────────────

def fidelity_report(srdb_dir: Path) -> bool:
    """
    Print fidelity coverage section.

    Returns True if the report is clean (no errors — inconsistencies between
    a model's declared fidelity and its SRDB calibration state are errors).
    Warnings are printed for F2 models with uncalibrated TM parameters (upgrade
    candidates). These are informational and do not affect the exit code.

    Implements: SVF-DEV-155
    """
    if not srdb_dir.exists():
        print("\n[fidelity] srdb/baseline/ not found — skipping fidelity report")
        return True

    # Load SRDB
    svf_src = srdb_dir.parents[1] / "src"
    if str(svf_src) not in sys.path:
        sys.path.insert(0, str(svf_src))

    try:
        from svf.srdb.loader import SrdbLoader
        from svf.srdb.definitions import Classification
    except ImportError as e:
        print(f"\n[fidelity] Cannot import SVF SRDB — skipping: {e}")
        return True

    loader = SrdbLoader()
    for f in sorted(srdb_dir.glob("*.yaml")):
        loader.load_baseline(f)
    srdb = loader.build()

    # Group TM params by model_id
    from collections import defaultdict
    tm_by_model: dict[str, list[str]] = defaultdict(list)
    for name, defn in srdb._parameters.items():
        if defn.classification == Classification.TM:
            tm_by_model[defn.model_id].append(name)

    # ── Per-model table ────────────────────────────────────────────────────
    col = 20
    print("\n" + "─" * 72)
    print("  Equipment fidelity coverage")
    print("─" * 72)
    print(f"  {'Model':<{col}} {'Level':<6} {'TM params':>9} {'Calibrated':>10}  Note")
    print(f"  {'─'*col} {'─'*5} {'─'*9} {'─'*10}")

    errors_found = False
    f2_uncalibrated_total = 0
    f2_uncalibrated_models: list[str] = []

    # Include every model from fidelity table; also any SRDB model_id not in table
    all_model_ids = set(EQUIPMENT_FIDELITY) | set(tm_by_model)

    for model_id in sorted(all_model_ids):
        level, display, upgrade = EQUIPMENT_FIDELITY.get(
            model_id, ("?", model_id, "Not in EQUIPMENT_FIDELITY table")
        )
        params = tm_by_model.get(model_id, [])
        n_total = len(params)
        n_cal = sum(
            1 for p in params if srdb._parameters[p].calibration is not None
        )

        # Inconsistency: calibration curves exist but model is F1 or F2
        if n_cal > 0 and level in ("F1", "F2"):
            note = f"INCONSISTENCY: {n_cal} calibrated params but level={level}"
            print(f"  {'[ERR] ' + display:<{col}} {level:<6} {n_total:>9} {n_cal:>10}  {note}")
            errors_found = True
            continue

        # F2 model with no calibration → upgrade candidate
        if level == "F2" and n_total > 0 and n_cal == 0:
            f2_uncalibrated_total += n_total
            f2_uncalibrated_models.append(display)
            print(f"  {display:<{col}} {level:<6} {n_total:>9} {n_cal:>10}  → F3: {upgrade}")
        else:
            note = upgrade if level in ("F3", "F4") else ""
            print(f"  {display:<{col}} {level:<6} {n_total:>9} {n_cal:>10}  {note}")

    print("─" * 72)

    # ── Summary ────────────────────────────────────────────────────────────
    n_f2 = sum(1 for l, _, _ in EQUIPMENT_FIDELITY.values() if l == "F2")
    n_f3_plus = sum(1 for l, _, _ in EQUIPMENT_FIDELITY.values() if l in ("F3", "F4"))
    print(f"\n  F2 models: {n_f2}   F3+: {n_f3_plus}")

    if f2_uncalibrated_models:
        tm_total = sum(len(v) for v in tm_by_model.values())
        cal_total = sum(
            1 for defn in srdb._parameters.values()
            if defn.calibration is not None
            and defn.classification == Classification.TM
        )
        print(
            f"  F2→F3 upgrade candidates: {len(f2_uncalibrated_models)} model(s), "
            f"{cal_total}/{tm_total} TM params calibrated"
        )
        print(
            "  Add CalibrationCurve entries to srdb/baseline/ to enable "
            "raw→engineering conversion and promote models to F3."
        )

    if errors_found:
        print("\n  ✗ Fidelity inconsistencies found (see [ERR] rows above).")
    else:
        print("\n  ✓ No fidelity inconsistencies.")

    return not errors_found


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    req_file   = Path("REQUIREMENTS.md")
    matrix_file = Path("results/traceability.txt")
    srdb_dir   = Path("srdb/baseline")

    baselined = parse_baselined_requirements(req_file)
    covered   = parse_covered_requirements(matrix_file)

    uncovered     = baselined - covered - set(KNOWN_GAPS.keys())
    known_gap_ids = baselined & set(KNOWN_GAPS.keys())
    fully_covered = baselined & covered

    print(f"BASELINED requirements:  {len(baselined)}")
    print(f"Covered by tests:        {len(fully_covered)}")
    print(f"Known gaps (deferred):   {len(known_gap_ids)}")
    print(f"Uncovered (unexpected):  {len(uncovered)}")

    if known_gap_ids:
        print("\nKnown gaps:")
        for req_id in sorted(known_gap_ids):
            print(f"  {req_id}: {KNOWN_GAPS[req_id]}")

    fidelity_ok = fidelity_report(srdb_dir)

    if uncovered:
        print("\n⚠ Unexpected uncovered BASELINED requirements:")
        for req_id in sorted(uncovered):
            print(f"  {req_id}")
        raise SystemExit(1)

    if not fidelity_ok:
        raise SystemExit(1)

    print("\n✓ All BASELINED requirements covered or tracked as known gaps")


if __name__ == "__main__":
    main()
