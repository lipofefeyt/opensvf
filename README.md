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

## Design Philosophy

OpenSVF is a **flight software validation platform** — not an AOCS design tool and not a Simulink replacement.

It answers a specific question: *does my flight C code behave correctly against real physics and a real ground station?*

```
Hand-coded C algorithm (openobsw)
    ↓ obsw_sim binary under test
    ↓ sensor injection via typed pipe protocol
    ↓ validated against C++ physics (opensvf-kde plant model)
    ↓ validated against Python reference oracles
    ↓ ground station commanding via YAMCS
```

**Key distinctions:**

- `opensvf-kde` is the **spacecraft plant** (physics). It contains no control algorithm.
- `openobsw` contains the **flight algorithms** (b-dot, ADCS PD, FDIR). These are what's under test.
- Python reference controllers (e.g. `make_bdot_controller()`) are **validation oracles** — not flight code. They exist to compare against the C implementations.
- Monte Carlo in OpenSVF varies initial conditions and noise seeds against fixed C code — answering "what is the statistical performance of my actual flight software?" rather than a design model.

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
              Sensor models                    │ dipoles / RW torques
              MTQ, RW actuators        ────────►
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

## Ground Segment (YAMCS)

```bash
# Terminal 1
yamcs-start && yamcs-log-follow

# Terminal 2
svf-demo-fg
```

Open `http://localhost:8090` — live TM parameters, TC commanding from YAMCS UI.

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
| `make_bdot_controller()` | factory | AOCS | m = −k·Ḃ reference controller |
| `make_sbt()` | factory | TTC | Carrier lock, mode FSM |
| `make_pcdu()` | factory | EPS | LCL switching, MPPT, UVLO |
| `EpsFmu` | FmuEquipment | EPS | Solar array, Li-Ion battery |

---

## Project Structure

```
src/svf/
├── models/
│   ├── kde_equipment.py    KDE FMU wrapper
│   ├── obc.py / obc_stub.py / obc_emulator.py
│   ├── ttc.py              TtcEquipment + YamcsBridge
│   ├── magnetometer.py / magnetorquer.py
│   ├── gyroscope.py / css.py / bdot_controller.py
│   └── reaction_wheel.py / star_tracker.py
├── yamcs_bridge.py         TCP TM/TC bridge to YAMCS
├── replay.py               SeedManager — deterministic replay
└── simulation.py           SimulationMaster

yamcs/etc/                  YAMCS server + instance config
yamcs/mdb/                  XTCE mission database (from SRDB)
scripts/                    setup-workspace.sh, demo.sh, start-yamcs.sh
tools/generate_xtce.py      XTCE generator from SRDB
docs/                       Architecture, equipment library, plugin, validation guides
Dockerfile                  Reproducible container image
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
| M14 — Real-Time & HIL (Renode, real-time tick, variable timestep) | Planned |
| M15 — Extended Bus Protocols (SpaceWire, CAN) | Planned |
| M16 — SRDB Maturity (version handshake, CSV export) | Planned |

---

## License

Apache 2.0 — see [`LICENSE`](LICENSE).

---

*Built by lipofefeyt · Sister projects: [opensvf-kde](https://github.com/lipofefeyt/opensvf-kde) · [openobsw](https://github.com/lipofefeyt/openobsw)*