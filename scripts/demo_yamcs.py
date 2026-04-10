#!/usr/bin/env python3
"""
OpenSVF + YAMCS Demo

Runs a 60-second SVF simulation with YAMCS connected.
Operator can send TC(17,1) from YAMCS UI and see TM(17,2).

Usage:
    # Terminal 1 — start YAMCS
    bash scripts/start-yamcs.sh

    # Terminal 2 — run demo
    python3 scripts/demo_yamcs.py

Then open http://localhost:8090 in your browser.
"""

import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(message)s",
)
logger = logging.getLogger("demo")

from cyclonedds.domain import DomainParticipant

from svf.simulation import SimulationMaster
from svf.software_tick import SoftwareTickSource
from svf.dds_sync import DdsSyncProtocol
from svf.parameter_store import ParameterStore
from svf.command_store import CommandStore
from svf.models.obc_stub import ObcStub, Rule
from svf.models.obc import ObcConfig
from svf.models.ttc import TtcEquipment
from svf.yamcs_bridge import YamcsBridge


def main() -> None:
    print("=" * 60)
    print("  OpenSVF + YAMCS Demo")
    print("  YAMCS UI: http://localhost:8090")
    print("  Instance: opensvf | Processor: realtime")
    print("=" * 60)

    # Start YAMCS bridge — SVF listens, YAMCS connects
    store = ParameterStore()
    bridge = YamcsBridge(store, tm_port=10015, tc_port=10025)

    print("\nWaiting for YAMCS to connect on ports 10015/10025...")
    print("(start YAMCS with: bash scripts/start-yamcs.sh)\n")
    bridge.start()
    print("YAMCS connected! Starting simulation...\n")

    # Build simulation
    participant = DomainParticipant()
    cmd_store = CommandStore()
    sync = DdsSyncProtocol(participant)

    obc = ObcStub(
        config=ObcConfig(),
        sync_protocol=sync,
        store=store,
        command_store=cmd_store,
        rules=[
            Rule(
                name="auto_nominal",
                watch="svf.sim_time",
                condition=lambda e: e is not None and e.value > 5.0,
                action=lambda cs, t: cs.inject(
                    "dhs.obc.mode_cmd", 1.0, t=t
                ),
                once=True,
            )
        ],
    )

    ttc = TtcEquipment(
        obc=obc,
        sync_protocol=sync,
        store=store,
        command_store=cmd_store,
        yamcs_bridge=bridge,
    )

    master = SimulationMaster(
        tick_source=SoftwareTickSource(),
        sync_protocol=sync,
        models=[obc, ttc],
        dt=1.0,
        stop_time=60.0,
        sync_timeout=5.0,
        command_store=cmd_store,
        param_store=store,
    )

    print("Simulation running for 60 seconds.")
    print("In YAMCS UI → Commanding → send TC_17_1_AreYouAlive")
    print("Watch TM parameters update in Telemetry display.\n")

    master.run()

    bridge.stop()
    print("\nDemo complete.")


if __name__ == "__main__":
    main()
