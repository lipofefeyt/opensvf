#!/usr/bin/env python3
"""
OpenSVF + YAMCS Demo — OBC Emulator mode
Connects obsw_sim (real C11 flight binary) to YAMCS ground station.
Operator can send TC(17,1) from YAMCS UI and see TM(17,2) in packet viewer.

Usage:
    # Terminal 1 — start YAMCS
    bash scripts/start-yamcs.sh

    # Terminal 2 — run demo
    python3 scripts/demo_yamcs.py [--obsw-sim PATH]

Then open http://localhost:8090 in your browser.
Commanding → /opensvf/TC_17_1_Ping → Send
Watch Telemetry → Packets for TM(17,2) response.
"""
from svf.stores.parameter_store import ParameterStore
from svf.stores.command_store import CommandStore
from svf.sim.software_tick import RealtimeTickSource
from svf.sim.simulation import SimulationMaster
from svf.models.ttc.ttc import TtcEquipment
from svf.models.dhs.obc_emulator import OBCEmulatorAdapter
from svf.ground.yamcs_bridge import YamcsBridge
from svf.ground.dds_sync import DdsSyncProtocol
from cyclonedds.domain import DomainParticipant
import argparse
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)-30s %(message)s",
)
logger = logging.getLogger("demo_yamcs")


def find_obsw_sim() -> Path:
    """Search for obsw_sim binary in likely locations."""
    candidates = [
        Path(os.environ.get("OBSW_SIM", "")),
        Path("/workspace/openobsw/build/sim/obsw_sim"),
        Path("../openobsw/build/sim/obsw_sim"),
        Path("bin/obsw_sim"),
    ]
    for p in candidates:
        if p.exists():
            return p
    raise FileNotFoundError(
        "obsw_sim not found. Set OBSW_SIM env var or pass --obsw-sim. "
        "Build openobsw with: host-build"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="OpenSVF + YAMCS demo")
    parser.add_argument(
        "--obsw-sim",
        type=Path,
        default=None,
        help="Path to obsw_sim binary (default: auto-detect)",
    )
    parser.add_argument(
        "--tm-port", type=int, default=10015,
        help="UDP port YAMCS listens for TM (default: 10015)",
    )
    parser.add_argument(
        "--tc-port", type=int, default=10025,
        help="UDP port SVF listens for TC from YAMCS (default: 10025)",
    )
    parser.add_argument(
        "--duration", type=float, default=3600.0,
        help="Simulation duration in seconds (default: 3600, Ctrl+C to stop)",
    )
    args = parser.parse_args()

    obsw_sim = args.obsw_sim or find_obsw_sim()
    logger.info(f"obsw_sim: {obsw_sim}")

    print("=" * 60)
    print("  OpenSVF + YAMCS Demo")
    print(f"  obsw_sim: {obsw_sim}")
    print("  YAMCS UI: http://localhost:8090")
    print("  Instance: opensvf | Processor: realtime")
    print("=" * 60)

    # ── YAMCS bridge ──────────────────────────────────────────────────
    store = ParameterStore()
    bridge = YamcsBridge(store, tm_port=args.tm_port, tc_port=args.tc_port)

    print(f"\nWaiting for YAMCS on ports {args.tm_port}/{args.tc_port}...")
    print("(start YAMCS with: bash scripts/start-yamcs.sh)\n")
    bridge.start()
    print("YAMCS connected!\n")

    # ── Simulation ────────────────────────────────────────────────────
    participant = DomainParticipant()
    cmd_store = CommandStore()
    sync = DdsSyncProtocol(participant)

    obc = OBCEmulatorAdapter(
        sim_path=obsw_sim,
        sync_protocol=sync,
        store=store,
        command_store=cmd_store,
    )
    obc._yamcs_bridge = bridge

    ttc = TtcEquipment(
        obc=obc,
        sync_protocol=sync,
        store=store,
        command_store=cmd_store,
        yamcs_bridge=bridge,
    )

    master = SimulationMaster(
        tick_source=RealtimeTickSource(),
        sync_protocol=sync,
        models=[obc, ttc],
        dt=1.0,
        stop_time=args.duration,
        sync_timeout=10.0,
        command_store=cmd_store,
        param_store=store,
    )

    print("Simulation running (realtime, 1 tick/s).")
    print("In YAMCS UI → Commanding → /opensvf/TC_17_1_Ping → Send")
    print("Watch Telemetry → Packets for TM(1,1) + TM(17,2) + TM(1,7).")
    print("Ctrl+C to stop.\n")

    try:
        master.run()
    except KeyboardInterrupt:
        print("\nStopped by user.")
    finally:
        bridge.stop()
        try:
            participant._delete()
        except Exception:
            pass

    print("\nDemo complete.")


if __name__ == "__main__":
    main()
