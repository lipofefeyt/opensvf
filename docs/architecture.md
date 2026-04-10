# SVF Architecture

> **Status:** v1.3
> **Last updated:** 2026-04
> **Author:** lipofefeyt

---

## 1. Overview

The Software Validation Facility (SVF) is an open-core platform for the validation of spacecraft software and systems. It connects four independent components into a single closed-loop simulation:

- **opensvf** — Python orchestration layer (this repo)
- **opensvf-kde** — C++ 6-DOF physics engine, compiled to FMI 2.0 FMU
- **openobsw** — C11 OBSW: PUS services, b-dot, FDIR, validated on MSP430
- **YAMCS 5.12.6** — Ground station: TC uplink, TM display, XTCE MDB

---

## 2. Full System Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│  YAMCS 5.12.6 (Ground Station)                                       │
│  http://localhost:8090                                               │
│  XTCE MDB: 78 parameters, 2 containers, 2 commands                  │
│  TC uplink (operator) | TM display (live parameters)                │
└──────────────────────────┬───────────────────────────────────────────┘
                           │ PUS TM/TC via TCP (10015/10025)
┌──────────────────────────▼───────────────────────────────────────────┐
│  YamcsBridge                                                         │
│  TCP server: TM on 10015, TC on 10025                               │
│  send_tm(): push PUS bytes to YAMCS each tick                       │
│  get_tc(): drain TC queue from YAMCS operator                       │
└──────────────────────────┬───────────────────────────────────────────┘
                           │ PUS bytes
┌──────────────────────────▼───────────────────────────────────────────┐
│  TtcEquipment (ObcInterface + optional YamcsBridge)                 │
└──────────────────────────┬───────────────────────────────────────────┘
                           │
┌──────────────────────────▼───────────────────────────────────────────┐
│  OBC (three implementations, drop-in via ObcInterface)              │
│  ObcEquipment | ObcStub (rules) | OBCEmulatorAdapter (real OBSW)   │
└──────────────────────────┬───────────────────────────────────────────┘
                           │ 1553 BC / pipe protocol
┌──────────────────────────▼───────────────────────────────────────────┐
│  Bus Adapters + Actuators                                            │
│  Mil1553Bus (fault injection) | MTQ | RW | PCDU                     │
└──────────────────────────┬───────────────────────────────────────────┘
                           │ torques → KDE IN ports
┌──────────────────────────▼───────────────────────────────────────────┐
│  opensvf-kde FMU (C++ physics)                                      │
│  6-DOF Euler integration + quaternion kinematics                    │
│  Earth B-field model                                                │
│  OUT: true ω (rad/s) | true B (T) | true q (quaternion)            │
└──────────────────────────┬───────────────────────────────────────────┘
                           │ true state → sensor truth ports
┌──────────────────────────▼───────────────────────────────────────────┐
│  Sensor Models                                                       │
│  MAG: true B + noise + bias drift                                   │
│  GYRO: true ω + ARW noise + bias                                    │
│  CSS: sun vector + eclipse detection                                │
│  ST: quaternion propagation + blinding                              │
└──────────────────────────┬───────────────────────────────────────────┘
                           │ noisy measurements
┌──────────────────────────▼───────────────────────────────────────────┐
│  ParameterStore (TM) | CommandStore (TC)                            │
│  SRDB canonical names | WiringMap connections                       │
└──────────────────────────┬───────────────────────────────────────────┘
                           │
┌──────────────────────────▼───────────────────────────────────────────┐
│  SimulationMaster (DDS lockstep, seed management)                   │
│  pytest + SVF plugin (xdist compatible) + campaigns + reports       │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 3. Design Principles

**Equipment as the universal abstraction.**
Every model — FMU, native Python, C++ physics engine, real OBSW binary — is an `Equipment`. `SimulationMaster` drives all of them identically.

**ObcInterface — the HIL plug-in point.**
`TtcEquipment` accepts any `ObcInterface`:
- `ObcEquipment` — simulated OBC
- `ObcStub` — configurable rule-based OBSW simulator
- `OBCEmulatorAdapter` — real OBSW binary via pipe protocol

**YamcsBridge — the ground segment plug-in point.**
`TtcEquipment` optionally accepts a `YamcsBridge`. When present, TM flows to YAMCS each tick and TC from the YAMCS operator is forwarded to the OBC.

**FMI 2.0 as the physics boundary.**
The KDE C++ engine is wrapped as an FMI 2.0 Co-Simulation FMU. One SVF tick = one FMU `doStep()`.

**SRDB as the shared parameter contract.**
Every parameter has one canonical name. The XTCE mission database is auto-generated from SRDB on every YAMCS start.

**Deterministic replay.**
`SeedManager` derives per-model seeds from a master seed via SHA-256. Every run logs its seed to `results/seed.json`. Replay = run again with the same seed.

---

## 4. YAMCS Integration

### Bridge Architecture

```
SVF (TCP server)              YAMCS (TCP client)
  port 10015  ←connects—  TM data link
  port 10025  ←connects—  TC data link
```

SVF is the server. YAMCS connects as a client. This means SVF can start/stop independently — YAMCS reconnects automatically.

### XTCE Mission Database

Generated from SRDB via `tools/generate_xtce.py`:

```bash
python3 tools/generate_xtce.py > yamcs/mdb/opensvf.xml
```

Contains:
- 78 TM parameters (from SRDB TM classification)
- TM containers: `TM_17_2` (ping response), `TM_3_25` (HK report)
- Commands: `TC_17_1_AreYouAlive`, `TC_20_1_SetParameter`

### Workflow

```bash
# Terminal 1
yamcs-start && yamcs-log-follow

# Terminal 2
svf-demo-fg
```

Or one command:
```bash
bash scripts/demo.sh
```

---

## 5. Deterministic Replay

```python
# Run with auto-generated seed (logged to results/seed.json)
master = SimulationMaster(...)
master.run()
# SVF seed: 809481067  (replay with seed=809481067)

# Replay exactly
master = SimulationMaster(..., seed=809481067)
master.run()  # identical noise, identical results
```

Per-model seeds are derived as:
```python
seed_for_model = SHA256(f"{master_seed}:{model_id}")[:4]
```

---

## 6. Four Validation Levels

```
Level 1 — Model Validation
  Each equipment verified in isolation
  Nominal + failure test procedures per model
  Status: complete (M8/M9)

Level 2 — Interface Validation
  1553 bus interfaces + full fault matrix
  Status: complete (M6/M9)

Level 3 — Integration Validation
  Models + PUS chain + closed-loop FDIR scenarios
  OBC stub drives all transitions
  Status: complete (M10)

Level 4 — System Validation
  Real OBSW binary (OBCEmulatorAdapter)
  Real C++ physics (opensvf-kde FMU)
  Real ground station (YAMCS)
  Full closed-loop co-simulation
  Status: complete (M11/M11.5/M12)
```

---

## 7. Milestones

| Milestone | Status |
|---|---|
| M1–M5 — Core platform | ✅ Done |
| M6 — Bus Protocols (1553) | ✅ Done |
| M7 — PUS TM/TC | ✅ Done |
| M8 — Equipment Interface Library | ✅ Done |
| M9 — Model & Interface Validation | ✅ Done |
| M10 — Integration & System Validation | ✅ Done |
| M11 — OBC Emulator Integration | ✅ Done |
| M11.5 — KDE Co-Simulation Integration | ✅ Done |
| M12 — Ground Segment (YAMCS) | ✅ Done |
| Next — Dockerfile, SpW, CAN, variable timestep | Planned |