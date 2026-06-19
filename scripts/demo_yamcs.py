#!/usr/bin/env python3
"""
OpenSVF + YAMCS Demo  -  OBC Emulator mode
Connects obsw_sim (real C11 flight binary) to YAMCS ground station.

Usage:
    # Terminal 1  -  start YAMCS
    bash scripts/start-yamcs.sh

    # Terminal 2  -  run demo
    python3 scripts/demo_yamcs.py [--obsw-sim PATH]

Then open http://localhost:8090 in your browser.

Scenario: early orbit  -  spacecraft attitude sensors not yet calibrated.
B-dot detumbling is active; geomagnetic field varies with orbital motion.

Demo A  -  Are-You-Alive:
    Commanding → TC_17_1_AreYouAlive → Send
    Packets: TM(1,1) acceptance → TM(17,2) pong → TM(1,7) completion

Demo B  -  Real-time B-dot gain upload:
    Observe: TM(3,25) AOCS_HK reports bdot_gain=10000.0 every 5 s
             MTQ dipole (aocs.mtq.*) is non-zero  -  controller is active
    1. Commanding → TC_20_1_SetBdotGain → value: 75000.0 → Send
       Packets: TM(1,1) acceptance → TM(1,7) completion
       TM(3,25) AOCS_HK: bdot_gain jumps to 75000.0 within 5 s
       MTQ dipole: increases ~7.5× proportionally
    2. (optional readback) Commanding → TC_20_3_GetBdotGain → Send
       Packets: TM(1,1) → TM(20,2) ParamReport (s20_param_value=75000.0) → TM(1,7)
"""
from svf.stores.parameter_store import ParameterStore
from svf.stores.command_store import CommandStore
from svf.sim.software_tick import RealtimeTickSource
from svf.sim.simulation import SimulationMaster
from svf.models.ttc.ttc import TtcEquipment
from svf.models.dhs.obc_emulator import OBCEmulatorAdapter
from svf.models.environment.orbital_environment import OrbitalEnvironment
from svf.models.aocs.magnetometer import make_magnetometer
from svf.config.wiring import WiringMap, Connection
from svf.core.equipment import Equipment, PortDefinition, PortDirection
from svf.pus.tm import PusTmPacket, PusTmBuilder
from svf.ground.yamcs_bridge import YamcsBridge
from svf.ground.dds_sync import DdsSyncProtocol
from cyclonedds.domain import DomainParticipant
import argparse
import logging
import os
import struct
import sys
from pathlib import Path

# ISS TLE  -  epoch 2021-001, ISS orbit (51.6° inc, ~400 km)
# Provides a time-varying geomagnetic field as the spacecraft moves through orbit.
_TLE1 = "1 25544U 98067A   21001.00000000  .00001234  00000-0  29032-4 0  9999"
_TLE2 = "2 25544  51.6432 228.3417 0001397 349.5283 135.8144 15.49309475265695"
_TLE_EPOCH_JD = 2459215.5  # 2021-01-01 00:00 UTC

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)-30s %(message)s",
)
logger = logging.getLogger("demo_yamcs")


class ActuatorReporter(Equipment):
    """
    Synthesises a TM(250,1) packet each tick carrying the current MTQ dipole
    commands and forwards it to YAMCS via the bridge.  This makes the B-dot
    output visible in the YAMCS packet viewer and parameter strip charts without
    requiring any changes to the OBSW binary.
    """

    def __init__(
        self,
        bridge: YamcsBridge,
        sync_protocol: object,
        store: ParameterStore,
        command_store: CommandStore,
    ) -> None:
        super().__init__(  # type: ignore[arg-type]
            "actuator_reporter", sync_protocol, store, command_store
        )
        self._bridge = bridge
        self._builder = PusTmBuilder()
        self._seq = 0

    def _declare_ports(self) -> list[PortDefinition]:
        return [
            PortDefinition("aocs.mtq.dipole_x", PortDirection.IN),
            PortDefinition("aocs.mtq.dipole_y", PortDirection.IN),
            PortDefinition("aocs.mtq.dipole_z", PortDirection.IN),
        ]

    def initialise(self, start_time: float = 0.0) -> None:
        pass

    def teardown(self) -> None:
        pass

    def do_step(self, t: float, dt: float) -> None:
        x = self.read_port("aocs.mtq.dipole_x")
        y = self.read_port("aocs.mtq.dipole_y")
        z = self.read_port("aocs.mtq.dipole_z")
        app_data = struct.pack(">fff", x, y, z)
        pkt = PusTmPacket(
            apid=0,
            sequence_count=self._seq & 0x3FFF,
            service=250,
            subservice=1,
            timestamp=int(t),
            app_data=app_data,
        )
        self._seq += 1
        self._bridge.send_tm(self._builder.build(pkt))


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

    # Orbital environment  -  SGP4 propagation + dipole B-field (pure Python)
    orbital = OrbitalEnvironment(
        tle_line1=_TLE1,
        tle_line2=_TLE2,
        sync_protocol=sync,
        store=store,
        command_store=cmd_store,
        epoch_jd=_TLE_EPOCH_JD,
        equipment_id="orbital",
    )

    # Magnetometer  -  noise model; reads true B field from orbital environment
    mag = make_magnetometer(sync, store, cmd_store, equipment_id="mag", seed=42)
    cmd_store.inject("aocs.mag.power_enable", 1.0, source_id="demo_init")

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

    # Wire NED B-field (orbital) → magnetometer body-frame true input.
    # NED ≈ body is a valid approximation while attitude is unknown (early orbit).
    wiring = WiringMap([
        Connection("orbital", "orbital.mag_field_n", "mag", "aocs.mag.true_x",
                   description="NED north → mag body-x"),
        Connection("orbital", "orbital.mag_field_e", "mag", "aocs.mag.true_y",
                   description="NED east  → mag body-y"),
        Connection("orbital", "orbital.mag_field_d", "mag", "aocs.mag.true_z",
                   description="NED down  → mag body-z"),
    ])

    actuator_reporter = ActuatorReporter(bridge, sync, store, cmd_store)

    master = SimulationMaster(
        tick_source=RealtimeTickSource(),
        sync_protocol=sync,
        models=[orbital, mag, obc, ttc, actuator_reporter],
        dt=1.0,
        stop_time=args.duration,
        sync_timeout=10.0,
        command_store=cmd_store,
        param_store=store,
        wiring=wiring,
    )

    print("Simulation running (realtime, 1 tick/s).")
    print()
    print("─── Demo A: Are-You-Alive ────────────────────────────────────")
    print("  Commanding → TC_17_1_AreYouAlive → Send")
    print("  Expect: TM(1,1) acceptance  →  TM(17,2) pong  →  TM(1,7) completion")
    print()
    print("─── Demo B: Real-time B-dot gain upload ─────────────────────")
    print("  Scenario: early orbit, attitude sensors not calibrated.")
    print("  B-dot detumbling active  -  MTQ dipole tracks orbital dB/dt.")
    print()
    print("  Observe baseline in Telemetry → Parameters:")
    print("    bdot_gain = 10000.0  (TM 3,25 AOCS_HK, every 5 s)")
    print("    aocs.mtq.dipole_* ≠ 0  (B-dot active)")
    print()
    print("  Step 1 → TC_20_1_SetBdotGain → value: 75000.0 → Send")
    print("    TM(3,25) AOCS_HK: bdot_gain → 75000.0 (within 5 s)")
    print("    MTQ dipole: increases ~7.5× proportionally")
    print()
    print("  Step 2 (optional readback) → TC_20_3_GetBdotGain → Send")
    print("    TM(20,2) ParamReport: s20_param_value = 75000.0")
    print()
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
