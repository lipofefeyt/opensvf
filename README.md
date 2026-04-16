# OpenSVF

**Open-core spacecraft Software Validation Facility**

OpenSVF is a Python-based platform for validating spacecraft software and systems — from individual subsystem models to full closed-loop co-simulation with a C++ physics engine, a real OBSW binary running on x86_64, aarch64 (ZynqMP QEMU), or ZynqMP Renode emulation, and a YAMCS ground station.

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

testosvf                             # ~392 tests
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
| `obsw_zynqmp` | aarch64 bare-metal | Cadence UART → Renode socket | ✅ Validated |

```bash
# x86_64 (default)
pytest tests/hardware/ -v

# aarch64 QEMU (auto-detected)
OBSW_ARCH=aarch64 pytest tests/hardware/ -v

# Renode ZynqMP (start Renode first)
renode renode/zynqmp_obsw.resc &
sleep 5
pytest tests/hardware/test_renode_zynqmp.py -v
```

---

## OBC Emulator Adapter

SVF connects to OBSW via two transport modes:

```python
# Pipe mode (x86_64 or aarch64 QEMU)
obc = OBCEmulatorAdapter(
    sim_path="obsw_sim",
    sync_protocol=sync, store=store, command_store=cmd_store,
)

# Socket mode (Renode ZynqMP)
obc = OBCEmulatorAdapter(
    sim_path=None,
    socket_addr=("localhost", 3456),
    sync_protocol=sync, store=store, command_store=cmd_store,
)
```

Auto-detection: if `obsw_sim_aarch64` is passed, QEMU prefix is added automatically.

---

## Model Organisation

```
src/svf/models/
├── aocs/       reaction_wheel, magnetometer, magnetorquer, gyroscope,
│               star_tracker, css, bdot_controller, thruster, gps
├── dynamics/   kde_equipment + fmu/DynamicsFmu
├── eps/        pcdu + fmu/{EpsFmu, BatteryFmu, SolarArrayFmu, PcduFmu}
├── dhs/        obc, obc_stub, obc_emulator
├── ttc/        ttc, sbt
└── thermal/    thermal
```

---

## Tick Sources

| Source | Behaviour | Use Case |
|---|---|---|
| `SoftwareTickSource` | Fast as possible | CI, Monte Carlo |
| `RealtimeTickSource` | Wall-clock aligned | YAMCS demos, HIL |

Variable timestep: models can override `suggested_dt()` to request a smaller step size. `SimulationMaster` uses the minimum across all models.

---

## Hardware Profiles

```python
rw  = make_reaction_wheel(sync, store, hardware_profile="rw_sinclair_rw003")
thr = make_thruster(sync, store, hardware_profile="thr_moog_monarc_1")
gps = make_gps(sync, store, hardware_profile="gps_novatel_oem7")
```

10 profiles in `srdb/data/hardware/` across 6 equipment types.

---

## Monte Carlo

```bash
python3 scripts/mc_bdot_detumbling.py --runs 20

# Result: 100% convergence, final rate 0.0001 rad/s
# Initial rates: 0.12–4.63 rad/s, all converge in 60s
```

---

## Reference Equipment Library

| Equipment | Subsystem | Import Path |
|---|---|---|
| `OBCEmulatorAdapter` | DHS | `svf.models.dhs.obc_emulator` |
| `ObcEquipment` / `ObcStub` | DHS | `svf.models.dhs.obc` / `obc_stub` |
| `TtcEquipment` + `YamcsBridge` | TTC/GND | `svf.models.ttc.ttc` |
| `make_kde_equipment()` | Dynamics | `svf.models.dynamics.kde_equipment` |
| `make_magnetometer/orquer/gyroscope/css()` | AOCS | `svf.models.aocs.*` |
| `make_reaction_wheel/star_tracker/bdot_controller()` | AOCS | `svf.models.aocs.*` |
| `make_thruster()` | AOCS/Prop | `svf.models.aocs.thruster` |
| `make_gps()` | Navigation | `svf.models.aocs.gps` |
| `make_thermal()` | Thermal | `svf.models.thermal.thermal` |
| `make_pcdu()` / `EpsFmu` | EPS | `svf.models.eps.*` |
| `make_sbt()` | TTC | `svf.models.ttc.sbt` |

---

## SRDB

```bash
obsw-srdb-export --data-dir srdb/data --output-dir srdb/export
obsw-srdb-codegen --data-dir srdb/data --output include/obsw/srdb_generated.h
```

Hardware profiles in `srdb/data/hardware/`. SRDB version handshake validated at startup.

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
| M14 — Real-Time & HIL + variable timestep + Renode socket | ✅ Done |
| M15 — Extended Bus Protocols (SpW, CAN) | 📋 Planned |
| M16 — SRDB Maturity | ✅ Done |
| M17 — Equipment Configurability | ✅ Done |
| M18 — Architecture Refactor | ✅ Done |

---

## License

Apache 2.0

---

*Built by lipofefeyt · [opensvf-kde](https://github.com/lipofefeyt/opensvf-kde) · [openobsw](https://github.com/lipofefeyt/openobsw)*