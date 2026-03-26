# SVF Architecture

> **Status:** Draft — v0.8
> **Last updated:** 2026-03
> **Author:** lipofefeyt

---

## 1. Overview

The Software Validation Facility (SVF) is an open-core platform for the validation of spacecraft software and systems. It provides a simulation infrastructure, a communication bus, a spacecraft reference database, a component modelling framework, bus protocol adapters, PUS TM/TC support, and a test orchestration layer — designed to be standards-based, modular, and incrementally scalable.

---

## 2. Design Principles

**Standards at the boundaries.** Every integration point uses an open standard.

**Python orchestrates, C executes.** Python handles test logic, campaign management, and orchestration. C handles simulation model internals where timing and throughput matter.

**Equipment as the universal model abstraction.** Every spacecraft model — FMU, native Python, bus adapter, or future hardware — is an Equipment. Equipment extends ModelAdapter so every model is directly driveable by SimulationMaster. No parallel patterns.

**Interface-typed ports.** Equipment ports carry an interface type (FLOAT, MIL1553_BC, MIL1553_RT, SpaceWire, CAN, UART, ANALOG, DIGITAL). The WiringLoader validates type compatibility — you cannot wire a 1553 BC port to a SpaceWire node. This mirrors how spacecraft ICDs define interfaces before wiring is specified.

**Bus as Equipment.** Every bus adapter (1553, SpW, CAN) extends Bus which extends Equipment. Buses have typed ports on both sides and built-in fault injection for FDIR testing. SimulationMaster drives buses the same way it drives any other Equipment — no special cases.

**TM and TC are architecturally separate.** ParameterStore holds telemetry outputs. CommandStore holds telecommands. These are never conflated.

**One data one source.** Every parameter has exactly one authoritative definition in the SRDB.

**Requirements traceability from day one.** Every test references a requirement. Every BASELINED requirement has a test. The traceability matrix is generated automatically after every CI run.

**PUS as the commanding language.** All ground-to-spacecraft commanding flows through PUS-C packet structures (ECSS-E-ST-70-41C). The OBC model acts as PUS TC router — it doesn't know about specific equipment parameters, only PUS service/subservice routing.

---

## 3. Layered Architecture

```
+------------------------------------------------------------------+
|                    GROUND SEGMENT (M10)                          |
|          YAMCS  |  SCOS-2000  |  custom ground tools             |
|          XTCE export  |  MIB import                              |
+------------------------------+-----------------------------------+
                               |  PUS TC/TM packets
+------------------------------v-----------------------------------+
|                    TTC EQUIPMENT (M7)                            |
|          Simulated RF link — forwards TC bytes to OBC            |
|          Exposes TM for observable assertions                    |
+------------------------------+-----------------------------------+
                               |  raw PUS bytes
+------------------------------v-----------------------------------+
|                    OBC EQUIPMENT (M7)                            |
|          PusTcParser — unmarshalls TC packets                    |
|          Routes commands to equipment via bus interface          |
|          PUS S1 acknowledgement generation                       |
|          PUS S3 HK aggregation (essential HK at boot)            |
|          PUS S17 are-you-alive response                          |
+------------------------------+-----------------------------------+
                               |  typed bus ports
+------------------------------v-----------------------------------+
|                    BUS ADAPTERS                                  |
|                                                                  |
|  Mil1553Bus (M6)          SpaceWireBus (M10)   CanBus (M10)     |
|  ├── bc_in (MIL1553_BC)   Router + RMAP        ECSS CAN         |
|  ├── rt1_out (MIL1553_RT)                                        |
|  ├── ...                  Fault injection on all bus types       |
|  └── rt30_out                                                    |
|                                                                  |
|  BusFault: NO_RESPONSE | LATE_RESPONSE | BAD_PARITY |            |
|            WRONG_WORD_COUNT | BUS_ERROR                         |
|  Injectable via CommandStore: bus.{id}.fault.{target}.{type}    |
+------------------------------+-----------------------------------+
                               |
+------------------------------v-----------------------------------+
|                 EQUIPMENT & PORT LAYER                           |
|                                                                  |
|  Equipment (extends ModelAdapter)                                |
|    ports: typed IN/OUT (InterfaceType)                           |
|    on_tick(): CommandStore -> do_step() -> ParameterStore        |
|                                                                  |
|  FmuEquipment        NativeEquipment       Bus (abstract)        |
|  FMI 3.0 FMU         Python step_fn        fault injection       |
|  + parameter_map     + port declarations   + typed ports         |
+------+-------+------+--------------------------------------------+
       |       |
+------v--+ +--v--------------------------------------------------+
|PARAMETER| | COMMAND STORE                                       |
|STORE    | |                                                     |
| TM only | | TC only — take() atomic                            |
|         | | written by: inject(), schedule, wiring, bus        |
| svf.    | | consumed by: Equipment.on_tick() per IN port       |
| sim_time| |                                                     |
+---------+ +-----------------------------------------------------+
       |              |
+------v--------------v-------------------------------------------+
|              SPACECRAFT REFERENCE DATABASE (SRDB)               |
|                                                                  |
|  ParameterDefinition: name, unit, dtype, valid_range            |
|  classification (TM/TC), domain, model_id                       |
|  pus: {apid, service, subservice, parameter_id}                 |
|                                                                  |
|  Domain baselines: EPS | AOCS | TTC | OBDH | Thermal            |
|  Mission overrides: srdb/missions/{mission}.yaml                |
|  Equipment wiring:  srdb/wiring/{system}_wiring.yaml            |
+------+----------------------------------------------------------+
       |
+------v----------------------------------------------------------+
|              PUS TM/TC LAYER (M7)                               |
|                                                                  |
|  PusTcPacket / PusTcParser / PusTcBuilder                       |
|  PusTmPacket / PusTmParser / PusTmBuilder                       |
|  CRC-16/CCITT                                                   |
|                                                                  |
|  Services:                                                       |
|  S1  Request Verification (acceptance, execution, completion)   |
|  S3  Housekeeping (TC(3,1) define, TC(3,5) enable, TM(3,25))   |
|  S5  Event Reporting                                            |
|  S17 Test (are-you-alive TC(17,1) / TM(17,2))                  |
|  S20 Parameter Management (TC(20,1) set, TC(20,3) get)          |
+------+----------------------------------------------------------+
       |
+------v----------------------------------------------------------+
|              COMMUNICATION BUS (Cyclone DDS)                    |
|   SVF/Sim/Tick  |  SVF/Sim/Ready/{id}                          |
+------+----------------------------------------------------------+
       |
+------v----------------------------------------------------------+
|              CAMPAIGN MANAGER & REPORTING                       |
|  svf run campaigns/eps_validation.yaml                          |
|  JUnit XML + ECSS metadata | HTML report | traceability matrix  |
+------------------------------------------------------------------+
```

---

## 4. Interface-Typed Port System

### 4.1 InterfaceType Enum

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

WiringLoader validates interface type compatibility before any simulation runs:

```yaml
connections:
  - from: obc.m1553_bc_out       # MIL1553_BC
    to:   platform_bus.bc_in     # MIL1553_BC ✓ match
  - from: platform_bus.rt5_out   # MIL1553_RT
    to:   rw1.m1553_rt_in        # MIL1553_RT ✓ match
  - from: obc.spw_out            # SPACEWIRE
    to:   platform_bus.bc_in     # MIL1553_BC ✗ WiringLoadError
```

---

## 5. Bus Protocol Architecture

### 5.1 Bus Class Hierarchy

```
Equipment (ABC)
    └── Bus (ABC)
            ├── Mil1553Bus      — MIL-STD-1553B with BC/RT model
            ├── SpaceWireBus    — SpW router + RMAP (M10)
            └── CanBus          — ECSS CAN (M10)
```

### 5.2 MIL-STD-1553 Topology

```
OBC (BC)
  └── m1553_bc_out (MIL1553_BC)
          ↓
  Mil1553Bus
    ├── bc_in (MIL1553_BC)
    ├── rt1_out (MIL1553_RT) → Equipment RT1
    ├── rt2_out (MIL1553_RT) → Equipment RT2
    └── rtN_out (MIL1553_RT) → Equipment RTN
```

Subaddress mapping in wiring YAML:
```yaml
  - from: platform_bus.rt5_out
    to:   rw1.m1553_rt_in
    interface: MIL1553_RT
    rt_address: 5
    subaddress_map:
      - sa: 1
        parameter: aocs.rw1.torque_cmd   # BC_to_RT
      - sa: 2
        parameter: aocs.rw1.speed        # RT_to_BC
```

### 5.3 Fault Injection

```python
# Inject via Bus object
bus.inject_fault(BusFault(
    fault_type=FaultType.NO_RESPONSE,
    target="rt5",
    duration_s=5.0,     # 0.0 = permanent
    injected_at=t,
))

# Inject via CommandStore (svf_command_schedule compatible)
cmd_store.inject("bus.platform_1553.fault.rt5.no_response", value=5.0)
```

Fault types: `NO_RESPONSE`, `LATE_RESPONSE`, `BAD_PARITY`, `WRONG_WORD_COUNT`, `BUS_ERROR`

BUS_ERROR triggers automatic dual-bus switchover (A→B).

### 5.4 FDIR Test Pattern

```python
@pytest.mark.svf_command_schedule([
    (10.0, "bus.platform_1553.fault.rt5.no_response", 3.0),
])
@pytest.mark.requirement("FDIR-001")
def test_obc_detects_rw_timeout(svf_session) -> None:
    """OBC detects RT5 no-response and flags FDIR within 3 frames."""
    svf_session.observe("obc.fdir.rt5_fault").exceeds(0.5).within(5.0)
    svf_session.stop()
```

---

## 6. PUS TM/TC Architecture

### 6.1 Packet Structure

```
PUS-C TC Packet:
  [Primary Header 6B][Data Field Header 5B][App Data][CRC-16 2B]

  Primary Header:
    version(3) | type=1(1) | dfh=1(1) | APID(11) |
    seq_flags(2) | seq_count(14) | data_length(16)

  Data Field Header:
    ccsds_sflag(1) | pus_version=2(3) | ack_flags(4) |
    service(8) | subservice(8) | source_id(16)

PUS-C TM Packet:
  [Primary Header 6B][Data Field Header 10B][App Data][CRC-16 2B]

  Data Field Header:
    ccsds_sflag(1) | pus_version=2(3) | sc_time_ref(4) |
    service(8) | subservice(8) | msg_counter(16) |
    destination_id(16) | timestamp(32)
```

### 6.2 Service Catalogue (M7)

| Service | Description | Key TC | Key TM |
|---|---|---|---|
| S1 | Request Verification | — | TM(1,1) acceptance, TM(1,7) completion |
| S3 | Housekeeping | TC(3,1) define, TC(3,5) enable | TM(3,25) HK report |
| S5 | Event Reporting | — | TM(5,1-4) event |
| S17 | Test | TC(17,1) are-you-alive | TM(17,2) response |
| S20 | Parameter Management | TC(20,1) set, TC(20,3) get | TM(20,4) value report |

### 6.3 Commanding Chain (M7 target)

```
Test procedure
    ↓ PusTcBuilder.build(PusTcPacket(apid=0x101, service=20,
                          subservice=1, app_data=pack(param_id, value)))
TTC Equipment
    ↓ forwards raw TC bytes to OBC
OBC Equipment
    ↓ PusTcParser.parse() → PusTcPacket
    ↓ routes S20/1 → extract param_id, value
    ↓ CommandStore.inject(canonical_name, value)
1553 Bus
    ↓ BC_to_RT subaddress routing
Equipment RT
    ↓ receives command via on_tick() CommandStore read
    ↓ do_step() applies it
OBC Equipment
    ↓ PusTmBuilder.build(TM(1,7)) → S1 completion
    ↓ PusTmBuilder.build(TM(3,25)) → S3 HK report
```

---

## 7. Equipment Wiring

### 7.1 Connection Types

| Connection | Source type | Destination type | Used for |
|---|---|---|---|
| FLOAT→FLOAT | any OUT | any IN | model-to-model data |
| MIL1553_BC→MIL1553_BC | OBC bc_out | Bus bc_in | OBC to 1553 bus |
| MIL1553_RT→MIL1553_RT | Bus rtN_out | Equipment rt_in | 1553 bus to equipment |

### 7.2 Wiring YAML Schema

```yaml
connections:
  - from: {equipment_id}.{port_name}
    to:   {equipment_id}.{port_name}
    description: optional human-readable description
    # For 1553 RT connections only:
    rt_address: 5
    subaddress_map:
      - sa: 1
        parameter: aocs.rw1.torque_cmd
```

---

## 8. Simulation Execution Model

### 8.1 Tick-Based Lockstep

```
Master
  ├── write svf.sim_time to ParameterStore
  ├── tick all Equipment (includes Bus adapters)
  │     each Equipment.on_tick():
  │       CommandStore.take() → IN ports
  │       do_step()
  │       ParameterStore.write() ← OUT ports
  │       publish_ready()
  ├── wait for all ready signals
  ├── apply wiring (copy OUT→IN via CommandStore)
  └── scheduler fires svf_command_schedule commands
```

### 8.2 TM/TC Separation

| Store | Direction | Written by | Read by |
|---|---|---|---|
| ParameterStore | TM | Equipment OUT ports, SimulationMaster | Observables, bus RT_to_BC routing, OBC HK aggregation |
| CommandStore | TC | inject(), schedule, wiring, bus BC_to_RT | Equipment IN ports |

---

## 9. pytest Plugin

### 9.1 Marks Reference

| Mark | Default | Description |
|---|---|---|
| `svf_fmus([FmuConfig(...)])` | SimpleCounter.fmu | FMU list with parameter_map |
| `svf_dt(float)` | 0.1 | Timestep in seconds |
| `svf_stop_time(float)` | 2.0 | Stop time in seconds |
| `svf_initial_commands([(name, value)])` | [] | Pre-simulation commands |
| `svf_command_schedule([(t, name, value)])` | [] | Scheduled commands at sim time t |
| `requirement(*ids)` | — | Requirement IDs verified |

### 9.2 Observable API

```python
svf_session.observe("eps.battery.soc").exceeds(0.88).within(120.0)
svf_session.observe("eps.battery.soc").drops_below(0.75).within(120.0)
svf_session.observe("aocs.rw1.speed").reaches(500.0).within(30.0)
svf_session.observe("obc.fdir.rt5_fault").satisfies(lambda v: v > 0.5).within(5.0)
```

---

## 10. Reference Models

### 10.1 EPS Models

**Integrated EPS FMU** — single FMU for rapid validation:

| Parameter | Direction | Unit |
|---|---|---|
| eps.solar_array.illumination | IN (TC) | — |
| eps.load.power | IN (TC) | W |
| eps.battery.soc | OUT (TM) | — |
| eps.battery.voltage | OUT (TM) | V |
| eps.bus.voltage | OUT (TM) | V |
| eps.solar_array.generated_power | OUT (TM) | W |
| eps.battery.charge_current | OUT (TM) | A |

**Decomposed EPS** — SolarArray + Battery + PCDU via `srdb/wiring/eps_wiring.yaml`

### 10.2 1553 Bus Demo (M6)

```
Mil1553Bus "platform_1553"
  ├── RT5: ReactionWheel (rw1)
  │     SA1: aocs.rw1.torque_cmd (BC_to_RT)
  │     SA2: aocs.rw1.speed      (RT_to_BC)
  └── [future: OBC as BC — M7]
```

Test procedures: TC-1553-001 through TC-1553-005 — all PASS.

---

## 11. Test Structure

```
tests/
├── unit/           SVF platform classes in isolation (SVF-DEV-xxx)
│   └── pus/        PUS TC/TM packet tests (PUS-xxx)
├── equipment/      Equipment contract + bus tests (EQP-xxx, 1553-xxx)
├── integration/    SVF infrastructure mechanics
└── spacecraft/     Model behaviour (EPS-xxx, TC-1553-xxx)
```

---

## 12. Technology Stack

| Concern | Choice |
|---|---|
| Simulation standard | FMI 3.0 |
| Model abstraction | Equipment (extends ModelAdapter) |
| Port typing | InterfaceType enum — compile-time interface safety |
| Bus protocols | Bus extends Equipment — unified driving model |
| Fault injection | BusFault via CommandStore — svf_command_schedule compatible |
| PUS TM/TC | ECSS-E-ST-70-41C, CRC-16/CCITT |
| Communication bus | Eclipse Cyclone DDS |
| Parameter database | SRDB (YAML + Python) |
| Test runner | pytest + SVF plugin |
| Traceability | @pytest.mark.requirement() + auto-generated matrix |
| Packaging | pyproject.toml |

---

## 13. Development Milestones

| Milestone | Objective | Status |
|---|---|---|
| M1 - Simulation Master | fmpy, CSV, CI | ✅ DONE |
| M2 - Simulation Bus & Abstractions | TickSource, SyncProtocol, DDS | ✅ DONE |
| M3 - pytest Plugin | svf_session, observable, verdict | ✅ DONE |
| M3.5 - SRDB | Parameter definitions, PUS mappings | ✅ DONE |
| M3.6 - Requirements Engineering | EQP/EPS requirements, traceability | ✅ DONE |
| M4 - First Real Model | Integrated EPS FMU | ✅ DONE |
| M4.5 - Model Wiring | Equipment ABC, WiringMap, decomposed EPS | ✅ DONE |
| M5 - Campaign & Reporting | YAML campaigns, HTML report, JUnit XML | ✅ DONE |
| M6 - Bus Protocols | InterfaceType, Bus ABC, 1553 adapter, fault injection | ✅ DONE |
| M7 - PUS TM/TC | TC/TM packets, S1/3/5/17/20, OBC model, TTC model | IN PROGRESS |
| M8 - ICD Integration | ICD parser, wiring YAML generator | PENDING |
| M9 - Real-Time & HIL | RT_PREEMPT, HIL adapter | PENDING |
| M10 - Ground Segment | CCSDS/PUS adapter, YAMCS, XTCE, MIB | PENDING |

---

## 14. Out of Scope (current)

- Real-time / HIL execution (M9)
- ICD parser (M8)
- SMP2 model import (M8)
- SpaceWire and CAN bus adapters (M10)
- CCSDS packet stream adapter (M10)
- DOORS NG / Jama Connect integration (M10)
- Tool qualification (DO-178C, ECSS-E-ST-40C)
- Multi-node distributed simulation
- SharedMemorySyncProtocol (M9)
- RealtimeTickSource (M9)
- ParameterStoreDdsBridge (M10)
- SRDB calibration curves
- XTCE export / MIB import (M10)
- SSP file support (M8)