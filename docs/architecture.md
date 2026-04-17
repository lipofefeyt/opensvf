# SVF Architecture

> **Status:** v2.1
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

## 2. Entry Points

### Zero-Python (M19)

```bash
python3 -c "
from svf.spacecraft import SpacecraftLoader
SpacecraftLoader.load('spacecraft.yaml').run()
"
```

### Python API

```python
from svf.spacecraft import SpacecraftLoader
master = SpacecraftLoader.load("spacecraft.yaml")
master.run()
```

### Low-level (full control)

```python
participant = DomainParticipant()
sync      = DdsSyncProtocol(participant)
store     = ParameterStore()
cmd_store = CommandStore()
# ... instantiate equipment manually ...
master = SimulationMaster(...)
master.run()
```

---

## 3. Spacecraft Configuration (M19)

```yaml
spacecraft: MySat-1

obsw:
  type: pipe | socket | stub
  binary: ./obsw_sim        # pipe mode
  host: localhost            # socket mode
  port: 3456                 # socket mode

equipment:
  - id: mag1
    model: magnetometer
    hardware_profile: mag_default
    seed: 42

buses:
  - id: aocs_bus
    type: mil1553 | spacewire | can
    ...

wiring:
  auto: true
  overrides:
    - from: mag1.aocs.mag.field_x
      to:   obc.aocs.mag1.field_x

simulation:
  dt: 0.1
  stop_time: 300.0
  seed: 42
  realtime: false
```

**Auto-wiring:** SVF connects OUT→IN port pairs automatically when they share the same canonical name. Explicit overrides handle non-standard connections.

---

## 4. Full System Architecture

```
┌──────────────────────────────────────────────────────────┐
│  YAMCS 5.12.6  http://localhost:8090                     │
│  XTCE MDB: parameters, containers, commands              │
└──────────────────────┬───────────────────────────────────┘
                       │ PUS TM/TC via TCP
┌──────────────────────▼───────────────────────────────────┐
│  YamcsBridge + TtcEquipment                              │
└──────────────────────┬───────────────────────────────────┘
                       │ PUS bytes
┌──────────────────────▼───────────────────────────────────┐
│  OBCEmulatorAdapter                                      │
│  PIPE:   obsw_sim (x86_64) or obsw_sim_aarch64 (QEMU)   │
│  SOCKET: Renode ZynqMP uart0 TCP:3456                    │
│  STUB:   ObcStub rule engine                             │
└──────────────────────┬───────────────────────────────────┘
                       │ wire protocol v3
┌──────────────────────▼───────────────────────────────────┐
│  openobsw C11 OBSW                                       │
│  b-dot → MTQ dipoles | ADCS PD → RW torques             │
│  PUS S1/3/5/8/17/20  FDIR FSM                           │
└──────────────────────┬───────────────────────────────────┘
                       │ actuator frame → CommandStore
┌──────────────────────▼───────────────────────────────────┐
│  Bus Adapters (optional)                                 │
│  MIL-STD-1553B | SpaceWire+RMAP | CAN 2.0B (ECSS)      │
│  Fault injection: BUS_ERROR, NO_RESPONSE, BAD_PARITY    │
└──────────────────────┬───────────────────────────────────┘
                       │ torques → KDE
┌──────────────────────▼───────────────────────────────────┐
│  opensvf-kde FMU (C++ / Eigen3)                         │
│  6-DOF physics, Euler equations, B-field model          │
│  OUT: true ω, true B, true q                            │
└──────────────────────┬───────────────────────────────────┘
                       │ true state → sensor models
┌──────────────────────▼───────────────────────────────────┐
│  Sensor Models: MAG GYRO ST CSS GPS                     │
│  Noisy measurements → type-0x02 frames → OBSW           │
└──────────────────────┬───────────────────────────────────┘
┌──────────────────────▼───────────────────────────────────┐
│  Thermal Model: N-node radiation/conduction network      │
└──────────────────────────────────────────────────────────┘
```

---

## 5. Wire Protocol v3

```
SVF → OBSW (stdin or TCP):
  [0x01][uint16 BE len][TC frame]          TC uplink
  [0x02][uint16 BE len][sensor_frame_t]    Sensor injection

OBSW → SVF (stdout or TCP):
  [0x04][uint16 BE len][TM packet]         PUS TM
  [0x03][uint16 BE len][actuator_frame_t]  Actuator commands
  [0xFF]                                   End of tick
```

---

## 6. Model Organisation

```
src/svf/models/
├── aocs/       reaction_wheel, magnetometer, magnetorquer, gyroscope,
│               star_tracker, css, bdot_controller, thruster, gps
├── dynamics/   kde_equipment + fmu/DynamicsFmu
├── eps/        pcdu + fmu/{EpsFmu,BatteryFmu,SolarArrayFmu,PcduFmu}
├── dhs/        obc, obc_stub, obc_emulator
├── ttc/        ttc, sbt
└── thermal/    thermal
```

---

## 7. Tick Sources

| Tick Source | Behaviour | Use Case |
|---|---|---|
| `SoftwareTickSource` | Fast as possible | CI, Monte Carlo |
| `RealtimeTickSource` | Wall-clock aligned | YAMCS demos, HIL |

Variable timestep: `Equipment.suggested_dt()` → `SimulationMaster` uses minimum.

---

## 8. Hardware Profile System

```
srdb/data/hardware/
├── rw_default.yaml / rw_sinclair_rw003.yaml
├── mtq_default.yaml
├── mag_default.yaml / gyro_default.yaml
├── thr_default.yaml / thr_moog_monarc_1.yaml
├── gps_default.yaml / gps_novatel_oem7.yaml
└── thermal_default.yaml
```

---

## 9. Milestones

| Milestone | Status |
|---|---|
| M1–M12 — Core platform | ✅ |
| M13 — SIL Attitude Loop | ✅ |
| M14 — Real-Time & HIL | ✅ |
| M15 — SpW + CAN | ✅ |
| M16 — SRDB Maturity | ✅ |
| M17 — Equipment Configurability | ✅ |
| M18 — Architecture Refactor | ✅ |
| M19 — Spacecraft Configuration DSL | ✅ |
| M20 — Test Procedure API | 🔄 |
| M21 — Mission Results Reporting | 📋 |
| M22 — OBSW Integration Guide | 📋 |