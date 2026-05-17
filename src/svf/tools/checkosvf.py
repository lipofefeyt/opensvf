"""Entry point for checkosvf — runs mypy strict type check over src/."""
import subprocess
import sys


def main() -> None:
    sys.exit(subprocess.run(
        ["mypy", "src/", *sys.argv[1:]]
    ).returncode)
