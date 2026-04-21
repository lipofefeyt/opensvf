"""
SVF Command Line Interface

Usage:
    svf run spacecraft.yaml              # run simulation
    svf campaign campaign.yaml           # run test campaign
    svf campaign campaign.yaml --report  # run + generate HTML report
    svf profiles                         # list available hardware profiles
    svf check spacecraft.yaml            # validate config without running

Implements: GAP-014
"""
from __future__ import annotations

import argparse
import sys
import logging
from pathlib import Path


def cmd_run(args: argparse.Namespace) -> int:
    """Run a spacecraft simulation from a YAML config."""
    from svf.config.spacecraft import SpacecraftLoader, SpacecraftConfigError
    try:
        master = SpacecraftLoader.load(args.config)
        print(f"[svf] Running {args.config} ...")
        master.run()
        print("[svf] Simulation complete.")
        return 0
    except SpacecraftConfigError as e:
        print(f"[svf] Config error: {e}", file=sys.stderr)
        return 1
    except FileNotFoundError as e:
        print(f"[svf] Not found: {e}", file=sys.stderr)
        return 1


def cmd_campaign(args: argparse.Namespace) -> int:
    """Run a test campaign and optionally generate HTML report."""
    from svf.test.campaign_runner import CampaignRunner
    from svf.test.report import generate_html_report

    path = Path(args.config)
    if not path.exists():
        print(f"[svf] Campaign file not found: {path}", file=sys.stderr)
        return 1

    try:
        runner = CampaignRunner.from_yaml(path)
        report = runner.run()

        if args.report:
            out = Path(args.output) if args.output else \
                  Path("results") / f"{path.stem}_report.html"
            generate_html_report(report, out)
            print(f"[svf] Report: {out}")

        if args.json:
            import json
            json_out = Path(args.json)
            json_out.parent.mkdir(parents=True, exist_ok=True)
            json_out.write_text(json.dumps(report.to_dict(), indent=2))
            print(f"[svf] JSON: {json_out}")

        return 0 if report.n_fail == 0 and report.n_error == 0 else 1

    except FileNotFoundError as e:
        print(f"[svf] Not found: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"[svf] Error: {e}", file=sys.stderr)
        return 1


def cmd_profiles(args: argparse.Namespace) -> int:
    """List available hardware profiles."""
    from svf.config.hardware_profile import _BUNDLED_PROFILES_DIR

    profiles = sorted(_BUNDLED_PROFILES_DIR.glob("*.yaml"))
    if not profiles:
        print("[svf] No bundled profiles found.")
        return 1

    print(f"Bundled hardware profiles ({_BUNDLED_PROFILES_DIR}):\n")
    for p in profiles:
        import yaml
        with open(p) as f:
            data = yaml.safe_load(f)
        hw_type = data.get("type", "unknown")
        desc    = data.get("description", "")
        print(f"  {p.stem:<30} [{hw_type}]  {desc}")

    # Check obsw-srdb
    try:
        import importlib.util
        if importlib.util.find_spec("obsw_srdb") is not None:
            print("\nobsw-srdb package profiles also available.")
    except Exception:
        pass

    return 0


def cmd_check(args: argparse.Namespace) -> int:
    """Validate a spacecraft YAML config without running."""
    from svf.config.spacecraft import SpacecraftLoader, SpacecraftConfigError
    try:
        master = SpacecraftLoader.load(args.config)
        models = master._models
        print(f"[svf] Config OK: {len(models)} models")
        for m in models:
            eq_id = m.equipment_id if hasattr(m, "equipment_id") else str(m)
            print(f"  - {eq_id}")
        wiring = master._wiring
        if wiring is not None:
            print(f"  Wiring: {len(wiring.connections)} connections")
        return 0
    except SpacecraftConfigError as e:
        print(f"[svf] Config error: {e}", file=sys.stderr)
        return 1
    except FileNotFoundError as e:
        print(f"[svf] Not found: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"[svf] Error: {e}", file=sys.stderr)
        return 1


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="svf",
        description="OpenSVF — Spacecraft Software Validation Facility",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable debug logging"
    )

    sub = parser.add_subparsers(dest="command", metavar="COMMAND")
    sub.required = True

    # svf run
    p_run = sub.add_parser("run", help="Run a spacecraft simulation")
    p_run.add_argument("config", help="Path to spacecraft.yaml")
    p_run.set_defaults(func=cmd_run)

    # svf campaign
    p_camp = sub.add_parser("campaign", help="Run a test campaign")
    p_camp.add_argument("config", help="Path to campaign.yaml")
    p_camp.add_argument(
        "--report", action="store_true",
        help="Generate HTML report after campaign"
    )
    p_camp.add_argument(
        "--output", "-o", default=None,
        help="HTML report output path (default: results/<name>_report.html)"
    )
    p_camp.add_argument(
        "--json", default=None,
        help="Also save JSON results to this path"
    )
    p_camp.set_defaults(func=cmd_campaign)

    # svf profiles
    p_prof = sub.add_parser("profiles", help="List available hardware profiles")
    p_prof.set_defaults(func=cmd_profiles)

    # svf check
    p_check = sub.add_parser("check", help="Validate spacecraft config")
    p_check.add_argument("config", help="Path to spacecraft.yaml")
    p_check.set_defaults(func=cmd_check)

    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.WARNING)

    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
