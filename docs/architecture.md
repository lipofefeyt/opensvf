# SVF Architecture

> **Status:** v0.9
> **Last updated:** 2026-03
> **Author:** lipofefeyt

---

## 1. Overview

The Software Validation Facility (SVF) is an open-core platform for the validation of spacecraft software and systems. It provides a simulation infrastructure, a communication bus, a spacecraft reference database, a component modelling framework, bus protocol adapters, PUS TM/TC support, and a test orchestration layer — designed to be standards-based, modular, and incrementally scalable.

SVF is built around one core idea: **every spacecraft subsystem is an Equipment, every interface is typed, and every test is traced to a requirement.** From a single FMU to a full PUS commanding chain, the same abstractions apply.

---

## 2. Design Principles

**Equipment as the universal model abstraction.**
Every spacecraft model — FMU, native Python, bus adapter, OBC, TTC — is an `Equipment`. Equipment extends `ModelAdapter` so every model is directly driveable by `SimulationMaster`. No parallel patterns, no special cases.

**Interface-typed ports.**
Equipment ports carry an `InterfaceType` (FLOAT, MIL1553_BC, MIL1553_RT, SpaceWire, CAN, UART, ANALOG, DIGITAL). The `WiringLoader` validates type compatibility — you cannot wire a 1553 BC port to a SpaceWire node. This mirrors how spacecraft ICDs define interfaces before wiring is specified.

**Bus as Equipment.**
Every bus adapter (1553, SpW, CAN) extends `Bus` which extends `Equipment`. Buses have typed ports on both sides and built-in fault injection for FDIR testing. `SimulationMaster` drives buses the same way it drives any other Equipment.

**TM and TC are architecturally separate.**
`ParameterStore` holds telemetry outputs (TM). `CommandStore` holds telecommands (TC). These are never conflated, mirroring the fundamental TM/TC separation in real spacecraft architecture.

**One data one source.**
Every parameter has exactly one authoritative definition in the SRDB, shared across all engineering disciplines — simulation models, test procedures, reporters, and ground segment tools.

**PUS as the commanding language.**
All ground-to-spacecraft commanding flows through PUS-C packet structures (ECSS-E-ST-70-41C). The OBC model is a PUS TC router — it doesn't know about specific equipment parameters, only PUS service/subservice routing and parameter_id → canonical name mapping.

**Requirements traceability from day one.**
Every test references a requirement via `@pytest.mark.requirement()`. Every BASELINED requirement has a test. The traceability matrix is generated automatically after every CI run.

**CI/CD compatibility.**
All outputs — JUnit XML, HTML report, traceability matrix — are consumable by standard CI/CD pipelines.

---

## 3. Layered Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    GROUND SEGMENT (M10)                         │
│         YAMCS | SCOS-2000 | XTCE export | MIB import            │
└──────────────────────────┬──────────────────────────────────────┘
                           │ PUS TC/TM bytes
┌──────────────────────────▼──────────────────────────────────────┐
│                    TTC EQUIPMENT                                 │
│  send_tc(PusTcPacket) → forwards to OBC                         │
│  get_tm_responses() ← exposes TM for observable assertions      │
└──────────────────────────┬──────────────────────────────────────┘
                           │ raw PUS bytes
┌──────────────────────────▼──────────────────────────────────────┐
│                    OBC EQUIPMENT                                 │
│  PusTcParser → route by service/subservice                      │
│  S17: TM(17,2) are-you-alive response                           │
│  S20/1: CommandStore.inject(canonical_name, value)              │
│  S20/3: ParameterStore.read() → TM(20,4)                        │
│  S3: TM(3,25) HK reports (essential HK auto-enabled at boot)    │
│  S1: TM(1,1) acceptance + TM(1,7) completion for all TCs        │
│  S1: TM(1,2) rejection on CRC error                             │
└──────────────────────────┬──────────────────────────────────────┘
                           │ typed bus ports
┌──────────────────────────▼──────────────────────────────────────┐
│                    BUS ADAPTERS                                  │
│                                                                  │
│  Mil1553Bus                    SpaceWireBus (M10)   CanBus (M10) │
│  ├── bc_in  (MIL1553_BC)       Router + RMAP        ECSS CAN    │
│  ├── rt1_out (MIL1553_RT)                                        │
│  └── rtN_out (MIL1553_RT)                                        │
│                                                                  │
│  Fault injection (all bus types):                                │
│  NO_RESPONSE | LATE_RESPONSE | BAD_PARITY |                      │
│  WRONG_WORD_COUNT | BUS_ERROR                                    │
│  bus.{id}.fault.{target}.{type} via CommandStore                 │
└──────────────────────────┬──────────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────────┐
│                 EQUIPMENT & PORT LAYER                           │
│                                                                  │
│  Equipment (extends ModelAdapter)                                │
│    ports: typed IN/OUT (InterfaceType)                           │
│    on_tick():                                                    │
│      1. CommandStore.take() → receive() for each IN port         │
│      2. do_step()  ← subclass implements physics                 │
│      3. ParameterStore.write() for each OUT port                 │
│      4. SyncProtocol.publish_ready()                             │
│                                                                  │
│  FmuEquipment        NativeEquipment       Bus (abstract)        │
│  FMI 3.0 FMU         Python step_fn        fault injection       │
│  + parameter_map     + port declarations   + typed ports         │
└──────┬──────────────────────┬───────────────────────────────────┘
       │                      │
┌──────▼──────┐  ┌────────────▼──────────────────────────────────┐
│  PARAMETER  │  │  COMMAND STORE                                 │
│  STORE      │  │                                                │
│  TM only    │  │  TC only — take() atomic read+consume          │
│  SRDB keys  │  │  written by: inject(), schedule, wiring,       │
│  svf.sim_   │  │             OBC S20 routing, bus BC_to_RT      │
│  time       │  │  consumed by: Equipment.on_tick() per IN port  │
└──────┬──────┘  └────────────────────────────────────────────────┘
       │
┌──────▼──────────────────────────────────────────────────────────┐
│              SPACECRAFT REFERENCE DATABASE (SRDB)               │
│                                                                  │
│  ParameterDefinition:                                            │
│    name (canonical), unit, dtype, valid_range                   │
│    classification (TM/TC), domain, model_id                     │
│    pus: {apid, service, subservice, parameter_id}               │
│                                                                  │
│  Domain baselines: EPS | AOCS | TTC | OBDH | Thermal            │
│  Mission overrides: srdb/missions/{mission}.yaml                │
│  Equipment wiring:  srdb/wiring/{system}_wiring.yaml            │
│  Runtime validation: range warnings, TM/TC separation warnings  │
└──────┬──────────────────────────────────────────────────────────┘
       │
┌──────▼──────────────────────────────────────────────────────────┐
│              PUS TM/TC LAYER                                    │
│                                                                  │
│  PusTcPacket / PusTcParser / PusTcBuilder  (ECSS-E-ST-70-41C)  │
│  PusTmPacket / PusTmParser / PusTmBuilder                       │
│  CRC-16/CCITT                                                   │
│                                                                  │
│  Services implemented:                                           │
│  S1  Request Verification (TM(1,1) acceptance, TM(1,7) done)   │
│  S3  Housekeeping (TC(3,1) define, TC(3,5/6) en/disable,        │
│      TM(3,25) HK report, essential HK at boot)                  │
│  S5  Event Reporting (TM(5,1-4) by severity)                    │
│  S17 Test (TC(17,1) are-you-alive → TM(17,2))                  │
│  S20 Parameter Management (TC(20,1) set, TC(20,3) get)          │
└──────┬──────────────────────────────────────────────────────────┘
       │
┌──────▼──────────────────────────────────────────────────────────┐
│              COMMUNICATION BUS (Cyclone DDS)                    │
│  SVF/Sim/Tick  |  SVF/Sim/Ready/{model_id}                      │
└──────┬──────────────────────────────────────────────────────────┘
       │
┌──────▼──────────────────────────────────────────────────────────┐
│              TEST ORCHESTRATION                                  │
│  pytest + SVF plugin                                            │
│  svf_session fixture | observables | svf_command_schedule       │
│  @pytest.mark.requirement() | traceability matrix               │
└──────┬──────────────────────────────────────────────────────────┘
       │
┌──────▼──────────────────────────────────────────────────────────┐
│              CAMPAIGN MANAGER & REPORTING                       │
│  svf run campaigns/eps_validation.yaml                          │
│  JUnit XML + ECSS metadata | HTML report | traceability matrix  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 4. Interface-Typed Port System

### 4.1 InterfaceType

```python
class InterfaceType(enum.Enum):
    FLOAT       = "float"        # Default — plain engineering value
    MIL1553_BC  = "mil1553_bc"   # MIL-STD-1553 Bus Controller
    MIL1553_RT  = "mil1553_rt"   # MIL-STD-1553 Remote Terminal
    SPACEWIRE   = "spacewire"    # SpaceWire node
    CAN         = "can"          # CAN node
    UART        = "uart"         # UART
    ANALOG      = "analog"       # Analog signal
    DIGITAL     = "digital"      # Digital signal
```

### 4.2 Wiring Validation

```yaml
connections:
  - from: obc.m1553_bc_out     # MIL1553_BC
    to:   platform_bus.bc_in   # MIL1553_BC ✓ compatible
  - from: obc.spw_out          # SPACEWIRE
    to:   platform_bus.bc_in   # MIL1553_BC ✗ WiringLoadError
```

---

## 5. Bus Protocol Architecture

### 5.1 Class Hierarchy

```
Equipment (ABC)
    └── Bus (ABC)
            ├── Mil1553Bus      — MIL-STD-1553B with BC/RT model (M6)
            ├── SpaceWireBus    — SpW router + RMAP (M10)
            └── CanBus          — ECSS CAN (M10)
```

### 5.2 MIL-STD-1553 Topology

```
OBC (future BC — M7 complete)
  └── 1553 bus bc_in (MIL1553_BC)
          ↓
  Mil1553Bus
    ├── rt5_out (MIL1553_RT) → ReactionWheel rw1
    │     SA1: aocs.rw1.torque_cmd  (BC_to_RT)
    │     SA2: aocs.rw1.speed       (RT_to_BC)
    └── rtN_out → future equipment
```

### 5.3 Fault Injection

```python
# Direct injection
bus.inject_fault(BusFault(
    fault_type=FaultType.NO_RESPONSE,
    target="rt5",
    duration_s=5.0,   # 0.0 = permanent
    injected_at=t,
))

# Via CommandStore (svf_command_schedule compatible)
@pytest.mark.svf_command_schedule([
    (10.0, "bus.platform_1553.fault.rt5.no_response", 5.0),
    (15.0, "bus.platform_1553.fault.rt5.clear", -1.0),
])
```

---

## 6. PUS TM/TC Architecture

### 6.1 Packet Structure (ECSS-E-ST-70-41C)

```
PUS-C TC: [Primary 6B][DFH 5B][App Data][CRC-16 2B]
  DFH: pus_version=2 | ack_flags | service | subservice | source_id

PUS-C TM: [Primary 6B][DFH 10B][App Data][CRC-16 2B]
  DFH: pus_version=2 | service | subservice | msg_counter |
       destination_id | timestamp(CUC)
```

### 6.2 Service Catalogue

| Service | TC | TM | Description |
|---|---|---|---|
| S1 | — | TM(1,1) TM(1,2) TM(1,7) TM(1,8) | Request Verification |
| S3 | TC(3,1) TC(3,5) TC(3,6) | TM(3,25) | Housekeeping |
| S5 | — | TM(5,1-4) | Event Reporting |
| S17 | TC(17,1) | TM(17,2) | Test / Are-You-Alive |
| S20 | TC(20,1) TC(20,3) | TM(20,4) | Parameter Management |

### 6.3 Commanding Chain

```
Test procedure / Ground
    ↓ PusTcPacket(service=20, subservice=1, app_data=pack(param_id, value))
TtcEquipment.send_tc()
    ↓ PusTcBuilder.build() → raw bytes
ObcEquipment.receive_tc()
    ↓ PusTcParser.parse() → validates CRC, extracts service/subservice
    ↓ S20/1: param_id → SRDB canonical name (via ObcConfig.param_id_map)
    ↓ CommandStore.inject(canonical_name, value, source_id="obc.s20.set")
Mil1553Bus.do_step()
    ↓ BC_to_RT: ParameterStore.read(canonical) → CommandStore.inject(canonical)
ReactionWheel.on_tick()
    ↓ CommandStore.take("aocs.rw1.torque_cmd")
    ↓ do_step(): integrate torque → speed
    ↓ ParameterStore.write("aocs.rw1.speed", new_speed)
ObcEquipment._generate_hk_reports()
    ↓ ParameterStore.read("aocs.rw1.speed")
    ↓ PusTmBuilder.build(TM(3,25)) → HK report
TtcEquipment.get_tm_responses(service=3, subservice=25)
```

---

## 7. Simulation Execution Model

### 7.1 Tick-Based Lockstep

```
SimulationMaster tick loop:
  1. Write svf.sim_time to ParameterStore
  2. For each Equipment (incl. Bus adapters, OBC, TTC):
       Equipment.on_tick(t, dt):
         CommandStore.take() → receive() for each IN port
         do_step()
         ParameterStore.write() for each OUT port
         SyncProtocol.publish_ready()
  3. Wait for all ready signals
  4. Apply WiringMap (OUT → IN via CommandStore)
  5. svf_command_schedule fires scheduled commands
```

### 7.2 TM/TC Stores

| Store | Direction | Written by | Read by |
|---|---|---|---|
| ParameterStore | TM | Equipment OUT ports, SimulationMaster | Observables, bus RT_to_BC, OBC HK |
| CommandStore | TC | inject(), schedule, wiring, OBC S20, bus BC_to_RT | Equipment IN ports |

---

## 8. pytest Plugin

### 8.1 Marks Reference

| Mark | Default | Description |
|---|---|---|
| `svf_fmus([FmuConfig(...)])` | SimpleCounter.fmu | FMU list with parameter_map |
| `svf_dt(float)` | 0.1 | Timestep in seconds |
| `svf_stop_time(float)` | 2.0 | Stop time in seconds |
| `svf_initial_commands([(name, value)])` | [] | Pre-simulation commands |
| `svf_command_schedule([(t, name, value)])` | [] | Commands at simulation time t |
| `requirement(*ids)` | — | Requirement IDs verified |

### 8.2 Observable API

```python
svf_session.observe("eps.battery.soc").exceeds(0.88).within(120.0)
svf_session.observe("aocs.rw1.speed").reaches(500.0).within(30.0)
svf_session.observe("bus.platform_1553.active_bus").satisfies(
    lambda v: v == 2.0  # bus B
).within(5.0)
```

---

## 9. Reference Models

### 9.1 EPS Models

**Integrated EPS FMU** — single FMU:

| Parameter | Direction | Unit |
|---|---|---|
| eps.solar_array.illumination | IN (TC) | — |
| eps.load.power | IN (TC) | W |
| eps.battery.soc | OUT (TM) | — |
| eps.battery.voltage | OUT (TM) | V |
| eps.bus.voltage | OUT (TM) | V |
| eps.solar_array.generated_power | OUT (TM) | W |
| eps.battery.charge_current | OUT (TM) | A |

**Decomposed EPS** — SolarArray + Battery + PCDU via `srdb/wiring/eps_wiring.yaml`.

### 9.2 AOCS Reaction Wheel

| Parameter | Direction | Unit | Bus |
|---|---|---|---|
| aocs.rw1.torque_cmd | IN (TC) | Nm | 1553 RT5 SA1 |
| aocs.rw1.speed | OUT (TM) | rpm | 1553 RT5 SA2 |
| aocs.rw1.status | OUT (TM) | — | — |

### 9.3 OBC / TTC

| Component | Purpose |
|---|---|
| ObcEquipment | PUS TC router — S1/3/5/17/20, essential HK at boot |
| TtcEquipment | Ground interface — send_tc(), get_tm_responses() |

---

## 10. Test Structure

```
tests/
├── unit/
│   ├── pus/        PUS TC/TM tests (PUS-xxx)
│   └── campaign/   Campaign loader/executor/reporter tests
│   test_*.py       SVF platform tests (SVF-DEV-xxx)
├── equipment/      Equipment contract + bus tests (EQP-xxx, 1553-xxx)
├── integration/    SVF infrastructure mechanics
└── spacecraft/     Model behaviour (EPS-xxx, TC-1553-xxx, TC-PUS-xxx)
```

Rule: every test has `@pytest.mark.requirement()`. No exceptions.

---

## 11. Technology Stack

| Concern | Choice |
|---|---|
| Simulation standard | FMI 3.0 |
| Model abstraction | Equipment (extends ModelAdapter) |
| Port typing | InterfaceType enum |
| Bus protocols | Bus extends Equipment |
| Fault injection | BusFault via CommandStore |
| PUS TM/TC | ECSS-E-ST-70-41C, CRC-16/CCITT |
| Communication bus | Eclipse Cyclone DDS |
| Parameter database | SRDB (YAML + Python) |
| Test runner | pytest + SVF plugin |
| Traceability | @pytest.mark.requirement() + auto matrix |
| Campaign manager | YAML + CLI (`svf run`) |
| Reporting | Self-contained HTML + JUnit XML |
| Packaging | pyproject.toml (Apache 2.0) |

---

## 12. Development Milestones

| Milestone | Objective | Status |
|---|---|---|
| M1 - Simulation Master | fmpy, CSV, CI | ✅ DONE |
| M2 - Simulation Bus | TickSource, SyncProtocol, DDS | ✅ DONE |
| M3 - pytest Plugin | svf_session, observables, verdicts | ✅ DONE |
| M3.5 - SRDB | Parameter definitions, PUS mappings | ✅ DONE |
| M3.6 - Requirements Engineering | Traceability, EQP/EPS requirements | ✅ DONE |
| M4 - First Real Model | Integrated EPS FMU | ✅ DONE |
| M4.5 - Model Wiring | Equipment ABC, WiringMap, decomposed EPS | ✅ DONE |
| M5 - Campaign & Reporting | YAML campaigns, HTML report, JUnit XML | ✅ DONE |
| M6 - Bus Protocols | InterfaceType, Bus ABC, 1553, fault injection | ✅ DONE |
| M7 - PUS TM/TC | TC/TM packets, S1/3/5/17/20, OBC, TTC | ✅ DONE |
| M8 - ICD Integration | ICD parser, wiring YAML generator | PENDING |
| M9 - Real-Time & HIL | RT_PREEMPT, HIL adapter | PENDING |
| M10 - Ground Segment | YAMCS, XTCE, MIB, SpW, CAN | PENDING |

---

## 13. Out of Scope (current)

- Real-time / HIL (M9)
- ICD parser (M8)
- SMP2 model import (M8)
- SpaceWire and CAN bus adapters (M10)
- CCSDS packet stream adapter (M10)
- DOORS NG / Jama Connect (M10)
- Tool qualification (DO-178C, ECSS-E-ST-40C)
- Multi-node distributed simulation
- SharedMemorySyncProtocol (M9)
- RealtimeTickSource (M9)
- ParameterStoreDdsBridge (M10)
- SRDB calibration curves
- XTCE export / MIB import (M10)
- SSP file support (M8)