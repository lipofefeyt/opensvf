# OpenSVF

**Open-core spacecraft Software Validation Facility**

OpenSVF is a Python-based platform for validating spacecraft software and systems — from individual subsystem models to full closed-loop co-simulation with a C++ physics engine, a real OBSW binary, and a YAMCS ground station.

---

## What is an SVF?

From ECSS-E-TM-10-21A:

> *System modelling and simulation is a support activity to OBSW validation. The ability to inject failures in the models enables the user to trigger the OBSW monitoring processes as well as to exercise the FDIR mechanisms.*

OpenSVF implements this across four validation levels:

| Level | Description | Status |
|---|---|---|
| 1 — Model validation | Each subsystem verified in isolation | ✅ Complete |
| 2 — Interface validation | Bus interfaces + full fault matrix | ✅ Complete |
| 3 — Integration validation | Models + PUS chain + closed-loop FDIR | ✅ Complete |
| 4 — System validation | Real OBSW + C++ physics + YAMCS ground station | ✅ Complete |

---

## Quick Start

```bash
git clone https://github.com/lipofefeyt/opensvf
cd opensvf
source scripts/setup-workspace.sh

# Run all tests
testosvf

# Run a campaign
svf run campaigns/fdir_chain.yaml

# Full demo: SVF + YAMCS ground station
bash scripts/demo.sh
```

---

## The Closed Loop

Four independent components run together in a single simulation tick:

```
opensvf-kde (C++ / Eigen3)          openobsw (C11 / bare metal)
  6-DOF physics engine                 Real OBSW binary
  Euler's equations                    b-dot (SAFE mode)
  Quaternion kinematics                ADCS PD (NOMINAL mode)
  Earth B-field model                  PUS S1/3/5/8/17/20
         │                             FDIR state machine
         │  true ω, B  via FMI 2.0           │
         ▼                                    │ type-0x02 sensor frames
              opensvf (Python)         ◄──────┘
              SVF tick loop                    │ type-0x03 actuator frames
              Sensor models                    │ (dipoles / RW torques)
              MTQ, RW actuators        ────────►
              PUS commanding
                    │
                    │  PUS TM/TC via TCP
                    ▼
               YAMCS 5.12.6
               Ground station UI
               TC uplink / TM display
```

**Mode-aware AOCS:**
- FSM SAFE + MAG valid → b-dot → MTQ dipoles → torque = m×B → KDE
- FSM NOMINAL + ST + GYRO → ADCS PD → RW torques → KDE

---

## Ground Segment (YAMCS)

```bash
# Terminal 1 — start YAMCS
source scripts/setup-workspace.sh
yamcs-start && yamcs-log-follow

# Terminal 2 — run simulation
source scripts/setup-workspace.sh
svf-demo-fg
```

Then open `http://localhost:8090` — the opensvf instance shows live TM parameters and TC commands can be sent from the YAMCS UI to the simulated OBC.

The XTCE mission database (78 parameters, 2 TM containers, 2 commands) is auto-generated from SRDB on every YAMCS start.

---

## The OBC Stack

Three drop-in implementations via `ObcInterface`:

```python
# Level 3 — rule-based OBSW behaviour simulator
obc = ObcStub(config, sync, store, cmd_store, rules=[...])

# Level 4 — real OBSW binary under test
obc = OBCEmulatorAdapter(sim_path="obsw_sim", ...)

# With YAMCS ground station
bridge = YamcsBridge(store)
bridge.start()
ttc = TtcEquipment(obc, sync, store, cmd_store, yamcs_bridge=bridge)
```

---

## Wire Protocol (obsw_sim ↔ SVF)

```
SVF → obsw_sim stdin:
  [0x01][uint16 BE len][TC frame]          — TC uplink
  [0x02][uint16 BE len][sensor_frame_t]    — MAG/GYRO/ST injection

obsw_sim → SVF stdout:
  [0x04][uint16 BE len][TM packet]         — PUS TM downlink
  [0x03][uint16 BE len][actuator_frame_t]  — dipoles / RW torques
  [0xFF]                                   — end of tick (sync)
```

---

## Deterministic Replay

Every run logs its seed to `results/seed.json`:

```
SVF seed: 809481067  (replay with seed=809481067)
```

Replay exactly:

```python
master = SimulationMaster(..., seed=809481067)
master.run()  # identical noise, identical results
```

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
| `make_bdot_controller()` | factory | AOCS | m = −k·Ḃ detumbling (reference) |
| `make_sbt()` | factory | TTC | Carrier lock, mode FSM |
| `make_pcdu()` | factory | EPS | LCL switching, MPPT, UVLO |
| `EpsFmu` | FmuEquipment | EPS | Solar array, Li-Ion battery |

---

## Validated Campaigns

| Campaign | Scenario | Level |
|---|---|---|
| `eps_validation.yaml` | EPS power system | 1 |
| `mil1553_validation.yaml` | 1553 bus + FDIR | 2 |
| `pus_validation.yaml` | PUS commanding chain | 3 |
| `platform_validation.yaml` | Full platform | 3 |
| `safe_mode_recovery.yaml` | Closed-loop recovery | 3/4 |
| `nominal_ops.yaml` | Nominal operations | 3/4 |
| `contact_pass.yaml` | Ground contact pass | 3/4 |
| `fdir_chain.yaml` | FDIR chain end-to-end | 3/4 |

---

## Project Structure

```
src/svf/
├── models/
│   ├── kde_equipment.py    KDE FMU wrapper
│   ├── obc.py              ObcEquipment — simulated OBC
│   ├── obc_stub.py         ObcStub — rule-based OBSW simulator
│   ├── obc_emulator.py     OBCEmulatorAdapter — real OBSW via pipe
│   ├── ttc.py              TtcEquipment (ObcInterface + YamcsBridge)
│   ├── magnetometer.py     MAG with noise + bias drift
│   ├── magnetorquer.py     MTQ torque = m × B
│   ├── gyroscope.py        GYRO with ARW noise + bias drift
│   ├── css.py              CSS sun vector + eclipse
│   └── bdot_controller.py  B-dot reference controller
├── yamcs_bridge.py         TCP TM/TC bridge to YAMCS
├── replay.py               SeedManager — deterministic replay
└── simulation.py           SimulationMaster (seed, explicit DDS teardown)

yamcs/
├── etc/                    YAMCS server + instance config
└── mdb/                    XTCE mission database (from SRDB)

scripts/
├── setup-workspace.sh      One-shot environment setup
├── start-yamcs.sh          Start YAMCS ground station
├── demo.sh                 Full demo (tmux)
└── demo_yamcs.py           SVF + YAMCS demo script
```

---

## Related Projects

| Project | Role |
|---|---|
| [opensvf-kde](https://github.com/lipofefeyt/opensvf-kde) | C++ 6-DOF physics engine (FMI 2.0 FMU) |
| [openobsw](https://github.com/lipofefeyt/openobsw) | C11 OBSW: PUS, b-dot, ADCS, FDIR, validated on MSP430 |

---

## Roadmap

| Milestone | Status |
|---|---|
| M1–M12 — Core platform through ground segment | ✅ Done |
| M13 — SIL Attitude Loop Closure (ADCS closed loop) | ✅ Done |
| M14 — Real-Time & HIL (Renode, real-time tick, Dockerfile) | Planned |

---

## License

Apache 2.0 — see [`LICENSE`](LICENSE).

---

*Built by lipofefeyt · Sister projects: [opensvf-kde](https://github.com/lipofefeyt/opensvf-kde) · [openobsw](https://github.com/lipofefeyt/openobsw)*