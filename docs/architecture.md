# SVF Architecture

> **Status:** v1.4
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
│  stdin:  [0x01] TC uplink                                           │
│          [0x02] sensor injection (MAG/GYRO/ST each tick)            │
│  stdout: [0x04] TM packets                                          │
│          [0x03] actuator frame (dipoles / RW torques)               │
│          [0xFF] sync byte                                            │
└──────────────────────────┬───────────────────────────────────────────┘
                           │ pipe protocol
┌──────────────────────────▼───────────────────────────────────────────┐
│  openobsw obsw_sim (C11)                                             │
│  FSM SAFE    → b-dot  → mtq_dipole[3]  (type-0x03)                 │
│  FSM NOMINAL → ADCS PD → rw_torque[3] (type-0x03)                  │
│  PUS S1/3/5/8/17/20                                                 │
└──────────────────────────┬───────────────────────────────────────────┘
                           │ actuator frame → CommandStore
┌──────────────────────────▼───────────────────────────────────────────┐
│  Actuator Models                                                     │
│  MTQ: torque = m × B  (b-dot dipoles from obsw_sim)                │
│  RW:  torque command  (ADCS torques from obsw_sim)                  │
└──────────────────────────┬───────────────────────────────────────────┘
                           │ torques → KDE IN ports
┌──────────────────────────▼───────────────────────────────────────────┐
│  opensvf-kde FMU (C++ physics)                                      │
│  OUT: true ω (rad/s) | true B (T) | true q (quaternion)            │
└──────────────────────────┬───────────────────────────────────────────┘
                           │ true state → sensor models
┌──────────────────────────▼───────────────────────────────────────────┐
│  Sensor Models (MAG, GYRO, ST, CSS)                                 │
│  Noisy measurements → type-0x02 frame → obsw_sim stdin             │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 3. obsw_sim Wire Protocol (v3)

```
SVF → obsw_sim stdin (type-prefixed):
  [0x01][uint16 BE len][TC frame]          TC uplink
  [0x02][uint16 BE len][sensor_frame_t]    MAG/GYRO/ST injection

obsw_sim → SVF stdout (type-prefixed):
  [0x04][uint16 BE len][TM packet]         PUS TM downlink
  [0x03][uint16 BE len][actuator_frame_t]  Actuator commands
  [0xFF]                                   End of tick (sync)
```

### obsw_sensor_frame_t (type 0x02)

```c
typedef struct {
    float mag_x, mag_y, mag_z; uint8_t mag_valid;
    float st_q_w, st_q_x, st_q_y, st_q_z; uint8_t st_valid;
    float gyro_x, gyro_y, gyro_z; uint8_t gyro_valid;
    float sim_time;
} obsw_sensor_frame_t;
```

### obsw_actuator_frame_t (type 0x03)

```c
typedef struct {
    float mtq_dipole_x, mtq_dipole_y, mtq_dipole_z;  // Am² (b-dot)
    float rw_torque_x,  rw_torque_y,  rw_torque_z;   // Nm  (ADCS)
    uint8_t controller;  // 0=bdot (SAFE), 1=adcs (NOMINAL)
    float sim_time;
} obsw_actuator_frame_t;
```

---

## 4. Mode-Aware AOCS

The real C OBSW selects the control algorithm based on FSM state:

```
FSM state = SAFE:
  if mag_valid:
    b-dot: m = -k · dB/dt
    → mtq_dipole[3] in actuator frame
    → CommandStore → MTQ.read_port() → torque = m × B → KDE

FSM state = NOMINAL:
  if st_valid AND gyro_valid:
    ADCS PD: τ = -Kp·q_err_vec - Kd·ω
    → rw_torque[3] in actuator frame
    → CommandStore → RW.read_port() → KDE
  else fallback to b-dot
```

This matches flight OBSW behaviour: magnetorquers for detumbling, reaction wheels for precision pointing.

---

## 5. Deterministic Replay

```python
# Auto-generated seed logged to results/seed.json
master = SimulationMaster(...)
master.run()
# SVF seed: 809481067

# Exact replay
master = SimulationMaster(..., seed=809481067)
master.run()  # identical noise, identical AOCS trajectory
```

Per-model seeds derived via SHA-256:
```python
seed_for_model = int.from_bytes(SHA256(f"{master}:{model_id}")[:4], "big")
```

---

## 6. Four Validation Levels

```
Level 1 — Model Validation         (M8/M9) ✅
Level 2 — Interface Validation     (M6/M9) ✅
Level 3 — Integration Validation   (M10)   ✅
Level 4 — System Validation        (M11–M13) ✅
  Real OBSW (OBCEmulatorAdapter)
  Real physics (opensvf-kde FMU)
  Real ground station (YAMCS)
  Mode-aware AOCS (b-dot ↔ ADCS PD)
```

---

## 7. Milestones

| Milestone | Status |
|---|---|
| M1–M10 — Core platform through closed-loop validation | ✅ Done |
| M11 — OBC Emulator Integration | ✅ Done |
| M11.5 — KDE Co-Simulation Integration | ✅ Done |
| M12 — Ground Segment (YAMCS) | ✅ Done |
| M13 — SIL Attitude Loop Closure (ADCS closed loop) | ✅ Done |
| M14 — Real-Time & HIL (Renode, real-time tick, Dockerfile) | Planned |