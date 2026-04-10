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

Three independent projects run together in a single simulation tick:

```
opensvf-kde (C++ / Eigen3)          openobsw (C11 / bare metal)
  6-DOF physics engine                 Real OBSW binary
  Euler's equations                    b-dot algorithm
  Quaternion kinematics                PUS S1/3/5/8/17/20
  Earth B-field model                  FDIR state machine
         │                                     │
         │  true ω, B  via FMI 2.0            │  TC/TM via pipe protocol
         ▼                                     ▼
              opensvf (Python / pytest)
                SVF tick loop (DDS lockstep)
                Sensor models (MAG, GYRO, ST, CSS)
                Actuator models (MTQ, RW, PCDU)
                OBC models (stub / emulator)
                PUS commanding chain
                Campaign manager + reports
                         │
                         │  PUS TM/TC via TCP
                         ▼
                    YAMCS 5.12.6
                    Ground station UI
                    XTCE mission database
                    TC uplink / TM display
```

---

## Ground Segment (YAMCS)

OpenSVF integrates with YAMCS as a real ground station:

```bash
# Terminal 1 — start YAMCS
source scripts/setup-workspace.sh
yamcs-start && yamcs-log-follow

# Terminal 2 — run simulation
source scripts/setup-workspace.sh
svf-demo-fg
```

Then open `http://localhost:8090` — the opensvf instance shows live TM parameters, and TC commands can be sent from the YAMCS UI directly to the simulated OBC.

The XTCE mission database is auto-generated from SRDB on every YAMCS start — 78 parameters, 2 TM containers, 2 commands.

---

## The OBC Stack

Three drop-in implementations — swap with one line at the composition root:

```python
# Level 3 — rule-based OBSW behaviour simulator
obc = ObcStub(config, sync, store, cmd_store, rules=[
    Rule(
        name="low_battery_safe",
        watch="eps.battery.soc",
        condition=lambda e: e is not None and e.value < 0.3,
        action=lambda cs, t: cs.inject("dhs.obc.mode_cmd", 0.0, t=t),
    ),
])

# Level 4 — real OBSW binary under test
obc = OBCEmulatorAdapter(sim_path="obsw_sim", ...)

# TtcEquipment accepts both — and optionally connects to YAMCS
ttc = TtcEquipment(obc, sync, store, cmd_store, yamcs_bridge=bridge)
```

---

## Deterministic Replay

Every simulation run logs its seed to `results/seed.json`:

```
SVF seed: 809481067  (replay with seed=809481067)
```

Replay any run exactly:

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
| `OBCEmulatorAdapter` | class | DHS | Real OBSW via binary pipe |
| `TtcEquipment` | class | TTC | TC/TM pipe, optional YAMCS bridge |
| `YamcsBridge` | class | GND | TCP TM/TC bridge to YAMCS |
| `make_kde_equipment()` | factory | Dynamics | 6-DOF physics, B-field model |
| `make_reaction_wheel()` | factory | AOCS | Torque, friction, temperature |
| `make_star_tracker()` | factory | AOCS | Quaternion, noise, sun blinding |
| `make_magnetometer()` | factory | AOCS | B-field measurement + noise |
| `make_magnetorquer()` | factory | AOCS | Torque = m × B |
| `make_gyroscope()` | factory | AOCS | Rate measurement + ARW noise |
| `make_css()` | factory | AOCS | Sun vector + eclipse detection |
| `make_bdot_controller()` | factory | AOCS | m = −k·Ḃ detumbling law |
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
│   ├── kde_equipment.py    KDE FMU wrapper (NativeEquipment)
│   ├── obc.py              ObcEquipment — simulated OBC
│   ├── obc_stub.py         ObcStub — rule-based OBSW simulator
│   ├── obc_emulator.py     OBCEmulatorAdapter — real OBSW via pipe
│   ├── ttc.py              TtcEquipment (ObcInterface + YamcsBridge)
│   ├── magnetometer.py     MAG with noise + bias drift
│   ├── magnetorquer.py     MTQ torque = m × B
│   ├── gyroscope.py        GYRO with ARW noise + bias drift
│   ├── css.py              CSS sun vector + eclipse
│   ├── bdot_controller.py  B-dot reference controller
│   └── ...
├── yamcs_bridge.py         TCP TM/TC bridge to YAMCS
├── replay.py               SeedManager — deterministic replay
├── simulation.py           SimulationMaster (seed param)
├── pus/                    PUS-C TC/TM (S1/3/5/8/17/20)
├── campaign/               YAML campaigns + HTML reports
└── plugin/                 pytest plugin (xdist compatible)

yamcs/
├── etc/                    YAMCS server + instance config
└── mdb/                    XTCE mission database (from SRDB)

scripts/
├── setup-workspace.sh      One-shot environment setup
├── start-yamcs.sh          Start YAMCS ground station
├── demo.sh                 Full demo (tmux, two windows)
└── demo_yamcs.py           SVF + YAMCS demo script

tools/
└── generate_xtce.py        XTCE generator from SRDB
```

---

## Related Projects

| Project | Role |
|---|---|
| [opensvf-kde](https://github.com/lipofefeyt/opensvf-kde) | C++ 6-DOF physics engine (FMI 2.0 FMU) |
| [openobsw](https://github.com/lipofefeyt/openobsw) | C11 OBSW: PUS services, b-dot, FDIR, validated on MSP430 |

---

## Roadmap

| Milestone | Status |
|---|---|
| M1–M10 — Core platform through closed-loop validation | ✅ Done |
| M11 — OBC Emulator Integration | ✅ Done |
| M11.5 — KDE Co-Simulation Integration | ✅ Done |
| M12 — Ground Segment (YAMCS) | ✅ Done |
| Next — Dockerfile, SpaceWire, CAN, variable timestep | Planned |

---

## License

Apache 2.0 — see [`LICENSE`](LICENSE).

---

*Built by lipofefeyt · Sister projects: [opensvf-kde](https://github.com/lipofefeyt/opensvf-kde) · [openobsw](https://github.com/lipofefeyt/openobsw)*