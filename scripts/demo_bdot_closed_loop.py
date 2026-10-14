"""
scripts/demo_bdot_closed_loop.py - full closed-loop b-dot detumbling demo
(headless MP4 output, no display required).

Real openobsw C11 b-dot flight software (obsw_sim), wired through
OBCEmulatorAdapter over the real wire protocol, driving magnetorquer
commands against the real opensvf-kde physics FMU (SGP4 orbit + a
tilted-dipole field rotated into the body frame by actual attitude).

This is the genuine article, not a stand-in: the same b-dot algorithm that
runs on STM32H750/MSP430/ZynqMP hardware, reacting to a real time-varying
magnetic field instead of a fixed placeholder vector.

The output file can be uploaded directly to LinkedIn as a video post.
Mirrors the render pattern used by openobsw's sim/demo.py.

Usage
-----
  source .venv/bin/activate
  python3 scripts/demo_bdot_closed_loop.py [--output demo_bdot.mp4]

Requires: bin/obsw_sim, models/SpacecraftDynamics.fmu (built from the
opensvf-kde WI-2 physics - see SCOPE_OF_CHANGE.md in that repo)
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO / "src"))

try:
    import matplotlib
    matplotlib.use('Agg')       # headless - no display needed
    import matplotlib.pyplot as plt
    import numpy as np
    import imageio
except ImportError as _e:
    print(f'ERROR: missing dependency - {_e}')
    print('  pip install matplotlib numpy "imageio[ffmpeg]"')
    sys.exit(1)

OBSW_SIM = REPO / "bin" / "obsw_sim"
KDE_FMU = REPO / "models" / "SpacecraftDynamics.fmu"

# GitHub-dark palette (matches openobsw's sim/demo.py and opensvf-kde's
# scripts/demo_orbit_field.py)
BG      = '#0d1117'
FG      = '#c9d1d9'
TITLE   = '#e6edf3'
BLUE    = '#58a6ff'
ORANGE  = '#f0883e'
RED     = '#f85149'
GREEN   = '#3fb950'
GRID    = '#21262d'
SPINE   = '#30363d'
MONO    = 'monospace'

CONVERGENCE_DEG_S = 2.0  # "detumbled" threshold for the [PASS] marker


# ── Simulation ──────────────────────────────────────────────────────────────

def _run_sim(stop_time: float, dt: float, initial_omega: list[float]):
    from cyclonedds.domain import DomainParticipant
    from svf.sim.simulation import SimulationMaster
    from svf.sim.software_tick import SoftwareTickSource
    from svf.ground.dds_sync import DdsSyncProtocol
    from svf.stores.parameter_store import ParameterStore
    from svf.stores.command_store import CommandStore
    from svf.config.wiring import WiringLoader
    from svf.models.dhs.obc_emulator import OBCEmulatorAdapter
    from svf.models.ttc.ttc import TtcEquipment
    from svf.models.dynamics.kde_equipment import make_kde_equipment
    from svf.models.aocs.magnetometer import make_magnetometer
    from svf.models.aocs.magnetorquer import make_magnetorquer
    from svf.models.aocs.gyroscope import make_gyroscope
    from svf.models.aocs.star_tracker import make_star_tracker

    participant = DomainParticipant()
    store = ParameterStore()
    cmd_store = CommandStore()
    sync = DdsSyncProtocol(participant)

    kde = make_kde_equipment(sync, store, cmd_store, initial_omega=initial_omega)
    mag = make_magnetometer(sync, store, cmd_store, seed=42)
    gyro = make_gyroscope(sync, store, cmd_store, seed=42)
    st = make_star_tracker(sync, store, cmd_store, seed=42)
    mtq = make_magnetorquer(sync, store, cmd_store)
    obc = OBCEmulatorAdapter(
        sim_path=OBSW_SIM, sync_protocol=sync, store=store,
        command_store=cmd_store, sync_timeout=3.0,
    )
    ttc = TtcEquipment(obc, sync, store, cmd_store)

    equipment = {"kde": kde, "mag": mag, "gyro": gyro, "mtq": mtq, "obc": obc}
    wiring = WiringLoader(equipment).load(
        REPO / "mission_mysat1" / "wiring" / "full_loop_wiring.yaml"
    )

    master = SimulationMaster(
        tick_source=SoftwareTickSource(),
        sync_protocol=sync,
        models=[kde, mag, gyro, st, ttc, obc, mtq],
        dt=dt,
        stop_time=stop_time,
        sync_timeout=5.0,
        command_store=cmd_store,
        param_store=store,
        wiring=wiring,
        seed=42,
    )

    for name in ("aocs.mag.power_enable", "aocs.gyro.power_enable",
                 "aocs.str1.power_enable", "aocs.mtq.power_enable"):
        cmd_store.inject(name, 1.0, source_id="demo")
    cmd_store.inject("aocs.str1.sun_angle", 90.0, source_id="demo")

    # Instrument: wrap ParameterStore.write and CommandStore.inject to build
    # a per-tick time history without needing a hook SimulationMaster
    # doesn't expose. True rate/field truth flows through ParameterStore
    # (written by kde/mag each tick); the real dipole command computed by
    # obsw_sim's b-dot algorithm flows through CommandStore (injected by
    # OBCEmulatorAdapter._parse_actuator each tick it receives an actuator
    # frame). Both carry a `t` argument; obsw_sim's own clock and SVF's
    # tick clock can drift by sub-dt amounts, so key samples by tick index
    # (round(t / dt)) rather than exact t.
    samples: dict[int, dict[str, float]] = {}
    param_tracked = {
        "aocs.truth.rate_x", "aocs.truth.rate_y", "aocs.truth.rate_z",
        "aocs.mag.true_x", "aocs.mag.true_y", "aocs.mag.true_z",
    }
    cmd_tracked = {"aocs.mtq.dipole_x", "aocs.mtq.dipole_y", "aocs.mtq.dipole_z"}

    original_write = store.write
    original_inject = cmd_store.inject

    def tracking_write(name, value, t, model_id):
        original_write(name, value, t, model_id)
        if name in param_tracked:
            samples.setdefault(round(t / dt), {})[name] = value

    def tracking_inject(name, value, t=0.0, source_id="test_procedure"):
        original_inject(name, value, t=t, source_id=source_id)
        if name in cmd_tracked:
            samples.setdefault(round(t / dt), {})[name] = value

    store.write = tracking_write  # type: ignore[method-assign]
    cmd_store.inject = tracking_inject  # type: ignore[method-assign]

    print(f"Running closed loop: stop_time={stop_time}s, dt={dt}s, "
          f"initial |omega|={math.sqrt(sum(w**2 for w in initial_omega)):.3f} rad/s")
    master.run()

    all_tracked = param_tracked | cmd_tracked
    ticks = sorted(samples.keys())
    t_hist, rate_hist, b_hist, dipole_hist = [], [], [], []
    for tick in ticks:
        s = samples[tick]
        if not all(k in s for k in all_tracked):
            continue  # partial tick (startup/shutdown edge, or no actuator
            # frame yet - obsw_sim hasn't sent a command this tick), skip
        t_hist.append(tick * dt)
        rate_hist.append([s["aocs.truth.rate_x"], s["aocs.truth.rate_y"], s["aocs.truth.rate_z"]])
        b_hist.append([s["aocs.mag.true_x"], s["aocs.mag.true_y"], s["aocs.mag.true_z"]])
        dipole_hist.append([s["aocs.mtq.dipole_x"], s["aocs.mtq.dipole_y"], s["aocs.mtq.dipole_z"]])

    print(f"Collected {len(t_hist)} full samples")
    return (np.array(t_hist), np.array(rate_hist),
            np.array(b_hist) * 1e6, np.array(dipole_hist))  # T -> uT


# ── Render ────────────────────────────────────────────────────────────────

def _render(args, t_hist, rate_hist, b_hist, dipole_hist):
    rate_deg_s = np.degrees(np.linalg.norm(rate_hist, axis=1))
    b_mag = np.linalg.norm(b_hist, axis=1)
    dipole_mag = np.linalg.norm(dipole_hist, axis=1)

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12.8, 7.2), dpi=100)
    fig.patch.set_facecolor(BG)

    # Left: angular rate convergence
    ax1.set_facecolor(BG)
    ax1.axhline(CONVERGENCE_DEG_S, color=RED, linestyle='--', linewidth=1.8,
                label=f'{CONVERGENCE_DEG_S}°/s detumbled threshold', zorder=2)
    ax1.set_xlim(0, t_hist[-1])
    ax1.set_ylim(0, rate_deg_s[0] * 1.12)
    ax1.set_xlabel('Simulation time  [s]', color=FG, fontsize=13)
    ax1.set_ylabel('|ω|  [deg/s]', color=FG, fontsize=13)
    ax1.set_title(
        'openobsw B-dot  -  Closed-Loop Detumbling\n'
        'Real C11 flight software · real orbit-varying field',
        color=TITLE, fontsize=13, pad=10,
    )
    ax1.tick_params(colors='#8b949e', labelsize=11)
    for sp in ax1.spines.values():
        sp.set_edgecolor(SPINE)
    ax1.grid(True, color=GRID, linewidth=0.9)
    rate_line, = ax1.plot([], [], color=BLUE, linewidth=2.4,
                           label='|ω| (true rate)', zorder=3)
    rate_readout = ax1.text(0.02, 0.94, '', transform=ax1.transAxes,
                             color=BLUE, fontsize=14, va='top', fontfamily=MONO)
    ax1.legend(loc='upper right', fontsize=10,
               facecolor='#161b22', edgecolor=SPINE, labelcolor=FG)

    # Right: field the controller sees + commanded dipole
    ax2.set_facecolor(BG)
    ax2b = ax2.twinx()
    ax2.set_xlim(0, t_hist[-1])
    ax2.set_ylim(0, np.max(b_mag) * 1.2)
    ax2b.set_ylim(0, max(np.max(dipole_mag), 1e-6) * 1.3)
    ax2.set_xlabel('Simulation time  [s]', color=FG, fontsize=13)
    ax2.set_ylabel('|B|, body frame  [µT]', color=ORANGE, fontsize=13)
    ax2b.set_ylabel('|commanded dipole|  [A·m²]', color=GREEN, fontsize=13)
    ax2.set_title(
        'What the controller reacts to\n'
        'measured field vs. commanded MTQ dipole moment',
        color=TITLE, fontsize=13, pad=10,
    )
    ax2.tick_params(colors='#8b949e', labelsize=11)
    ax2b.tick_params(colors='#8b949e', labelsize=11)
    for sp in ax2.spines.values():
        sp.set_edgecolor(SPINE)
    ax2.grid(True, color=GRID, linewidth=0.9)
    b_line, = ax2.plot([], [], color=ORANGE, linewidth=1.8, label='|B|', zorder=3)
    dipole_line, = ax2b.plot([], [], color=GREEN, linewidth=1.4, alpha=0.85,
                              label='|dipole|', zorder=3)
    ax2.legend(loc='upper right', fontsize=10,
               facecolor='#161b22', edgecolor=SPINE, labelcolor=FG)

    fig.tight_layout()

    n_frames = min(args.max_frames, len(t_hist))
    idx = np.linspace(0, len(t_hist) - 1, n_frames).astype(int)

    converged_frame = None
    below = np.where(rate_deg_s <= CONVERGENCE_DEG_S)[0]
    if len(below) > 0:
        converged_at = t_hist[below[0]]
        converged_frame = next((k for k, i in enumerate(idx) if t_hist[i] >= converged_at), None)

    print(f"\nRendering {n_frames} frames at {args.fps} fps -> {args.output}")
    pass_marker_added = False
    with imageio.get_writer(args.output, fps=args.fps,
                             codec='libx264', quality=8,
                             pixelformat='yuv420p') as writer:
        for k, i in enumerate(idx):
            rate_line.set_data(t_hist[:i + 1], rate_deg_s[:i + 1])
            rate_readout.set_text(f'|ω| = {rate_deg_s[i]:6.2f} deg/s')

            b_line.set_data(t_hist[:i + 1], b_mag[:i + 1])
            dipole_line.set_data(t_hist[:i + 1], dipole_mag[:i + 1])

            if converged_frame is not None and k >= converged_frame and not pass_marker_added:
                ax1.axvline(t_hist[i], color=GREEN, linestyle='--',
                            linewidth=1.8, alpha=0.9, zorder=2)
                ax1.text(t_hist[i] + t_hist[-1] * 0.015, rate_deg_s[0] * 0.85,
                          f'[DETUMBLED]  t = {t_hist[i]:.0f} s',
                          color=GREEN, fontsize=12, va='top', fontfamily=MONO)
                rate_readout.set_color(GREEN)
                pass_marker_added = True

            fig.canvas.draw()
            frame = np.asarray(fig.canvas.buffer_rgba())[:, :, :3]
            writer.append_data(frame)

            if (k + 1) % 50 == 0 or k == n_frames - 1:
                print(f'  {k + 1}/{n_frames} frames', end='\r')

    plt.close(fig)
    import os
    print(f"\nSaved -> {args.output}  "
          f"({n_frames / args.fps:.1f} s  ·  {os.path.getsize(args.output) // 1024} KB)")


# ── Entry point ───────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(
        description='Render a closed-loop b-dot detumbling demo to MP4 (no display required)',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument('--output', default='demo_bdot_closed_loop.mp4')
    p.add_argument('--stop-time', type=float, default=300.0, help='sim seconds')
    p.add_argument('--dt', type=float, default=0.1)
    p.add_argument('--tumble', type=float, nargs=3, default=[1.2, -0.9, 0.7],
                    metavar=('WX', 'WY', 'WZ'), help='initial angular rate, rad/s')
    p.add_argument('--max-frames', type=int, default=250)
    p.add_argument('--fps', type=int, default=25)
    p.add_argument('--debug', action='store_true',
                    help='log obsw_sim stderr and internal SVF debug output')
    args = p.parse_args()

    if args.debug:
        import logging
        logging.basicConfig(level=logging.DEBUG,
                             format='%(asctime)s %(name)s %(message)s')

    if not OBSW_SIM.exists():
        print(f'ERROR: obsw_sim not found at {OBSW_SIM}')
        sys.exit(1)
    if not KDE_FMU.exists():
        print(f'ERROR: SpacecraftDynamics.fmu not found at {KDE_FMU}')
        sys.exit(1)

    t_hist, rate_hist, b_hist, dipole_hist = _run_sim(
        args.stop_time, args.dt, list(args.tumble))
    _render(args, t_hist, rate_hist, b_hist, dipole_hist)


if __name__ == '__main__':
    main()
