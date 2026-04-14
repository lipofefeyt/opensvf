# OpenSVF

**Open-core spacecraft Software Validation Facility**

OpenSVF is a Python-based platform for validating spacecraft software and systems — from individual subsystem models to full closed-loop co-simulation with a C++ physics engine, a real OBSW binary running on x86_64 or aarch64 (ZynqMP), and a YAMCS ground station.

---

## Design Philosophy

OpenSVF is a **flight software validation platform** — not an AOCS design tool and not a Simulink replacement.

- `opensvf-kde` is the **spacecraft plant** (physics). No control algorithm.
- `openobsw` contains the **flight algorithms** (b-dot, ADCS PD, FDIR). Under test.
- Python reference controllers are **validation oracles** — not flight code.
- Monte Carlo runs against fixed C code — tests the actual flight software.

See [`docs/design-philosophy.md`](docs/design-philosophy.md).

---

## Quick Start

```bash
git clone https://github.com/lipofefeyt/opensvf
cd opensvf
source scripts/setup-workspace.sh   # installs everything

testosvf                             # ~375 tests
svf-campaign campaigns/realtime_detumbling.yaml
bash scripts/demo.sh                 # SVF + YAMCS

docker build -t opensvf .
docker run --rm opensvf testosvf
```

---

## The Closed Loop

```
opensvf-kde (C++ / Eigen3)          openobsw (C11)
  6-DOF physics engine                 Real OBSW binary
  Euler's equations                    FSM: SAFE → b-dot
  Quaternion kinematics                FSM: NOMINAL → ADCS PD
  Earth B-field model                  PUS S1/3/5/8/17/20
         │                             FDIR state machine
         │  true ω, B  via FMI 2.0           │
         ▼                                    │ 0x02 sensor frames
              opensvf (Python)         ◄──────┘
              SVF tick loop                    │ 0x03 actuator frames
              Sensor + actuator models ────────►
                    │
                    │  PUS TM/TC via TCP
                    ▼
               YAMCS 5.12.6
```

---

## Target Architectures

| Binary | Architecture | Transport | Status |
|---|---|---|---|
| `obsw_sim` | x86_64 | stdin/stdout pipe | ✅ Production |
| `obsw_sim_aarch64` | aarch64 (ZynqMP PS) | stdin/stdout pipe via QEMU | ✅ Validated |
| `obsw_zynqmp` | aarch64 (ZynqMP PS) | Cadence UART → Renode socket | 📋 Planned (v0.7) |

```bash
# Run against x86_64 binary (default)
pytest tests/hardware/ -v

# Run against aarch64 binary (QEMU auto-detected)
OBSW_ARCH=aarch64 pytest tests/hardware/ -v
```

---

## Tick Sources

| Source | Behaviour | Use Case |
|---|---|---|
| `SoftwareTickSource` | Fast as possible | CI, Monte Carlo |
| `RealtimeTickSource` | Wall-clock aligned | YAMCS demos, HIL |

---

## Hardware Profiles

```python
rw  = make_reaction_wheel(sync, store, hardware_profile="rw_sinclair_rw003")
thr = make_thruster(sync, store, hardware_profile="thr_moog_monarc_1")
gps = make_gps(sync, store, hardware_profile="gps_novatel_oem7")
```

Profiles in `srdb/data/hardware/` — 10 profiles across 6 equipment types.

---

## Monte Carlo

```bash
python3 scripts/mc_bdot_detumbling.py --runs 20

# Result: 100% convergence, final rate 0.0001 rad/s
# Initial rates: 0.12–4.63 rad/s, all converge in 60s
```

```python
# Custom Monte Carlo
from svf.monte_carlo import MonteCarloRunner
runner = MonteCarloRunner(run_fn, n_runs=100, n_workers=4)
summary = runner.run(output_path=Path("results/mc/report.txt"))
```

---

## Reference Equipment Library

| Equipment | Subsystem | Milestone |
|---|---|---|
| `ObcEquipment` / `ObcStub` / `OBCEmulatorAdapter` | DHS | M7–M11 |
| `TtcEquipment` + `YamcsBridge` | TTC/GND | M7/M12 |
| `make_kde_equipment()` | Dynamics | M11.5 |
| `make_magnetometer/orquer/gyroscope/css()` | AOCS | M11.5 |
| `make_reaction_wheel/star_tracker/bdot_controller()` | AOCS | M6–M11.5 |
| `make_thruster()` | Propulsion | M17 |
| `make_gps()` | Navigation | M17 |
| `make_thermal()` | Thermal | M17 |
| `make_sbt/pcdu()` / `EpsFmu` | TTC/EPS | M8/M4 |

---

## Campaigns

| Campaign | Scenario | Level |
|---|---|---|
| `eps_validation.yaml` | EPS power system | 1 |
| `mil1553_validation.yaml` | 1553 bus + FDIR | 2 |
| `pus_validation.yaml` | PUS commanding | 3 |
| `safe_mode_recovery.yaml` | Closed-loop FDIR | 3/4 |
| `fdir_chain.yaml` | FDIR chain | 3/4 |
| `realtime_detumbling.yaml` | Real-time b-dot + YAMCS | 4 |

---

## Related Projects

| Project | Role |
|---|---|
| [opensvf-kde](https://github.com/lipofefeyt/opensvf-kde) | C++ 6-DOF physics (FMI 2.0) |
| [openobsw](https://github.com/lipofefeyt/openobsw) | C11 OBSW: PUS, b-dot, ADCS, FDIR |

---

## Roadmap

| Milestone | Status |
|---|---|
| M1–M12 — Core platform through ground segment | ✅ Done |
| M13 — SIL Attitude Loop Closure | ✅ Done |
| M14 — Real-Time & HIL | 🔄 In progress |
| M15 — Extended Bus Protocols (SpW, CAN) | 📋 Planned |
| M16 — SRDB Maturity | ✅ Done |
| M17 — Equipment Configurability | ✅ Done |
| M18 — Architecture Refactor | 📋 Planned |

### M14 Open
- #125 Socket adapter for OBCEmulatorAdapter (Renode integration)
- #115 Renode MSP430 (blocked — no MSP430 in Renode mainline)

---

## License

Apache 2.0

---

*Built by lipofefeyt · [opensvf-kde](https://github.com/lipofefeyt/opensvf-kde) · [openobsw](https://github.com/lipofefeyt/openobsw)*