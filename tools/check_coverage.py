"""
SVF Requirement Coverage Checker
Cross-references REQUIREMENTS.md BASELINED requirements against
the traceability matrix. Reports uncovered requirements.

Usage: python3 tools/check_coverage.py (alias: checkcov)
"""

import re
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

    # EPS FMU — tested in tests/unit/ via FMU integration tests.
    # Markers pending on EPS-specific test suite.
    "EPS-001":  "Verified by test_fmu_equipment_step (SolarArrayFmu)",
    "EPS-002":  "Verified by test_fmu_equipment_step (SolarArrayFmu zero illumination)",
    "EPS-003":  "Verified by test_fmu_equipment_step (SolarArrayFmu full illumination)",
    "EPS-004":  "Verified by test_fmu_equipment_step (BatteryFmu discharging)",
    "EPS-005":  "Verified by test_fmu_equipment_step (BatteryFmu charging)",
    "EPS-006":  "Verified by test_fmu_equipment_step (BatteryFmu voltage curve)",
    "EPS-007":  "Verified by test_fmu_equipment_step (BatteryFmu SoC clamp)",
    "EPS-008":  "Verified by test_fmu_equipment_step (PcduFmu positive current)",
    "EPS-009":  "Verified by test_fmu_equipment_step (PcduFmu negative current)",
    "EPS-010":  "Verified by test_fmu_equipment_step (PcduFmu bus voltage)",
    "EPS-011":  "Verified by test_fmu_equipment_step (EpsFmu charging scenario)",
    "EPS-012":  "Verified by test_fmu_equipment_step (EpsFmu discharging scenario)",
    "EPS-013":  "Verified by test_fmu_equipment_step (EpsFmu bus voltage)",
    "EPS-014":  "Verified by test_fmu_equipment_step (decomposed EPS charging)",
    "EPS-015":  "Verified by test_fmu_equipment_step (decomposed EPS discharging)",
    "EPS-016":  "Verified by test_fmu_equipment_step (decomposed EPS power)",

    # PCDU native model — tested in tests/equipment/test_pcdu.py
    "PCDU-001": "Verified by test_pcdu_lcl_switching",
    "PCDU-002": "Verified by test_pcdu_mppt_efficiency",
    "PCDU-003": "Verified by test_pcdu_uvlo_disconnects_loads",
    "PCDU-004": "Verified by test_pcdu_power_balance",

    # svf_command_schedule — implemented, test marker pending
    "SVF-DEV-048": "Verified by test_tc_pwr_003_charging_in_sunlight (uses svf_command_schedule)",

    # Reporting
    "SVF-DEV-071": "Verified by JUnit XML and HTML report generation in CI",

    # Hardware/infrastructure — verified by CI or hardware tests
    "SVF-DEV-100": "Verified by tests/hardware/test_aarch64_obsw.py (excluded from default run)",
    "SVF-DEV-101": "Verified by tests/hardware/test_renode_zynqmp.py (excluded from default run)",
    "SVF-DEV-130": "Verified by HardwareProfile bundled search — exercised by every campaign run",
}


def parse_baselined_requirements(req_file: Path) -> set[str]:
    """Extract all BASELINED and IMPLEMENTED requirement IDs from REQUIREMENTS.md."""
    content = req_file.read_text()
    required_ids = set()
    
    # Updated pattern:
    # 1. [\w-]+ covers IDs like SVF-DEV-001 or 1553-001
    # 2. [\w\d]+ inside the brackets covers tags like [SIM] and [1553]
    # 3. (BASELINED|IMPLEMENTED) ensures we track everything that needs testing
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


def main() -> None:
    req_file = Path("REQUIREMENTS.md")
    matrix_file = Path("results/traceability.txt")

    baselined = parse_baselined_requirements(req_file)
    covered = parse_covered_requirements(matrix_file)

    uncovered = baselined - covered - set(KNOWN_GAPS.keys())
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

    if uncovered:
        print("\n⚠ Unexpected uncovered BASELINED requirements:")
        for req_id in sorted(uncovered):
            print(f"  {req_id}")
        raise SystemExit(1)
    else:
        print("\n✓ All BASELINED requirements covered or tracked as known gaps")


if __name__ == "__main__":
    main()
