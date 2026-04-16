# SVF Architecture

> **Status:** v2.0
> **Last updated:** 2026-04
> **Author:** lipofefeyt

---

## 1. Overview

The Software Validation Facility (SVF) is an open-core platform for the validation of spacecraft software and systems. It connects four independent components into a single closed-loop simulation:

- **opensvf** — Python orchestration layer (this repo)
- **opensvf-kde** — C++ 6-DOF physics engine, compiled to FMI 2.0 FMU
- **openobsw** — C11 OBSW: PUS services, b-dot, ADCS PD, FDIR
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
│                                                                      │
│  PIPE MODE (default):           SOCKET MODE (Renode):               │
│  obsw_sim (x86_64)              Renode ZynqMP uart0 TCP:3456        │
│  obsw_sim_aarch64 (QEMU)        obsw_zynqmp bare-metal              │
│                                                                      │
│  stdin:  [0x01] TC | [0x02] sensor injection                        │
│  stdout: [0x04] TM | [0x03] actuator frame | [0xFF] sync            │
│  stderr: SRDB version handshake                                      │
└──────────────────────────┬───────────────────────────────────────────┘
                           │ pipe / TCP socket (same protocol)
┌──────────────────────────▼───────────────────────────────────────────┐
│  openobsw C11 OBSW                                                   │
│  FSM SAFE    → b-dot  → mtq_dipole[3]  (type-0x03)                 │
│  FSM NOMINAL → ADCS PD → rw_torque[3] (type-0x03)                  │
│  PUS S1/3/5/8/17/20                                                 │
│  SRDB_VERSION embedded at build time                                 │
└──────────────────────────┬───────────────────────────────────────────┘
                           │ actuator frame → CommandStore
┌──────────────────────────▼───────────────────────────────────────────┐
│  Actuator Models (AOCS)                                              │
│  MTQ: torque = m × B                                                │
│  RW:  torque command                                                 │
│  THR: thrust, propellant tracking (Tsiolkovsky)                     │
└──────────────────────────┬───────────────────────────────────────────┘
                           │ torques → KDE IN ports
┌──────────────────────────▼───────────────────────────────────────────┐
│  opensvf-kde FMU (C++ physics)                                      │
│  OUT: true ω (rad/s) | true B (T) | true q (quaternion)            │
└──────────────────────────┬───────────────────────────────────────────┘
                           │ true state → sensor models
┌──────────────────────────▼───────────────────────────────────────────┐
│  Sensor Models (AOCS)                                                │
│  MAG, GYRO, ST, CSS, GPS — noisy measurements → 0x02 frames        │
└────────────────────────────────────────────────────────────────────  │
┌──────────────────────────▼───────────────────────────────────────────┐
│  Thermal Model                                                       │
│  N-node network: solar input, radiation, conduction, dissipation    │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 3. OBSW Transport Modes

### Pipe mode (x86_64 / aarch64 QEMU)

```python
obc = OBCEmulatorAdapter(
    sim_path="obsw_sim",          # or "obsw_sim_aarch64" (auto-detects QEMU)
    sync_protocol=sync,
    store=store,
    command_store=cmd_store,
)
```

### Socket mode (Renode ZynqMP)

```python
# Start Renode first: renode renode/zynqmp_obsw.resc
obc = OBCEmulatorAdapter(
    sim_path=None,
    socket_addr=("localhost", 3456),
    sync_protocol=sync,
    store=store,
    command_store=cmd_store,
)
```

Both modes use identical wire protocol v3.

---

## 4. Wire Protocol v3

```
SVF → obsw_sim stdin (or Renode socket):
  [0x01][uint16 BE len][TC frame]          TC uplink
  [0x02][uint16 BE len][sensor_frame_t]    MAG/GYRO/ST injection

obsw_sim → SVF stdout (or Renode socket):
  [0x04][uint16 BE len][TM packet]         PUS TM downlink
  [0x03][uint16 BE len][actuator_frame_t]  Actuator commands
  [0xFF]                                   End of tick

obsw_sim stderr (startup):
  [OBSW] Host sim started (type-frame protocol v2).
  [OBSW] SRDB version: 0.1.0
```

---

## 5. Model Organisation

```
src/svf/models/
├── aocs/       reaction_wheel, magnetometer, magnetorquer, gyroscope,
│               star_tracker, css, bdot_controller, thruster, gps
├── dynamics/   kde_equipment
│   └── fmu/    DynamicsFmu
├── eps/        pcdu
│   └── fmu/    EpsFmu, BatteryFmu, SolarArrayFmu, PcduFmu
├── dhs/        obc, obc_stub, obc_emulator
├── ttc/        ttc, sbt
└── thermal/    thermal
```

---

## 6. Tick Sources

| Tick Source | Behaviour | Use Case |
|---|---|---|
| `SoftwareTickSource` | Fast as possible | CI, Monte Carlo, batch |
| `RealtimeTickSource` | Wall-clock aligned | YAMCS demos, HIL |

### Variable Timestep

Any model can suggest a smaller step size:

```python
class MyModel(NativeEquipment):
    def suggested_dt(self) -> float:
        return 0.01  # force 10ms steps

# SimulationMaster uses min(fixed_dt, all model suggestions)
```

---

## 7. Hardware Profile System

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

---

## 8. Deterministic Replay

```python
master = SimulationMaster(..., seed=42)
master.run()
# SVF seed: 42 → results/seed.json
```

---

## 9. Four Validation Levels

```
Level 1 — Model Validation         (M8/M9)   ✅
Level 2 — Interface Validation     (M6/M9)   ✅
Level 3 — Integration Validation   (M10)     ✅
Level 4 — System Validation        (M11–M14) ✅
  Real OBSW via pipe (x86_64/aarch64 QEMU)
  Real OBSW via socket (Renode ZynqMP)
  Real physics (opensvf-kde FMU)
  Real ground station (YAMCS)
  Mode-aware AOCS (b-dot ↔ ADCS PD)
  Hardware-profiled equipment models
```

---

## 10. Milestones

| Milestone | Status |
|---|---|
| M1–M12 — Core platform through ground segment | ✅ Done |
| M13 — SIL Attitude Loop Closure | ✅ Done |
| M14 — Real-Time & HIL + Renode socket + variable timestep | ✅ Done |
| M15 — Extended Bus Protocols (SpaceWire, CAN) | 📋 Planned |
| M16 — SRDB Maturity | ✅ Done |
| M17 — Equipment Configurability | ✅ Done |
| M18 — Architecture Refactor | ✅ Done |