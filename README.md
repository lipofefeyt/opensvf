# OpenSVF

**Open-core spacecraft Software Validation Facility**

OpenSVF is a Python-based platform for validating spacecraft software and systems — from individual subsystem models to full closed-loop co-simulation with a C++ physics engine, a real OBSW binary, and a YAMCS ground station.

---

## Design Philosophy

OpenSVF is a **flight software validation platform** — not an AOCS design tool and not a Simulink replacement.

It answers a specific question: *does my flight C code behave correctly against real physics and a real ground station?*

- `opensvf-kde` is the **spacecraft plant** (physics). It contains no control algorithm.
- `openobsw` contains the **flight algorithms** (b-dot, ADCS PD, FDIR). These are what's under test.
- Python reference controllers (e.g. `make_bdot_controller()`) are **validation oracles** — not flight code.
- Monte Carlo in OpenSVF varies seeds and initial conditions against fixed C code — testing the actual flight software, not a design model.

See [`docs/design-philosophy.md`](docs/design-philosophy.md) for the full discussion.

---

## Quick Start

```bash
# Clone and set up
git clone https://github.com/lipofefeyt/opensvf
cd opensvf
source scripts/setup-workspace.sh

# Run all tests
testosvf

# Run a campaign
svf-campaign campaigns/realtime_detumbling.yaml

# Full demo: SVF + YAMCS ground station
bash scripts/demo.sh

# Docker (fully self-contained)
docker build -t opensvf .
docker run --rm opensvf testosvf
```

---

## The Closed Loop

```
opensvf-kde (C++ / Eigen3)          openobsw (C11 / bare metal)
  6-DOF physics engine                 Real OBSW binary
  Euler's equations                    FSM: SAFE → b-dot
  Quaternion kinematics                FSM: NOMINAL → ADCS PD
  Earth B-field model                  PUS S1/3/5/8/17/20
         │                             FDIR state machine
         │  true ω, B  via FMI 2.0           │
         ▼                                    │ 0x02 sensor frames
              opensvf (Python)         ◄──────┘
              SVF tick loop                    │ 0x03 actuator frames
              Sensor + actuator models         │ dipoles / RW torques
              Thruster, GPS, thermal   ────────►
                    │
                    │  PUS TM/TC via TCP
                    ▼
               YAMCS 5.12.6
               Ground station UI
```

**Mode-aware AOCS in real C:**
- SAFE + MAG valid → b-dot → MTQ dipoles → torque = m×B → KDE
- NOMINAL + ST + GYRO → ADCS PD → RW torques → KDE

---

## Wire Protocol (obsw_sim ↔ SVF)

```
SVF → obsw_sim stdin:
  [0x01][uint16 BE len][TC frame]          TC uplink
  [0x02][uint16 BE len][sensor_frame_t]    MAG/GYRO/ST injection

obsw_sim → SVF stdout:
  [0x03][uint16 BE len][actuator_frame_t]  Dipoles / RW torques
  [0x04][uint16 BE len][TM packet]         PUS TM downlink
  [0xFF]                                   End of tick
```

---

## Tick Sources

| Tick Source | Behaviour | Use Case |
|---|---|---|
| `SoftwareTickSource` | Fast as possible | CI, batch validation, Monte Carlo |
| `RealtimeTickSource` | Wall-clock aligned | YAMCS operator demos, HIL |

```python
master = SimulationMaster(tick_source=RealtimeTickSource(), ...)
```

---

## Hardware Profiles

Equipment models are parameterised from SRDB hardware YAML profiles:

```python
# Generic default
rw = make_reaction_wheel(sync, store)

# Specific hardware
rw = make_reaction_wheel(sync, store, hardware_profile="rw_sinclair_rw003")
thr = make_thruster(sync, store, hardware_profile="thr_moog_monarc_1")
gps = make_gps(sync, store, hardware_profile="gps_novatel_oem7")
```

Available profiles in `srdb/data/hardware/`:

| Profile | Type | Key Parameters |
|---|---|---|
| `rw_default` | reaction_wheel | 6000 rpm, 0.2 Nm |
| `rw_sinclair_rw003` | reaction_wheel | 5000 rpm, 30 mNm |
| `mtq_default` | magnetorquer | 10 Am², 5 Ω |
| `mag_default` | magnetometer | 1×10⁻⁷ T noise |
| `gyro_default` | gyroscope | ARW 1×10⁻⁴ rad/s/√Hz |
| `thr_default` | thruster | 1 N, Isp=70s (cold gas) |
| `thr_moog_monarc_1` | thruster | 1 N, Isp=220s (hydrazine) |
| `gps_default` | gps | 5 m position noise |
| `gps_novatel_oem7` | gps | 1.5 m position noise |
| `thermal_default` | thermal_node | 3-node (panels + internal) |

---

## SRDB Version Handshake

At startup, `OBCEmulatorAdapter` reads the SRDB version from `obsw_sim` stderr and compares against the installed `obsw-srdb` package:

```
[obsw] [OBSW] SRDB version: 0.1.0
[obc-emu] SRDB version handshake OK: 0.1.0
```

Mismatch triggers a WARNING — parameter names may be inconsistent between OBSW and SVF.

---

## Ground Segment (YAMCS)

```bash
# Terminal 1
yamcs-start && yamcs-log-follow

# Terminal 2 — real-time detumbling observable in YAMCS TM
svf-campaign campaigns/realtime_detumbling.yaml
```

Open `http://localhost:8090` — live TM parameters, TC commanding from YAMCS UI. XTCE MDB (78 parameters, 2 commands) auto-generated from SRDB on every start.

---

## Campaigns

```bash
svf-campaign campaigns/eps_validation.yaml
svf-campaign-all
```

| Campaign | Scenario | Level |
|---|---|---|
| `eps_validation.yaml` | EPS power system | 1 |
| `mil1553_validation.yaml` | 1553 bus + FDIR | 2 |
| `pus_validation.yaml` | PUS commanding chain | 3 |
| `platform_validation.yaml` | Full platform | 3 |
| `safe_mode_recovery.yaml` | Closed-loop FDIR | 3/4 |
| `nominal_ops.yaml` | Nominal operations | 3/4 |
| `contact_pass.yaml` | Ground contact pass | 3/4 |
| `fdir_chain.yaml` | FDIR chain | 3/4 |
| `realtime_detumbling.yaml` | Real-time b-dot + YAMCS | 4 |

---

## Reference Equipment Library

| Equipment | Factory | Subsystem | Key Physics |
|---|---|---|---|
| `ObcEquipment` | class | DHS | Mode FSM, OBT, watchdog, PUS routing |
| `ObcStub` | class | DHS | Rule engine, closed-loop FDIR |
| `OBCEmulatorAdapter` | class | DHS | Real OBSW via typed pipe protocol |
| `TtcEquipment` | class | TTC | TC/TM pipe, optional YAMCS bridge |
| `YamcsBridge` | class | GND | TCP TM/TC bridge to YAMCS |
| `make_kde_equipment()` | factory | Dynamics | 6-DOF physics, B-field model |
| `make_reaction_wheel()` | factory | AOCS | Torque, friction, temperature |
| `make_star_tracker()` | factory | AOCS | Quaternion, noise, sun blinding |
| `make_magnetometer()` | factory | AOCS | B-field measurement + noise |
| `make_magnetorquer()` | factory | AOCS | Torque = m × B |
| `make_gyroscope()` | factory | AOCS | Rate measurement + ARW noise |
| `make_css()` | factory | AOCS | Sun vector + eclipse detection |
| `make_bdot_controller()` | factory | AOCS | m = −k·Ḃ reference oracle |
| `make_thruster()` | factory | AOCS | Thrust, propellant, temperature |
| `make_gps()` | factory | NAV | Position/velocity + noise, eclipse |
| `make_thermal()` | factory | THM | N-node radiation/conduction model |
| `make_sbt()` | factory | TTC | Carrier lock, mode FSM |
| `make_pcdu()` | factory | EPS | LCL switching, MPPT, UVLO |
| `EpsFmu` | FmuEquipment | EPS | Solar array, Li-Ion battery |

---

## Deterministic Replay

```
SVF seed: 809481067  (replay with seed=809481067)
```

```python
master = SimulationMaster(..., seed=809481067)
master.run()  # identical noise, identical results
```

---

## Project Structure

```
src/svf/
├── models/             Equipment models (flat — M18 refactor planned)
├── software_tick.py    SoftwareTickSource + RealtimeTickSource
├── yamcs_bridge.py     TCP TM/TC bridge to YAMCS
├── replay.py           SeedManager — deterministic replay
└── simulation.py       SimulationMaster

srdb/data/hardware/     Equipment hardware profiles (YAML)
campaigns/              YAML campaign definitions
yamcs/                  YAMCS config + XTCE MDB
scripts/                setup-workspace.sh, demo.sh, start-yamcs.sh
tools/                  generate_xtce.py
docs/                   Architecture, equipment library, plugin,
                        design philosophy, validation guides
Dockerfile              Reproducible container image
```

---

## Related Projects

| Project | Role |
|---|---|
| [opensvf-kde](https://github.com/lipofefeyt/opensvf-kde) | C++ 6-DOF physics engine (FMI 2.0 FMU) |
| [openobsw](https://github.com/lipofefeyt/openobsw) | C11 OBSW: PUS, b-dot, ADCS PD, FDIR, validated on MSP430 |

---

## Roadmap

| Milestone | Status |
|---|---|
| M1–M12 — Core platform through ground segment | ✅ Done |
| M13 — SIL Attitude Loop Closure | ✅ Done |
| M14 — Real-Time & HIL | 🔄 In progress |
| M15 — Extended Bus Protocols (SpaceWire, CAN) | 📋 Planned |
| M16 — SRDB Maturity | ✅ Done |
| M17 — Equipment Configurability | ✅ Done |
| M18 — Architecture Refactor (subsystem layout, FMU management) | 📋 Planned |

---

## License

Apache 2.0 — see [`LICENSE`](LICENSE).

---

*Built by lipofefeyt · Sister projects: [opensvf-kde](https://github.com/lipofefeyt/opensvf-kde) · [openobsw](https://github.com/lipofefeyt/openobsw)*