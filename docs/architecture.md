# SVF Architecture

> **Status:** v1.5
> **Last updated:** 2026-04
> **Author:** lipofefeyt

---

## 1. Overview

The Software Validation Facility (SVF) is an open-core platform for the validation of spacecraft software and systems. It connects four independent components into a single closed-loop simulation:

- **opensvf** — Python orchestration layer (this repo)
- **opensvf-kde** — C++ 6-DOF physics engine, compiled to FMI 2.0 FMU
- **openobsw** — C11 OBSW: PUS services, b-dot, ADCS PD, FDIR, validated on MSP430
- **YAMCS 5.12.6** — Ground station: TC uplink, TM display, XTCE MDB

---

## 2. Full System Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│  YAMCS 5.12.6 (Ground Station)                                       │
│  http://localhost:8090                                               │
│  XTCE MDB: 78 parameters, 2 containers, 2 commands                  │
└──────────────────────────┬───────────────────────────────────────────┘
                           │ PUS TM/TC via TCP (10015/10025)
┌──────────────────────────▼───────────────────────────────────────────┐
│  YamcsBridge + TtcEquipment                                          │
└──────────────────────────┬───────────────────────────────────────────┘
                           │ PUS bytes
┌──────────────────────────▼───────────────────────────────────────────┐
│  OBCEmulatorAdapter                                                  │
│  stdin:  [0x01] TC | [0x02] sensor injection                        │
│  stdout: [0x04] TM | [0x03] actuator frame | [0xFF] sync            │
│  stderr: SRDB version handshake                                      │
└──────────────────────────┬───────────────────────────────────────────┘
                           │ pipe protocol v3
┌──────────────────────────▼───────────────────────────────────────────┐
│  openobsw obsw_sim (C11)                                             │
│  FSM SAFE    → b-dot  → mtq_dipole[3]  (type-0x03)                 │
│  FSM NOMINAL → ADCS PD → rw_torque[3] (type-0x03)                  │
│  PUS S1/3/5/8/17/20                                                 │
│  SRDB_VERSION embedded at build time                                 │
└──────────────────────────┬───────────────────────────────────────────┘
                           │ actuator frame → CommandStore
┌──────────────────────────▼───────────────────────────────────────────┐
│  Actuator Models                                                     │
│  MTQ: torque = m × B  (b-dot dipoles from obsw_sim)                │
│  RW:  torque command  (ADCS torques from obsw_sim)                  │
│  THR: thrust, propellant tracking (Tsiolkovsky)                     │
└──────────────────────────┬───────────────────────────────────────────┘
                           │ torques → KDE IN ports
┌──────────────────────────▼───────────────────────────────────────────┐
│  opensvf-kde FMU (C++ physics)                                      │
│  OUT: true ω (rad/s) | true B (T) | true q (quaternion)            │
└──────────────────────────┬───────────────────────────────────────────┘
                           │ true state → sensor models
┌──────────────────────────▼───────────────────────────────────────────┐
│  Sensor Models (MAG, GYRO, ST, CSS, GPS)                            │
│  Noisy measurements → type-0x02 frame → obsw_sim stdin             │
│  GPS: ECI position/velocity + altitude                              │
└──────────────────────────┬───────────────────────────────────────────┘
                           │
┌──────────────────────────▼───────────────────────────────────────────┐
│  Thermal Model                                                       │
│  N-node network: solar input, radiation, conduction, dissipation    │
│  Outputs: cavity temp → equipment ambient reference                 │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 3. obsw_sim Wire Protocol (v3)

```
SVF → obsw_sim stdin:
  [0x01][uint16 BE len][TC frame]          TC uplink
  [0x02][uint16 BE len][sensor_frame_t]    MAG/GYRO/ST injection

obsw_sim → SVF stdout:
  [0x04][uint16 BE len][TM packet]         PUS TM downlink
  [0x03][uint16 BE len][actuator_frame_t]  Actuator commands
  [0xFF]                                   End of tick (sync)

obsw_sim stderr (startup only):
  [OBSW] Host sim started (type-frame protocol v2).
  [OBSW] SRDB version: 0.1.0
```

---

## 4. SRDB Version Handshake

At startup, `OBCEmulatorAdapter` reads SRDB version from `obsw_sim` stderr:

```
[obsw] [OBSW] SRDB version: 0.1.0
[obc-emu] SRDB version handshake OK: 0.1.0
```

If versions differ, a WARNING is logged — parameter names may be inconsistent between OBSW and SVF.

---

## 5. Hardware Profile System

Equipment models load physics constants from SRDB hardware YAML profiles:

```
srdb/data/hardware/
├── rw_default.yaml          Generic RW (6000 rpm, 0.2 Nm)
├── rw_sinclair_rw003.yaml   Sinclair RW-0.03 (5000 rpm, 30 mNm)
├── mtq_default.yaml         Generic MTQ (10 Am²)
├── mag_default.yaml         Generic MAG (1e-7 T noise)
├── gyro_default.yaml        Generic GYRO (ARW 1e-4)
├── thr_default.yaml         Cold gas (1 N, Isp=70s)
├── thr_moog_monarc_1.yaml   Hydrazine (1 N, Isp=220s)
├── gps_default.yaml         Generic GPS (5 m noise)
├── gps_novatel_oem7.yaml    NovAtel OEM7 (1.5 m noise)
└── thermal_default.yaml     3-node (panels + internal)
```

Profile loading is optional — all factories fall back to built-in defaults.

---

## 6. Tick Sources

| Tick Source | Behaviour | Use Case |
|---|---|---|
| `SoftwareTickSource` | Fast as possible | CI, Monte Carlo, batch |
| `RealtimeTickSource` | Wall-clock aligned | YAMCS demos, HIL |

`RealtimeTickSource` logs overrun warnings when a tick exceeds dt by >10%.

---

## 7. Deterministic Replay

```python
master = SimulationMaster(..., seed=42)
master.run()
# SVF seed: 42 → results/seed.json
```

Per-model seeds derived via SHA-256:
```python
seed_for_model = int.from_bytes(SHA256(f"{master}:{model_id}")[:4], "big")
```

---

## 8. Four Validation Levels

```
Level 1 — Model Validation         (M8/M9) ✅
Level 2 — Interface Validation     (M6/M9) ✅
Level 3 — Integration Validation   (M10)   ✅
Level 4 — System Validation        (M11–M13) ✅
  Real OBSW (OBCEmulatorAdapter)
  Real physics (opensvf-kde FMU)
  Real ground station (YAMCS)
  Mode-aware AOCS (b-dot ↔ ADCS PD)
  Hardware-profiled equipment models
```

---

## 9. Milestones

| Milestone | Status |
|---|---|
| M1–M10 — Core platform through closed-loop validation | ✅ Done |
| M11 — OBC Emulator Integration | ✅ Done |
| M11.5 — KDE Co-Simulation Integration | ✅ Done |
| M12 — Ground Segment (YAMCS) | ✅ Done |
| M13 — SIL Attitude Loop Closure (ADCS closed loop) | ✅ Done |
| M14 — Real-Time & HIL | 🔄 In progress |
| M15 — Extended Bus Protocols (SpaceWire, CAN) | 📋 Planned |
| M16 — SRDB Maturity (version handshake, CSV export) | ✅ Done |
| M17 — Equipment Configurability (hardware profiles, thruster, GPS, thermal) | ✅ Done |
| M18 — Architecture Refactor (subsystem layout, FMU management) | 📋 Planned |