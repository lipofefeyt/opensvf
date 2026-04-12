"""
Monte Carlo: B-dot Detumbling Convergence Study

Runs b-dot detumbling N times with different noise seeds.
Reports: convergence time, final angular rate, detumbling success rate.

This answers: "What is the statistical performance of the real C11
b-dot algorithm against KDE physics, across N noise realisations?"

Usage:
    python3 scripts/mc_bdot_detumbling.py [--runs N] [--workers W]
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

REPO = Path(__file__).parent.parent
OBSW_SIM = REPO / "obsw_sim"
KDE_FMU  = REPO / "models/fmu/SpacecraftDynamics.fmu"


def run_bdot(seed: int) -> dict:
    """
    Single b-dot detumbling run.
    Returns metrics dict for Monte Carlo collection.
    """
    from cyclonedds.domain import DomainParticipant
    from svf.simulation import SimulationMaster
    from svf.software_tick import SoftwareTickSource
    from svf.dds_sync import DdsSyncProtocol
    from svf.parameter_store import ParameterStore
    from svf.command_store import CommandStore
    from svf.wiring import WiringLoader
    from svf.models.obc_emulator import OBCEmulatorAdapter
    from svf.models.ttc import TtcEquipment
    from svf.models.kde_equipment import make_kde_equipment
    from svf.models.magnetometer import make_magnetometer
    from svf.models.magnetorquer import make_magnetorquer
    from svf.models.gyroscope import make_gyroscope
    from svf.models.star_tracker import make_star_tracker

    participant = DomainParticipant()
    store       = ParameterStore()
    cmd_store   = CommandStore()
    sync        = DdsSyncProtocol(participant)

    # Vary initial tumble rate based on seed (0.1 to 2.0 rad/s)
    import random
    rng_ic = random.Random(seed * 1000)  # separate RNG for initial conditions
    omega_scale = rng_ic.uniform(0.1, 2.0)
    initial_omega = [
        rng_ic.gauss(0.0, omega_scale),
        rng_ic.gauss(0.0, omega_scale),
        rng_ic.gauss(0.0, omega_scale),
    ]
    initial_rate = (sum(w**2 for w in initial_omega) ** 0.5)
    kde  = make_kde_equipment(sync, store, cmd_store,
                              initial_omega=initial_omega)
    mag  = make_magnetometer(sync, store, cmd_store, seed=seed)
    gyro = make_gyroscope(sync, store, cmd_store, seed=seed)
    st   = make_star_tracker(sync, store, cmd_store, seed=seed)
    mtq  = make_magnetorquer(sync, store, cmd_store)
    obc  = OBCEmulatorAdapter(
        sim_path=OBSW_SIM,
        sync_protocol=sync,
        store=store,
        command_store=cmd_store,
        sync_timeout=3.0,
    )
    ttc  = TtcEquipment(obc, sync, store, cmd_store)

    equipment = {"kde": kde, "mag": mag, "gyro": gyro, "mtq": mtq, "obc": obc}
    wiring = WiringLoader(equipment).load(
        REPO / "srdb/wiring/full_loop_wiring.yaml"
    )

    master = SimulationMaster(
        tick_source=SoftwareTickSource(),
        sync_protocol=sync,
        models=[kde, mag, gyro, st, ttc, obc, mtq],
        dt=0.1,
        stop_time=60.0,
        sync_timeout=5.0,
        command_store=cmd_store,
        param_store=store,
        wiring=wiring,
        seed=seed,
    )

    for name in [
        "aocs.mag.power_enable",
        "aocs.gyro.power_enable",
        "aocs.str1.power_enable",
        "aocs.mtq.power_enable",
    ]:
        cmd_store.inject(name, 1.0, source_id="mc")
    cmd_store.inject("aocs.str1.sun_angle", 90.0, source_id="mc")

    master.run()

    rate_x = store.read("aocs.truth.rate_x")
    rate_y = store.read("aocs.truth.rate_y")
    rate_z = store.read("aocs.truth.rate_z")

    if rate_x is None or rate_y is None or rate_z is None:
        raise RuntimeError("No angular rate data in store")

    final_rate = math.sqrt(
        rate_x.value**2 + rate_y.value**2 + rate_z.value**2
    )

    return {
        "initial_rate_rad_s": initial_rate,
        "final_rate_rad_s":   final_rate,
        "converged":          1.0 if final_rate < 1.0 else 0.0,
        "rate_reduction":     initial_rate - final_rate,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Monte Carlo: B-dot detumbling convergence study"
    )
    parser.add_argument("--runs",    type=int, default=20,
                        help="Number of Monte Carlo runs (default: 20)")
    parser.add_argument("--workers", type=int, default=1,
                        help="Parallel workers (default: 1)")
    parser.add_argument("--seed",    type=int, default=0,
                        help="Base seed (default: 0)")
    parser.add_argument("--output",  type=str,
                        default="results/mc_bdot/report.txt",
                        help="Output report path")
    args = parser.parse_args()

    if not OBSW_SIM.exists():
        print(f"ERROR: obsw_sim not found at {OBSW_SIM}")
        sys.exit(1)
    if not KDE_FMU.exists():
        print(f"ERROR: SpacecraftDynamics.fmu not found at {KDE_FMU}")
        sys.exit(1)

    from svf.monte_carlo import MonteCarloRunner

    print(f"B-dot Monte Carlo: {args.runs} runs, seed={args.seed}")
    print(f"Convergence criterion: final |ω| < 1.0 rad/s after 60s")
    print()

    runner = MonteCarloRunner(
        run_fn=run_bdot,
        n_runs=args.runs,
        base_seed=args.seed,
        n_workers=args.workers,
        pass_thresholds={
            "final_rate_rad_s": (1.0, True),  # pass if < 1.0 rad/s
        },
    )

    runner.run(output_path=Path(args.output))


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)s %(message)s")
    main()
