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
KNOWN_GAPS: dict[str, str] = {
    "SVF-DEV-048": "svf_command_schedule not yet implemented — M4.5 close-out",
}


def parse_baselined_requirements(req_file: Path) -> set[str]:
    """Extract all BASELINED requirement IDs from REQUIREMENTS.md."""
    content = req_file.read_text()
    baselined = set()
    pattern = re.compile(
        r'\*\*([\w-]+)\*\*\s+`\[[A-Z]+\]`\s+`BASELINED`'
    )
    for match in pattern.finditer(content):
        baselined.add(match.group(1))
    return baselined


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
