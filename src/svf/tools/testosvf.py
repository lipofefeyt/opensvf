"""Entry point for testosvf — runs the full OpenSVF test suite."""
import subprocess
import sys


def main() -> None:
    sys.exit(subprocess.run(
        ["pytest", "tests/", "-v", *sys.argv[1:]]
    ).returncode)
