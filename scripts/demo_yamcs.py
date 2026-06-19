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

Scenario: early orbit B-dot detumbling convergence.
Spacecraft starts tumbling at 3 deg/s; B-dot controller converges it to
near-zero body rate over ~5-10 minutes (visible in YAMCS strip charts).

Demo A  -  Are-You-Alive:
    Commanding → TC_17_1_AreYouAlive → Send
    Packets: TM(1,1) acceptance → TM(17,2) pong → TM(1,7) completion

Demo B  -  Watch detumbling convergence (no commands needed):
    Telemetry → Parameters → omega_norm (TM 250,2 BodyState, every tick)
    omega_norm starts at ~0.065 rad/s (3.7 deg/s) and converges to < 0.005 rad/s.
    MTQ dipoles (TM 250,1 ActuatorStatus) track the B-dot and decrease as rate drops.

Demo C  -  Real-time gain tuning:
    Observe: TM(3,25) AOCS_HK reports bdot_gain every 5 s
    1. Commanding → TC_20_1_SetBdotGain → value: 150000.0 → Send
       Convergence accelerates (higher gain = stronger braking torque)
    2. (optional readback) Commanding → TC_20_3_GetBdotGain → Send
       Packets: TM(1,1) → TM(20,2) ParamReport (s20_param_value=150000.0) → TM(1,7)
"""
import argparse
import logging
import math
import os
import struct
import sys
from pathlib import Path

from cyclonedds.domain import DomainParticipant

from svf.config.wiring import Connection, WiringMap
from svf.core.abstractions import SyncProtocol
from svf.core.equipment import Equipment, PortDefinition, PortDirection
from svf.ground.dds_sync import DdsSyncProtocol
from svf.ground.yamcs_bridge import YamcsBridge
from svf.models.aocs.magnetometer import make_magnetometer
from svf.models.aocs.magnetorquer import make_magnetorquer
from svf.models.dhs.obc_emulator import OBCEmulatorAdapter
from svf.models.dynamics.rigid_body import make_rigid_body_dynamics
from svf.models.environment.orbital_environment import OrbitalEnvironment
from svf.models.ttc.ttc import TtcEquipment
from svf.pus.tm import PusTmBuilder, PusTmPacket
from svf.sim.simulation import SimulationMaster
from svf.sim.software_tick import RealtimeTickSource
from svf.stores.command_store import CommandStore
from svf.stores.parameter_store import ParameterStore

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
        sync_protocol: SyncProtocol,
        store: ParameterStore,
        command_store: CommandStore,
    ) -> None:
        super().__init__(
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


class BodyStateReporter(Equipment):
    """
    Synthesises a TM(250,2) packet each tick carrying the current body angular
    velocity (omega_x/y/z + omega_norm) from the rigid-body integrator and
    forwards it to YAMCS. Makes detumbling convergence directly visible as a
    real-time strip chart without any OBSW changes.
    """

    def __init__(
        self,
        bridge: YamcsBridge,
        sync_protocol: SyncProtocol,
        store: ParameterStore,
        command_store: CommandStore,
    ) -> None:
        super().__init__(
            "body_state_reporter", sync_protocol, store, command_store
        )
        self._bridge = bridge
        self._builder = PusTmBuilder()
        self._seq = 0

    def _declare_ports(self) -> list[PortDefinition]:
        return [
            PortDefinition("aocs.body.omega_x",    PortDirection.IN),
            PortDefinition("aocs.body.omega_y",    PortDirection.IN),
            PortDefinition("aocs.body.omega_z",    PortDirection.IN),
            PortDefinition("aocs.body.omega_norm", PortDirection.IN),
        ]

    def initialise(self, start_time: float = 0.0) -> None:
        pass

    def teardown(self) -> None:
        pass

    def do_step(self, t: float, dt: float) -> None:
        ox   = self.read_port("aocs.body.omega_x")
        oy   = self.read_port("aocs.body.omega_y")
        oz   = self.read_port("aocs.body.omega_z")
        norm = self.read_port("aocs.body.omega_norm")
        app_data = struct.pack(">ffff", ox, oy, oz, norm)
        pkt = PusTmPacket(
            apid=0,
            sequence_count=self._seq & 0x3FFF,
            service=250,
            subservice=2,
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

    # Magnetometer  -  noise model; reads true B field from rigid body (body frame)
    mag = make_magnetometer(sync, store, cmd_store, equipment_id="mag", seed=42)
    cmd_store.inject("aocs.mag.power_enable", 1.0, source_id="demo_init")

    # Magnetorquer  -  reads OBSW dipole commands, computes torque for rigid body
    mtq = make_magnetorquer(sync, store, cmd_store, equipment_id="mtq")
    cmd_store.inject("aocs.mtq.power_enable", 1.0, source_id="demo_init")

    # Rigid body  -  integrates attitude; closes the B-dot detumbling loop
    # Initial condition: 3 deg/s tumble on each axis
    rigid_body = make_rigid_body_dynamics(
        sync, store, cmd_store,
        equipment_id="rigid_body",
        omega0=(
            3.0 * math.pi / 180.0,
            2.0 * math.pi / 180.0,
            1.0 * math.pi / 180.0,
        ),
    )

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

    # Closed-loop detumbling wiring:
    #   orbital NED B → rigid_body (frame rotation)
    #   rigid_body body-frame B → magnetometer true input
    #   magnetometer output → MTQ B-field input (for torque calculation)
    #   MTQ torque → rigid_body dynamics input
    wiring = WiringMap([
        Connection("orbital",    "orbital.mag_field_n",      "rigid_body", "orbital.mag_field_n",
                   description="NED B north → rigid body"),
        Connection("orbital",    "orbital.mag_field_e",      "rigid_body", "orbital.mag_field_e",
                   description="NED B east → rigid body"),
        Connection("orbital",    "orbital.mag_field_d",      "rigid_body", "orbital.mag_field_d",
                   description="NED B down → rigid body"),
        Connection("rigid_body", "aocs.body.b_true_x",       "mag",        "aocs.mag.true_x",
                   description="Body-frame B → mag true X"),
        Connection("rigid_body", "aocs.body.b_true_y",       "mag",        "aocs.mag.true_y",
                   description="Body-frame B → mag true Y"),
        Connection("rigid_body", "aocs.body.b_true_z",       "mag",        "aocs.mag.true_z",
                   description="Body-frame B → mag true Z"),
        Connection("mag",        "aocs.mag.field_x",         "mtq",        "aocs.mtq.b_field_x",
                   description="MAG measured B → MTQ X"),
        Connection("mag",        "aocs.mag.field_y",         "mtq",        "aocs.mtq.b_field_y",
                   description="MAG measured B → MTQ Y"),
        Connection("mag",        "aocs.mag.field_z",         "mtq",        "aocs.mtq.b_field_z",
                   description="MAG measured B → MTQ Z"),
        Connection("mtq",        "aocs.mtq.torque_x",        "rigid_body", "aocs.mtq.torque_x",
                   description="MTQ torque X → rigid body"),
        Connection("mtq",        "aocs.mtq.torque_y",        "rigid_body", "aocs.mtq.torque_y",
                   description="MTQ torque Y → rigid body"),
        Connection("mtq",        "aocs.mtq.torque_z",        "rigid_body", "aocs.mtq.torque_z",
                   description="MTQ torque Z → rigid body"),
    ])

    actuator_reporter  = ActuatorReporter(bridge, sync, store, cmd_store)
    body_state_reporter = BodyStateReporter(bridge, sync, store, cmd_store)

    master = SimulationMaster(
        tick_source=RealtimeTickSource(),
        sync_protocol=sync,
        models=[orbital, rigid_body, mag, mtq, obc, ttc,
                actuator_reporter, body_state_reporter],
        dt=1.0,
        stop_time=args.duration,
        sync_timeout=10.0,
        command_store=cmd_store,
        param_store=store,
        wiring=wiring,
    )

    omega0_deg = math.degrees(math.sqrt(
        (3.0*math.pi/180.0)**2 + (2.0*math.pi/180.0)**2 + (1.0*math.pi/180.0)**2
    ))
    print("Simulation running (realtime, 1 tick/s).")
    print()
    print(f"  Initial body rate: {omega0_deg:.2f} deg/s")
    print("  Closed-loop B-dot detumbling active.")
    print()
    print("─── Demo A: Are-You-Alive ───────────────────────────────────────────")
    print("  Commanding → TC_17_1_AreYouAlive → Send")
    print("  Expect: TM(1,1) acceptance → TM(17,2) pong → TM(1,7) completion")
    print()
    print("─── Demo B: Watch detumbling convergence (no commands needed) ───────")
    print("  Telemetry → Parameters → omega_norm  (TM 250,2 BodyState, every tick)")
    print(f"  Starts at ~{omega0_deg:.3f} rad/s, converges to < 0.005 rad/s in ~5-10 min")
    print("  MTQ dipoles (TM 250,1) decrease as body rate drops")
    print()
    print("─── Demo C: Real-time gain tuning ───────────────────────────────────")
    print("  Commanding → TC_20_1_SetBdotGain → value: 150000.0 → Send")
    print("    Convergence accelerates (stronger braking torque)")
    print("  Commanding → TC_20_3_GetBdotGain → Send")
    print("    TM(20,2) ParamReport: s20_param_value = 150000.0")
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
