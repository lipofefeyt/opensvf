# SVF Architecture

> **Status:** v1.2
> **Last updated:** 2026-04
> **Author:** lipofefeyt

---

## 1. Overview

The Software Validation Facility (SVF) is an open-core platform for the validation of spacecraft software and systems. It connects three independent projects into a single closed-loop simulation:

- **opensvf** — Python orchestration layer (this repo)
- **opensvf-kde** — C++ 6-DOF physics engine, compiled to FMI 2.0 FMU
- **openobsw** — C11 OBSW: PUS services, b-dot, FDIR, validated on MSP430

From ECSS-E-TM-10-21A:

> *System modelling and simulation is a support activity to OBSW validation. The ability to inject failures in the models enables the user to trigger the OBSW monitoring processes as well as to exercise the FDIR mechanisms.*

---

## 2. The Three-Project Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│  opensvf-kde (C++ / Eigen3)         openobsw (C11 / bare metal)     │
│  6-DOF physics engine               Real OBSW binary                │
│  Euler's equations                  b-dot algorithm                 │
│  Quaternion kinematics              PUS S1/3/5/8/17/20              │
│  Earth B-field model                FDIR state machine              │
│         │                                    │                      │
│         │  true ω, B  (FMI 2.0)             │  TC/TM (pipe proto)  │
│         ▼                                    ▼                      │
│              opensvf (Python / pytest)                              │
│              SVF tick loop (DDS lockstep)                           │
│              Sensor models: MAG, GYRO, ST, CSS                      │
│              Actuator models: MTQ, RW, PCDU                         │
│              OBC: stub | emulator                                   │
│              PUS commanding chain (ECSS-E-ST-70-41C)                │
│              Campaign manager + ECSS-compatible reports             │
└─────────────────────────────────────────────────────────────────────┘
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

**FMI 2.0 as the physics boundary.**
The KDE C++ engine is wrapped as an FMI 2.0 Co-Simulation FMU. The Python SVF is the FMI master. One SVF tick = one FMU `doStep()`.

**SRDB as the shared parameter contract.**
Every parameter has one canonical name. The openobsw SRDB pip package makes this contract explicit across OBSW and SVF.

**Wiring as the composition layer.**
`WiringLoader` validates port types and injects values via `CommandStore` each tick. The wiring YAML defines the closed loop — no code changes needed to rewire.

---

## 4. Layered Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                  GROUND SEGMENT (M12)                        │
│        YAMCS | SCOS-2000 | XTCE | MIB                       │
└──────────────────────────┬───────────────────────────────────┘
                           │ PUS TC/TM
┌──────────────────────────▼───────────────────────────────────┐
│                  TTC EQUIPMENT                               │
│  ObcInterface: ObcEquipment | ObcStub | OBCEmulatorAdapter   │
└──────────────────────────┬───────────────────────────────────┘
                           │ 1553 BC / pipe
┌──────────────────────────▼───────────────────────────────────┐
│              BUS ADAPTERS + ACTUATORS                        │
│  Mil1553Bus (fault injection) | MTQ | RW | PCDU              │
└──────────────────────────┬───────────────────────────────────┘
                           │ torques → KDE IN ports
┌──────────────────────────▼───────────────────────────────────┐
│              KDE FMU (C++ physics)                           │
│  6-DOF Euler integration + quaternion kinematics             │
│  Earth B-field model (simplified dipole)                     │
│  OUT: true ω (rad/s) | true B (T) | true q (quaternion)      │
└──────────────────────────┬───────────────────────────────────┘
                           │ true state → sensor truth ports
┌──────────────────────────▼───────────────────────────────────┐
│              SENSOR MODELS                                   │
│  MAG: true B + noise + bias drift                            │
│  GYRO: true ω + ARW noise + bias                             │
│  CSS: sun vector + eclipse detection                         │
│  ST: quaternion propagation + blinding                       │
└──────────────────────────┬───────────────────────────────────┘
                           │ noisy measurements → OBSW
┌──────────────────────────▼───────────────────────────────────┐
│         PARAMETER STORE (TM) │ COMMAND STORE (TC)            │
│         SRDB canonical names │ WiringMap connections         │
└──────────────────────────┬───────────────────────────────────┘
                           │
┌──────────────────────────▼───────────────────────────────────┐
│         SIMULATION MASTER (DDS lockstep)                     │
│         pytest + SVF plugin + campaigns + reports            │
└──────────────────────────────────────────────────────────────┘
```

---

## 5. KDE Equipment — Physics Bridge

`make_kde_equipment()` wraps `DynamicsFmu` as a `NativeEquipment` with SRDB-canonical port names.

### Ports

| Port | Direction | Unit | Description |
|---|---|---|---|
| `aocs.mtq.torque_x/y/z` | IN | Nm | Mechanical torques from MTQ model |
| `aocs.truth.rate_x/y/z` | OUT | rad/s | True angular velocity (→ GYRO) |
| `aocs.mag.true_x/y/z` | OUT | T | True magnetic field (→ MAG) |
| `aocs.attitude.quaternion_w/x/y/z` | OUT | — | True attitude quaternion (→ ST) |

### FMU wire protocol

```
SVF tick → kde.do_step(t, dt):
  1. Read aocs.mtq.torque_x/y/z from ports
  2. fmu.setReal([tq_mtq_x, tq_mtq_y, tq_mtq_z], torques)
  3. fmu.doStep(currentCommunicationPoint=t, communicationStepSize=dt)
  4. q = fmu.getReal([q_w, q_x, q_y, q_z])
  5. ω = fmu.getReal([omega_x, omega_y, omega_z])
  6. B = fmu.getReal([b_field_x, b_field_y, b_field_z])
  7. Write to ParameterStore via OUT ports
```

---

## 6. Closed-Loop Wiring

`srdb/wiring/kde_wiring.yaml` defines the full detumbling loop:

```
KDE.aocs.truth.rate_x/y/z  → GYRO.aocs.truth.rate_x/y/z
KDE.aocs.mag.true_x/y/z    → MAG.aocs.mag.true_x/y/z
MAG.aocs.mag.field_x/y/z   → bdot.aocs.mag.field_x/y/z
MAG.aocs.mag.field_x/y/z   → MTQ.aocs.mtq.b_field_x/y/z
bdot.aocs.mtq.dipole_x/y/z → MTQ.aocs.mtq.dipole_x/y/z
MTQ.aocs.mtq.torque_x/y/z  → KDE.aocs.mtq.torque_x/y/z  ← loop closed
```

All wiring is validated by `WiringLoader` at load time — mismatched port directions or unknown equipment IDs raise `WiringLoadError` before simulation starts.

---

## 7. OBC Implementation Options

| Implementation | Use case |
|---|---|
| `ObcEquipment` | Unit and integration testing without OBSW |
| `ObcStub` | Closed-loop Level 3/4 testing with rule-based OBSW behaviour |
| `OBCEmulatorAdapter` | Real OBSW binary under test via binary pipe |

### ObcInterface Protocol

```python
@runtime_checkable
class ObcInterface(Protocol):
    def receive_tc(self, raw_tc: bytes, t: float = 0.0) -> list[PusTmPacket]: ...
    def get_tm_queue(self) -> list[PusTmPacket]: ...
    def get_tm_by_service(self, service: int, subservice: int) -> list[PusTmPacket]: ...
```

### OBCEmulatorAdapter wire protocol

```
SVF → obsw_sim stdin:  [uint16 BE length][TC frame bytes]
obsw_sim → SVF stdout: [uint16 BE length][TM packet bytes] ... [0xFF sync]
```

S5 events drive mode state: `event_id=0x0002` → SAFE, `event_id=0x0003` → NOMINAL.

---

## 8. Four Validation Levels

```
Level 1 — Model Validation (M8/M9)
  Each equipment verified in isolation
  Nominal + failure test procedures per model
  Status: complete

Level 2 — Interface Validation (M6/M9)
  1553 bus interfaces + full fault matrix
  Status: complete

Level 3 — Integration Validation (M10)
  Models + PUS chain + closed-loop FDIR scenarios
  OBC stub drives all transitions
  Status: complete

Level 4 — System Validation (M11/M11.5)
  Real OBSW binary under test (OBCEmulatorAdapter)
  Real C++ physics engine (opensvf-kde FMU)
  Full closed-loop co-simulation
  Status: complete
```

---

## 9. Reference Equipment Library

| Equipment | Subsystem | Key Physics | Status |
|---|---|---|---|
| `make_kde_equipment()` | Dynamics | 6-DOF physics, B-field | M11.5 |
| `ObcEquipment` | DHS | Mode FSM, OBT, watchdog, PUS routing | M7/M8 |
| `ObcStub` | DHS | Rule engine, closed-loop FDIR | M10 |
| `OBCEmulatorAdapter` | DHS | Real OBSW via binary pipe | M11 |
| `TtcEquipment` | TTC | TC/TM byte pipe | M7 |
| `make_reaction_wheel()` | AOCS | Torque, friction, temperature | M6/M8 |
| `make_star_tracker()` | AOCS | Quaternion, noise, sun blinding | M8 |
| `make_magnetometer()` | AOCS | B-field measurement + noise | M11.5 |
| `make_magnetorquer()` | AOCS | Torque = m × B | M11.5 |
| `make_gyroscope()` | AOCS | Rate measurement + ARW noise | M11.5 |
| `make_css()` | AOCS | Sun vector + eclipse | M11.5 |
| `make_bdot_controller()` | AOCS | m = −k·Ḃ detumbling | M11.5 |
| `make_sbt()` | TTC | Carrier lock, mode FSM | M8 |
| `make_pcdu()` | EPS | LCL switching, MPPT, UVLO | M9 |
| `EpsFmu` | EPS | Solar array, Li-Ion battery | M4 |

---

## 10. Milestones

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
| M12 — Ground Segment (YAMCS, SpW, CAN) | Planned |