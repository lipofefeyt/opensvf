# SVF Architecture

> **Status:** Draft — v0.7
> **Last updated:** 2026-03
> **Author:** lipofefeyt

---

## 1. Overview

The Software Validation Facility (SVF) is an open-core platform for the validation of spacecraft software and systems. It provides a simulation infrastructure, a communication bus, a spacecraft reference database, a component modelling framework, and a test orchestration layer — designed to be standards-based, modular, and incrementally scalable.

The initial target domain is aerospace (small satellites, NewSpace), with architecture choices made to allow later extension into adjacent regulated industries (automotive, rail, medical).

---

## 2. Design Principles

**Standards at the boundaries.** Every integration point between layers uses an open standard. This ensures model interoperability, avoids tool lock-in, and supports procurement in regulated environments.

**Python orchestrates, C executes.** Python handles test logic, campaign management, and orchestration. C handles simulation model internals where timing and throughput matter.

**Plugin-first design.** Every integration point is a plugin slot from day one.

**Dependency injection for real-time readiness.** The SimulationMaster declares what it needs via abstract interfaces. Switching from software to real-time execution is a one-line change at the composition root.

**Equipment as the universal model abstraction.** Every spacecraft model — FMU, native Python, or future hardware — is an Equipment. Equipment extends ModelAdapter so every model is directly driveable by SimulationMaster. No parallel patterns, no adapter wrapping.

**Port-based inter-equipment communication.** Equipment models communicate through named ports (IN/OUT). The WiringMap defines point-to-point connections between ports. Wiring is declared in human-readable YAML — not a 1M-line XML file.

**TM and TC are architecturally separate.** The ParameterStore holds telemetry outputs (written by Equipment OUT ports). The CommandStore holds telecommands (written by test procedures or wiring, consumed by Equipment IN ports). These are never conflated.

**One data one source.** Every parameter has exactly one authoritative definition in the SRDB, shared across all engineering disciplines.

**Requirements traceability from day one.** Every test references a requirement via `@pytest.mark.requirement()`. Every BASELINED requirement has a test. The traceability matrix is generated automatically after every CI run.

**CI/CD compatibility.** All outputs are consumable by standard CI/CD pipelines. SVF fits into existing developer workflows.

---

## 3. Layered Architecture

```
+--------------------------------------------------------------+
|                    CAMPAIGN MANAGER (M5)                     |
|            YAML/TOML test campaign definitions               |
|         requirements traceability  |  config baseline        |
+----------------------+---------------------------------------+
                       |
+----------------------v---------------------------------------+
|                  TEST ORCHESTRATOR                           |
|               pytest core + SVF plugin                       |
|    svf_session fixture  |  verdict mapper  |  observable API |
|    inject()             |  svf_initial_commands              |
|    svf_command_schedule |  traceability matrix hook          |
+------+--------------------------------------+----------------+
       |                                      |
+------v--------------+            +----------v---------------+
|  SIMULATION MASTER  |            |   TEST PROCEDURES        |
|                     |            |                          |
|  TickSource         |            |   @pytest.mark.requirement
|  SyncProtocol       |            |   observe("eps.bat.soc") |
|  Equipment[]        |            |     .exceeds(0.8)        |
|  WiringMap          |            |     .within(120.0)       |
|  param_store        |            |   inject("eps.sol.", 1.0)|
|  command_store      |            |   svf_command_schedule   |
+------+--------------+            +--------------------------+
       |
+------v--------------------------------------------------------------+
|                 ABSTRACTION LAYER                                   |
|                                                                     |
|  TickSource         SyncProtocol          ModelAdapter              |
|  (abstract)         (abstract)            (abstract)                |
|      |                  |                     |                     |
|  Software           DDS-based            Equipment (abstract)       |
|  Realtime(defer)    SHM(defer)               |                      |
|                                         FmuEquipment                |
|                                         NativeEquipment             |
|                                         Hardware(defer)             |
+------+--------------------------------------------------------------+
       |
+------v--------------------------------------------------------------+
|                 EQUIPMENT & PORT LAYER                              |
|                                                                     |
|  Equipment (extends ModelAdapter)                                   |
|    equipment_id, ports (IN/OUT)                                     |
|    write_port(), read_port(), receive()                             |
|    on_tick():                                                       |
|      1. CommandStore.take() -> receive() for each IN port           |
|      2. do_step(t, dt)      <- subclass implements physics          |
|      3. ParameterStore.write() for each OUT port                   |
|      4. SyncProtocol.publish_ready()                               |
|                                                                     |
|  FmuEquipment           NativeEquipment                            |
|  wraps FMU              wraps step_fn                              |
|  + parameter_map        + port declarations                        |
|  FMU vars -> ports      step_fn(eq, t, dt)                        |
+------+------+------------------------------------------------------+
       |      |
+------v--+   +---v-------------------------------------------------+
|PARAMETER|   | COMMAND STORE                                       |
|STORE    |   |                                                     |
| TM only |   | TC only — take() atomic read+consume               |
|         |   | written by: inject(), initial_commands,            |
| OUT port|   |             svf_command_schedule, wiring           |
| values  |   | consumed by: Equipment.on_tick() per IN port       |
|         |   |                                                     |
| svf.    |   | SRDB canonical names as keys                       |
| sim_time|   |                                                     |
+---------+   +-----------------------------------------------------+
       |              |
+------v--------------v----------------------------------------------+
|              SPACECRAFT REFERENCE DATABASE (SRDB)                  |
|                                                                     |
|  ParameterDefinition: name, unit, dtype, valid_range               |
|  classification (TM/TC), domain, model_id, pus mapping             |
|                                                                     |
|  Domain baselines: EPS | AOCS | TTC | OBDH | Thermal               |
|  Mission overrides: srdb/missions/{mission}.yaml                    |
|  Equipment wiring:  srdb/wiring/{system}_wiring.yaml               |
|                                                                     |
|  Runtime validation: range warnings, TM/TC separation warnings     |
+------+--------------------------------------------------------------+
       |
+------v--------------------------------------------------------------+
|              COMMUNICATION BUS (Cyclone DDS)                       |
|                                                                     |
|   SVF/Sim/Tick           <- simulation tick broadcasts              |
|   SVF/Sim/Ready/{id}     <- model acknowledgements                 |
|                                                                     |
|   Future (M6-M9): 1553 | CAN | SpW | UART | CCSDS/PUS             |
+------+--------------------------------------------------------------+
       |
+------v--------------------------------------------------------------+
|              REPORTING & TRACEABILITY                               |
|                                                                     |
|   results/traceability.txt  — generated after every test run       |
|   @pytest.mark.requirement() — links tests to requirements         |
|   tools/check_coverage.py   — cross-references BASELINED reqs      |
|                                                                     |
|   Future (M5): JUnit XML | Allure HTML | ECSS test records         |
+---------------------------------------------------------------------+
```

---

## 4. Equipment Model

### 4.1 Class Hierarchy

```
ModelAdapter (ABC)
    └── Equipment (ABC)
            ├── FmuEquipment     — wraps FMI 3.0 FMU
            ├── NativeEquipment  — wraps Python step function
            └── (future) HardwareEquipment — HIL bridge
```

`Equipment` extends `ModelAdapter` directly. Every Equipment is driveable by `SimulationMaster` without any adapter wrapping.

### 4.2 Equipment Lifecycle (on_tick)

```
Equipment.on_tick(t, dt):
  1. For each IN port:
       entry = CommandStore.take(port_name)
       if entry: receive(port_name, entry.value)
  2. do_step(t, dt)          ← subclass implements physics
  3. For each OUT port:
       ParameterStore.write(port_name, port_value, t+dt, equipment_id)
  4. SyncProtocol.publish_ready(equipment_id, t)
```

### 4.3 Port Interface

```python
class Equipment(ModelAdapter):
    def write_port(self, name: str, value: float) -> None: ...  # OUT only
    def read_port(self, name: str) -> float: ...                # any port
    def receive(self, port_name: str, value: float) -> None: ...# IN only
```

### 4.4 FmuEquipment

Wraps an FMI 3.0 FMU. FMU inputs → IN ports, FMU outputs → OUT ports. `parameter_map` translates FMU variable names to SRDB canonical port names.

```python
eq = FmuEquipment(
    fmu_path="models/EpsFmu.fmu",
    equipment_id="eps",
    sync_protocol=sync,
    store=store,
    command_store=cmd_store,
    parameter_map={
        "battery_soc":        "eps.battery.soc",
        "solar_illumination": "eps.solar_array.illumination",
        ...
    }
)
```

### 4.5 NativeEquipment

Wraps a plain Python step function. Ports declared explicitly at construction.

```python
def rw_step(eq: NativeEquipment, t: float, dt: float) -> None:
    if eq.read_port("power_enable") > 0.5:
        speed = eq.read_port("speed") + 100.0 * dt
        eq.write_port("speed", speed)

eq = NativeEquipment(
    equipment_id="rw1",
    ports=[
        PortDefinition("power_enable", PortDirection.IN),
        PortDefinition("speed", PortDirection.OUT, unit="rpm"),
    ],
    step_fn=rw_step,
    sync_protocol=sync,
    store=store,
    command_store=cmd_store,
)
```

---

## 5. Equipment Wiring

### 5.1 WiringMap

Point-to-point connections between equipment OUT ports and IN ports. Applied by `SimulationMaster` after every tick via `receive()`.

```
After tick t:
  for each Connection(from_eq, from_port, to_eq, to_port):
      value = equipment[from_eq].read_port(from_port)
      CommandStore.inject(to_port, value, source_id="wiring:...")
```

Wiring is validated at `run()` time before the first tick — unknown equipment or ports raise `SimulationError` immediately.

### 5.2 Wiring YAML Schema

```yaml
# srdb/wiring/eps_wiring.yaml
connections:
  - from: solar_array.eps.solar_array.generated_power
    to:   pcdu.eps.solar_input
    description: Solar array power to PCDU input

  - from: battery.eps.battery.voltage
    to:   pcdu.eps.battery_voltage_in
    description: Battery voltage feedback to PCDU

  - from: pcdu.eps.pcdu.charge_current
    to:   battery.eps.battery.charge_current_in
    description: PCDU charge current command to battery
```

### 5.3 WiringLoader

```python
loader = WiringLoader(equipment_dict)
wiring = loader.load(Path("srdb/wiring/eps_wiring.yaml"))
```

Validates all referenced equipment IDs and port names. Source must be OUT port, destination must be IN port.

---

## 6. Simulation Execution Model

### 6.1 Tick-Based Lockstep Protocol

```
Master                    Equipment A             Equipment B
  |                            |                       |
  |--- tick(t=0.1) ----------->|                       |
  |--- tick(t=0.1) ---------------------------------->|
  |                       CommandStore.take()    CommandStore.take()
  |                       do_step()              do_step()
  |                       ParameterStore.write() ParameterStore.write()
  |                       publish_ready()        publish_ready()
  |<-- ready(A) ---------------|                       |
  |<-- ready(B) ----------------------------------------|
  |   Apply wiring (CommandStore.inject per connection) |
  |   Write svf.sim_time to ParameterStore              |
  |--- tick(t=0.2) ----------->|                       |
```

### 6.2 TM/TC Separation

| Store | Direction | Written by | Read by | Keys |
|---|---|---|---|---|
| ParameterStore | TM | Equipment OUT ports, SimulationMaster (svf.sim_time) | Observables, loggers, scheduler | SRDB canonical names |
| CommandStore | TC | inject(), wiring, initial_commands, scheduler | Equipment IN ports | SRDB canonical names |

### 6.3 svf_command_schedule — Multi-Phase Test Procedures

The `svf_command_schedule` mark enables test procedures with multiple phases by scheduling commands at specific simulation times:

```python
@pytest.mark.svf_command_schedule([
    (60.0, "eps.solar_array.illumination", 0.0),  # eclipse at t=60s
])
def test_eclipse_transition(svf_session):
    svf_session.observe("eps.battery.soc").exceeds(0.85).within(90.0)
    svf_session.observe("eps.battery.charge_current").drops_below(0.0).within(60.0)
```

How it works:
1. `SimulationMaster` writes `svf.sim_time` to ParameterStore after each tick
2. A scheduler thread polls `svf.sim_time`
3. When `sim_t >= target_t`, the command is injected into CommandStore
4. The Equipment picks it up on the next tick

---

## 7. Spacecraft Reference Database (SRDB)

### 7.1 ParameterDefinition

```python
@dataclass(frozen=True)
class ParameterDefinition:
    name: str                    # canonical: domain.subsystem.parameter
    description: str
    unit: str
    dtype: Dtype                 # float | int | bool | string
    classification: Classification  # TM | TC
    domain: Domain               # EPS | AOCS | TTC | OBDH | THERMAL
    model_id: str
    valid_range: Optional[tuple[float, float]]
    pus: Optional[PusMapping]    # APID, service, subservice, parameter_id
```

### 7.2 Domain Baselines

| File | Domain |
|---|---|
| srdb/baseline/eps.yaml | EPS — battery, solar array, PCDU |
| srdb/baseline/aocs.yaml | AOCS — attitude, rates, actuators |
| srdb/baseline/ttc.yaml | TTC — transponder, antenna, link |
| srdb/baseline/obdh.yaml | OBDH — OBC health, memory, modes |
| srdb/baseline/thermal.yaml | Thermal — sensors, heaters |

### 7.3 Runtime Validation

When an `Srdb` is wired to `ParameterStore` and `CommandStore`:
- Warning when value outside `valid_range`
- Warning when model writes TC-classified parameter
- Warning when test procedure injects TM-classified parameter

Warnings logged, never raised — simulation continues regardless.

---

## 8. pytest Plugin

### 8.1 Marks Reference

| Mark | Default | Description |
|---|---|---|
| `svf_fmus([FmuConfig(...)])` | SimpleCounter.fmu | FMU equipment list |
| `svf_dt(float)` | 0.1 | Timestep in seconds |
| `svf_stop_time(float)` | 2.0 | Stop time in seconds |
| `svf_initial_commands([(name, value)])` | [] | Commands before simulation starts |
| `svf_command_schedule([(t, name, value)])` | [] | Commands fired at simulation time t |
| `requirement(*ids)` | — | Requirement IDs verified by this test |

### 8.2 Observable API

```python
svf_session.observe("eps.battery.soc").exceeds(0.88).within(120.0)
svf_session.observe("eps.battery.soc").drops_below(0.75).within(120.0)
svf_session.observe("eps.battery.soc").reaches(0.9).within(120.0)
svf_session.observe("eps.battery.soc").satisfies(lambda v: 0.2 < v < 0.95).within(120.0)
```

Observables fail fast when the simulation thread exits — no unnecessary wall-clock waiting.

### 8.3 ECSS Verdict Mapper

| pytest outcome | ECSS Verdict |
|---|---|
| Passed | PASS |
| Failed (AssertionError) | FAIL |
| Error (infrastructure) | ERROR |
| Neither | INCONCLUSIVE |

### 8.4 Traceability Matrix

Generated automatically after every test run to `results/traceability.txt`:

```
SVF Requirements Traceability Matrix
============================================================
Requirement          Verdict      Test Case
------------------------------------------------------------
EPS-011              PASS         test_tc_pwr_001_battery_charges_in_sunlight
EQP-001              PASS         test_equipment_construction
SVF-DEV-004          PASS         test_wiring_propagates_values
...
------------------------------------------------------------
Total requirements covered: 47
```

---

## 9. Reference Models — EPS

### 9.1 Integrated EPS FMU

Single FMU for quick validation. All three subsystems internally decomposed.

| FMU Variable | Port Name | Direction | Unit | Range |
|---|---|---|---|---|
| solar_illumination | eps.solar_array.illumination | IN (TC) | — | 0–1 |
| load_power | eps.load.power | IN (TC) | W | 0–200 |
| battery_soc | eps.battery.soc | OUT (TM) | — | 0.05–1.0 |
| battery_voltage | eps.battery.voltage | OUT (TM) | V | 3.0–4.2 |
| bus_voltage | eps.bus.voltage | OUT (TM) | V | 3.0–4.2 |
| generated_power | eps.solar_array.generated_power | OUT (TM) | W | 0–120 |
| charge_current | eps.battery.charge_current | OUT (TM) | A | -20–20 |

### 9.2 Decomposed EPS

Three separate FMUs connected via `srdb/wiring/eps_wiring.yaml`:

| FMU | Inputs | Outputs |
|---|---|---|
| SolarArrayFmu | solar_illumination | generated_power, array_voltage |
| BatteryFmu | charge_current | battery_voltage, battery_soc |
| PcduFmu | generated_power, battery_voltage, load_power | bus_voltage, charge_current |

### 9.3 Validated Test Procedures

| ID | Test Case | Type | Status |
|---|---|---|---|
| TC-PWR-001 | Battery charges in full sunlight | Single-phase | PASS |
| TC-PWR-002 | Battery discharges in eclipse | Single-phase | PASS |
| TC-PWR-003 | Sunlight to eclipse transition | Multi-phase (svf_command_schedule) | PASS |
| TC-PWR-004 | Partial illumination (penumbra) | Single-phase | PASS |
| TC-PWR-005 | Low battery recovery | Multi-phase (svf_command_schedule) | PASS |

---

## 10. Test Structure

```
tests/
├── unit/           SVF platform classes in isolation (SVF-DEV-xxx)
├── equipment/      Generic Equipment contract (EQP-xxx)
├── integration/    SVF infrastructure mechanics (SVF-DEV-xxx)
└── spacecraft/     Specific model behaviour (EPS-xxx)
```

Rules:
- Every test has `@pytest.mark.requirement()` — no exceptions
- A test belongs at the lowest level that can verify it
- No test without a requirement, no requirement without a test

---

## 11. Technology Stack

| Concern | Choice | Rationale |
|---|---|---|
| Simulation standard | FMI 3.0 | Open, widely adopted, real-time ready |
| Simulation library | fmpy | Mature Python FMI implementation |
| Model abstraction | Equipment (extends ModelAdapter) | Single coherent pattern, port-based |
| Model authoring | pythonfmu (Python), C FMUs | Low barrier, FMI-compliant |
| Parameter database | SRDB (YAML + Python loader) | ECSS-E-TM-10-23 inspired |
| Equipment wiring | WiringMap + YAML | Human-readable, not 1M-line XML |
| Communication bus | Eclipse Cyclone DDS | Tick synchronisation |
| Telemetry store | ParameterStore | Thread-safe, SRDB-keyed, late-joiner safe |
| Command store | CommandStore | TM/TC separation, atomic take() |
| Test runner | pytest + SVF plugin | Ecosystem, CI compatibility |
| Traceability | @pytest.mark.requirement() | Auto-generated matrix after every run |
| Build system | CMake + scikit-build-core | Mixed C/Python |
| Packaging | pyproject.toml | pip-installable |

---

## 12. Development Milestones

| Milestone | Objective | Status |
|---|---|---|
| M1 - Simulation Master | fmpy, CSV, CI | ✅ DONE |
| M2 - Simulation Bus & Abstractions | TickSource, SyncProtocol, ModelAdapter, DDS | ✅ DONE |
| M3 - pytest Plugin | svf_session, observable, verdict, ParameterStore, CommandStore | ✅ DONE |
| M3.5 - SRDB | Parameter definitions, domain baselines, PUS mapping | ✅ DONE |
| M3.6 - Requirements Engineering | EQP/EPS requirements, test restructuring, traceability | ✅ DONE |
| M4 - First Real Model | Integrated EPS FMU, 5 test procedures | ✅ DONE |
| M4.5 - Model Wiring | Equipment ABC, FmuEquipment, WiringMap, decomposed EPS, svf_command_schedule | ✅ DONE |
| M5 - Campaign & Reporting | YAML campaigns, ECSS reports, Allure HTML | NEXT |
| M6 - Bus Protocols | 1553, SpW, CAN, UART, WizardLink | PENDING |
| M7 - ICD Integration | ICD parser, wiring YAML generator | PENDING |
| M8 - Real-Time & HIL | RT_PREEMPT, shared memory sync, HIL adapter | PENDING |
| M9 - Ground Segment | CCSDS/PUS, YAMCS, XTCE export, MIB import | PENDING |
| v0.1 | First release | 2026-05-30 |

---

## 13. Out of Scope (v0.1)

- Real-time / HIL execution (M8)
- SMP2 model import
- CCSDS/PUS command adapter (M9)
- Bus protocol adapters (M6)
- ICD parser (M7)
- DOORS NG / Jama Connect integration
- Tool qualification (DO-178C, ECSS-E-ST-40C)
- Multi-node distributed simulation
- GUI / visual modelling environment
- SharedMemorySyncProtocol (M8)
- RealtimeTickSource (M8)
- ParameterStoreDdsBridge (M9)
- SRDB calibration curves
- XTCE export / MIB import (M9)
- SSP file support (deferred from M4.5)