# SVF Architecture

> **Status:** Draft — v0.5
> **Last updated:** 2026-03
> **Author:** lipofefeyt

---

## 1. Overview

The Software Validation Facility (SVF) is an open-core platform for the validation of spacecraft software and systems. It provides a simulation infrastructure, a communication bus, a spacecraft reference database, a component modelling framework, and a test orchestration layer — designed to be standards-based, modular, and incrementally scalable.

The initial target domain is aerospace (small satellites, NewSpace), with architecture choices made to allow later extension into adjacent regulated industries (automotive, rail, medical).

The platform is designed to start small — a single developer, a single spacecraft model — and scale toward distributed multi-model campaigns, hardware-in-the-loop, and real-time execution without requiring architectural rewrites.

---

## 2. Design Principles

**Standards at the boundaries.** Every integration point between layers uses an open standard. This ensures model interoperability, avoids tool lock-in, and supports procurement in regulated environments.

**Python orchestrates, C executes.** Python handles test logic, campaign management, and orchestration. C handles simulation model internals where timing and throughput matter.

**Plugin-first design.** Every integration point is a plugin slot from day one, even if only one adapter is initially implemented. This is what allows later support for CCSDS, SpaceWire, real hardware interfaces, without touching the core.

**Dependency injection for real-time readiness.** The SimulationMaster declares what it needs via abstract interfaces. Concrete implementations are injected at startup. Switching from software to real-time execution is a one-line change at the composition root.

**Models speak for themselves.** The SimulationMaster never publishes telemetry or sync acknowledgements on behalf of models. Each ModelAdapter is responsible for publishing its own outputs and acknowledging its own readiness.

**TM and TC are architecturally separate.** The ParameterStore holds telemetry outputs. The CommandStore holds telecommands. These are never conflated, mirroring the fundamental TM/TC separation in real spacecraft architecture.

**One data one source.** Every parameter has exactly one authoritative definition in the SRDB, shared across all engineering disciplines — simulation models, test procedures, reporters, and future ground segment tools.

**CI/CD compatibility.** All outputs (test verdicts, reports, traceability records) are consumable by standard CI/CD pipelines. SVF fits into existing developer workflows, it does not replace them.

---

## 3. Layered Architecture

```
+--------------------------------------------------------------+
|                    CAMPAIGN MANAGER                          |
|            YAML/TOML test campaign definitions               |
|         requirements traceability  |  config baseline        |
+----------------------+---------------------------------------+
                       |
+----------------------v---------------------------------------+
|                  TEST ORCHESTRATOR                           |
|               pytest core + SVF plugin                       |
|    svf_session fixture | verdict mapper | observable API     |
|    inject() stimuli API | svf_initial_commands mark          |
+------+--------------------------------------+----------------+
       |                                      |
+------v--------------+            +----------v---------------+
|  SIMULATION MASTER  |            |   TEST PROCEDURES        |
|                     |            |   Python scripts         |
|  TickSource         |            |   svf_session fixture    |
|  SyncProtocol       |            |   observe("eps.batt.soc")|
|  ModelAdapter[]     |            |     .exceeds(0.8)        |
+------+--------------+            |     .within(120.0)       |
       |                           |   inject("eps.sol.", 1.0)|
       |                           +--------------------------+
+------v--------------------------------------------------------------+
|                 ABSTRACTION LAYER                                   |
|                                                                     |
|  TickSource         SyncProtocol          ModelAdapter              |
|  (abstract)         (abstract)            (abstract)                |
|      |                  |                     |                     |
|  Software           DDS-based            FMU adapter                |
|  Realtime(defer)    SHM(defer)           Native Python              |
+------+--------------------------------------------------------------+
       |
+------v--------------------------------------------------------------+
|                    FMU ECOSYSTEM                                    |
|   [EPS]  [AOCS]  [TTC]  [OBDH]  [Thermal]  [Environment]          |
|          pythonfmu (Python FMUs)  |  C/C++ FMUs                     |
|   parameter_map: FMU name -> SRDB canonical name                    |
+------+------+------------------------------------------------------+
       |      |
+------v--+   +---v-------------------------------------------------+
|PARAMETER|   | COMMAND STORE                                       |
|STORE    |   |                                                     |
|         |   | CommandEntry(name, value, t, source_id, consumed)  |
| TM only |   | TC only - take() atomic read+consume               |
|         |   |                                                     |
| keys:   |   | keys: SRDB canonical names                         |
| SRDB    |   | e.g. "eps.solar_array.illumination"                |
| canonical   |                                                     |
| names   |   | written by: inject() API, svf_initial_commands     |
|         |   | consumed by: FmuModelAdapter before each doStep()  |
+---------+   +-----------------------------------------------------+
       |              |
+------v--------------v----------------------------------------------+
|              SPACECRAFT REFERENCE DATABASE (SRDB)                  |
|                                                                     |
|  "one data one source" — inspired by ECSS-E-TM-10-23               |
|                                                                     |
|  ParameterDefinition:                                               |
|    name, description, unit, dtype, valid_range                      |
|    classification (TM/TC), domain, model_id                         |
|    pus: {apid, service, subservice, parameter_id}                   |
|                                                                     |
|  Domain baselines: EPS | AOCS | TTC | OBDH | Thermal               |
|  Mission overrides: srdb/missions/{mission}.yaml                    |
|                                                                     |
|  Future: XTCE export | MIB import | calibration curves              |
+------+--------------------------------------------------------------+
       |
+------v--------------------------------------------------------------+
|              COMMUNICATION BUS (Cyclone DDS)                       |
|                                                                     |
|   SVF/Sim/Tick           <- simulation tick broadcasts              |
|   SVF/Sim/Ready/{id}     <- model acknowledgements                 |
|                                                                     |
|   Future: SVF/Telemetry/{name} (ParameterStoreDdsBridge)           |
|   Future: bus protocol adapters (1553, CAN, I2C, UART, SpW)        |
+------+--------------------------------------------------------------+
       |
+------v--------------------------------------------------------------+
|              REPORTING & TRACEABILITY                               |
|     JUnit XML  |  Allure HTML  |  ECSS verdict records              |
|     requirements linkage  |  full timeline export                   |
|     Future: XTCE export  |  DOORS NG  |  Jama Connect               |
+---------------------------------------------------------------------+
```

---

## 4. Simulation Execution Model

### 4.1 Tick-Based Lockstep Protocol

```
Master                    Model A                 Model B
  |                          |                       |
  |--- tick(t=0.1) --------->|                       |
  |--- tick(t=0.1) --------------------------------->|
  |                          |                       |
  |                    CommandStore.take()     CommandStore.take()
  |                    doStep()               doStep()
  |                    ParameterStore.write() ParameterStore.write()
  |                    publish_ready()        publish_ready()
  |                          |                       |
  |<-- ready(A, t=0.1) ------|                       |
  |<-- ready(B, t=0.1) --------------------------------|
  |                          |                       |
  |--- tick(t=0.2) --------->|                       |
```

### 4.2 TM/TC Separation

| Store | Direction | Written by | Read by | Keys |
|---|---|---|---|---|
| ParameterStore | TM (outputs) | Model adapters | Observables, loggers, reporters | SRDB canonical names |
| CommandStore | TC (inputs) | inject() API | Model adapters before each tick | SRDB canonical names |

### 4.3 Parameter Naming

All parameters use SRDB canonical names throughout the platform. FMU variable names (constrained by FMI/pythonfmu) are mapped to canonical names via the `parameter_map` in `FmuModelAdapter`:

```python
EPS_PARAMETER_MAP = {
    "battery_soc":        "eps.battery.soc",
    "battery_voltage":    "eps.battery.voltage",
    "bus_voltage":        "eps.bus.voltage",
    "generated_power":    "eps.solar_array.generated_power",
    "charge_current":     "eps.battery.charge_current",
    "solar_illumination": "eps.solar_array.illumination",
    "load_power":         "eps.load.power",
}
```

Naming convention: `{domain}.{subsystem}.{parameter}`

### 4.4 DDS Topic Convention

| Topic | Direction | Payload |
|---|---|---|
| SVF/Sim/Tick | Master -> Models | SimTick(t, dt) |
| SVF/Sim/Ready/{model_id} | Model -> Master | SimReady(model_id, t) |

---

## 5. Spacecraft Reference Database (SRDB)

Inspired by the Astrium SRDB Next Generation and ECSS-E-TM-10-23. The SRDB is the parameter definition layer — it answers "what is this parameter?" while the ParameterStore answers "what is its current value?"

### 5.1 ParameterDefinition Schema

```python
@dataclass(frozen=True)
class PusMapping:
    apid: int           # CCSDS APID (11-bit)
    service: int        # PUS service type
    subservice: int     # PUS subservice type
    parameter_id: int   # Mission-specific parameter ID

@dataclass(frozen=True)
class ParameterDefinition:
    name: str                              # Canonical name: domain.subsystem.param
    description: str
    unit: str                              # SI unit or "" for dimensionless
    dtype: Dtype                           # float | int | bool | string
    classification: Classification         # TM | TC
    domain: Domain                         # EPS | AOCS | TTC | OBDH | THERMAL
    model_id: str
    valid_range: Optional[tuple[float, float]]
    pus: Optional[PusMapping]
```

### 5.2 Domain Baselines

Five YAML baseline files ship with SVF covering standard spacecraft subsystem parameters:

| File | Domain | Covers |
|---|---|---|
| srdb/baseline/eps.yaml | EPS | Battery, solar array, PCDU, bus |
| srdb/baseline/aocs.yaml | AOCS | Attitude, angular rates, reaction wheels, magnetorquers |
| srdb/baseline/ttc.yaml | TTC | Transponder, antenna, link budget |
| srdb/baseline/obdh.yaml | OBDH | OBC health, memory, mode management |
| srdb/baseline/thermal.yaml | THERMAL | Temperature sensors, heaters |

### 5.3 Mission Overrides

Mission-specific YAML files override or extend domain baselines:

```yaml
# srdb/missions/my_mission.yaml
parameters:
  eps.battery.soc:
    description: Battery SoC (mission margin applied)
    valid_range: [0.2, 0.9]        # Conservative margins
  eps.payload.power:               # New mission-specific parameter
    description: Payload power consumption
    unit: W
    dtype: float
    classification: TM
    domain: EPS
    model_id: eps
    valid_range: [0.0, 50.0]
```

Classification (TM/TC) cannot be changed by mission overrides.

### 5.4 SRDB Loader

```python
loader = SrdbLoader()
for f in Path("srdb/baseline").glob("*.yaml"):
    loader.load_baseline(f)
loader.load_mission(Path("srdb/missions/my_mission.yaml"))
srdb = loader.build()

defn = srdb.require("eps.battery.soc")
eps_params = srdb.by_domain(Domain.EPS)
tm_params = srdb.by_classification(Classification.TM)
```

### 5.5 PUS Mapping

Each parameter carries an optional PUS mapping enabling future CCSDS/PUS integration:

```
eps.battery.soc -> PUS Service 3 (Housekeeping), APID 0x100, param_id 0x1001
eps.solar_array.illumination -> PUS Service 20 (Parameter Mgmt), APID 0x100
```

PUS service assignments follow ECSS-E-ST-70-41C (PUS-C).

---

## 6. Abstraction Layer

### 6.1 TickSource

```python
class TickSource(ABC):
    def start(self, on_tick: TickCallback, dt: float, stop_time: float) -> None: ...
    def stop(self) -> None: ...
```

| Implementation | Status |
|---|---|
| SoftwareTickSource | Implemented — Python loop |
| RealtimeTickSource | Deferred — RT_PREEMPT timer |

### 6.2 SyncProtocol

```python
class SyncProtocol(ABC):
    def wait_for_ready(self, expected: list[str], timeout: float) -> bool: ...
    def publish_ready(self, model_id: str, t: float) -> None: ...
    def reset(self) -> None: ...
```

| Implementation | Status |
|---|---|
| DdsSyncProtocol | Implemented — DDS KEEP_ALL QoS |
| SharedMemorySyncProtocol | Deferred — lock-free ring buffer |

### 6.3 ModelAdapter

```python
class ModelAdapter(ABC):
    @property
    def model_id(self) -> str: ...
    def initialise(self, start_time: float = 0.0) -> None: ...
    def on_tick(self, t: float, dt: float) -> None: ...
    def teardown(self) -> None: ...
```

| Implementation | Status |
|---|---|
| FmuModelAdapter | Implemented — FMI 3.0 FMU + parameter_map |
| NativeModelAdapter | Implemented — plain Python class |
| Hardware adapter | Deferred |

### 6.4 Real-Time Upgrade Path

| Step | What changes | What stays the same |
|---|---|---|
| Soft RT (RT_PREEMPT kernel) | Nothing in code | Everything |
| Deterministic ticking | SoftwareTickSource -> RealtimeTickSource | Everything else |
| Low-latency sync | DdsSyncProtocol -> SharedMemorySyncProtocol | Everything else |
| HIL interface | New ModelAdapter for hardware bridge | Everything else |

---

## 7. pytest Plugin

### 7.1 Simulation Lifecycle Fixture

```python
@pytest.mark.svf_fmus([FmuConfig("models/eps.fmu", "eps", EPS_PARAMETER_MAP)])
@pytest.mark.svf_dt(1.0)
@pytest.mark.svf_stop_time(120.0)
@pytest.mark.svf_initial_commands([("eps.solar_array.illumination", 1.0)])
def test_battery_charges(svf_session):
    svf_session.observe("eps.battery.soc").exceeds(0.88).within(120.0)
    svf_session.stop()
```

| Mark | Default | Description |
|---|---|---|
| svf_fmus([FmuConfig(...)]) | SimpleCounter.fmu | FMUs with optional parameter_map |
| svf_dt(float) | 0.1 | Simulation timestep in seconds |
| svf_stop_time(float) | 2.0 | Simulation stop time in seconds |
| svf_initial_commands([(name, value)]) | [] | Commands injected before simulation starts |

### 7.2 Observable Assertion API

Polls the ParameterStore using SRDB canonical parameter names.

```python
svf_session.observe("eps.battery.soc").exceeds(0.88).within(120.0)
svf_session.observe("eps.battery.soc").drops_below(0.75).within(120.0)
svf_session.observe("eps.battery.soc").reaches(0.9).within(120.0)
svf_session.observe("eps.battery.soc").satisfies(lambda v: 0.2 < v < 0.95).within(120.0)
```

Observables fail fast when the simulation thread exits — no unnecessary waiting.

### 7.3 Stimuli Injection

```python
svf_session.inject("eps.solar_array.illumination", 0.0)  # mid-test eclipse
svf_session.inject("eps.load.power", 50.0)               # high load
```

### 7.4 ECSS Verdict Mapper

| pytest outcome | ECSS Verdict |
|---|---|
| Passed | PASS |
| Failed (AssertionError) | FAIL |
| Error (infrastructure fault) | ERROR |
| Neither | INCONCLUSIVE |

---

## 8. Technology Stack Summary

| Concern | Choice | Rationale |
|---|---|---|
| Simulation standard | FMI 3.0 | Open, widely adopted, real-time ready |
| Simulation library | fmpy | Mature Python FMI implementation |
| Model authoring | pythonfmu (Python), C FMUs | Low barrier, FMI-compliant output |
| Parameter database | SRDB (YAML + Python loader) | ECSS-E-TM-10-23 inspired, one data one source |
| Communication bus | Eclipse Cyclone DDS | Open source, QoS-rich, RTPS-based |
| Telemetry store | ParameterStore | Thread-safe, late-joiner safe, SRDB-keyed |
| Command store | CommandStore | TM/TC separation, atomic take() |
| Abstractions | Python ABC | Dependency injection, real-time switchable |
| Test runner | pytest + SVF plugin | Ecosystem, CI compatibility |
| Plugin registration | pytest11 entry point | Auto-discovery, zero configuration |
| SRDB format | YAML | Human-readable, version-controllable |
| Build system | CMake + scikit-build-core | Mixed C/Python |
| Packaging | pyproject.toml | pip-installable |
| Containerisation | Docker | Parallel execution, cloud-scalable |

---

## 9. Reference Model — Integrated EPS FMU

The first reference spacecraft model shipped with SVF is an integrated EPS (Electrical Power System) FMU comprising Solar Array, Battery (Li-Ion), and PCDU subsystems.

### 9.1 Interface

| Variable | Direction | Canonical Name | Unit | Range |
|---|---|---|---|---|
| solar_illumination | Input (TC) | eps.solar_array.illumination | — | 0.0–1.0 |
| load_power | Input (TC) | eps.load.power | W | 0–200 |
| battery_soc | Output (TM) | eps.battery.soc | — | 0.05–1.0 |
| battery_voltage | Output (TM) | eps.battery.voltage | V | 3.0–4.2 |
| bus_voltage | Output (TM) | eps.bus.voltage | V | 3.0–4.2 |
| generated_power | Output (TM) | eps.solar_array.generated_power | W | 0–120 |
| charge_current | Output (TM) | eps.battery.charge_current | A | -20–20 |

### 9.2 Validated Test Procedures

| ID | Test Case | Status |
|---|---|---|
| TC-PWR-001 | Battery charges in full sunlight | PASS |
| TC-PWR-002 | Battery discharges in eclipse | PASS |
| TC-PWR-003 | Charging behaviour in sunlight | PASS |
| TC-PWR-004 | Partial illumination (penumbra) | PASS |
| TC-PWR-005 | Deep eclipse discharge | PASS |

### 9.3 Documented Simplifications

- Solar array modelled as ideal current source (no I-V curve)
- No temperature dependence on capacity or panel efficiency
- Bus voltage equals battery voltage (no active PCU regulation)
- No battery thermal model
- Subsystem decomposition into separate FMUs deferred to M4.5

---

## 10. Development Milestones

| Milestone | Objective | Status |
|---|---|---|
| M1 - Simulation Master | fmpy, CSV, CI | DONE |
| M2 - Simulation Bus & Abstractions | TickSource, SyncProtocol, ModelAdapter, DDS | DONE |
| M3 - pytest Plugin | svf_session, observable, verdict, ParameterStore, CommandStore | DONE |
| M3.5 - SRDB | Parameter definitions, domain baselines, PUS mapping, loader | IN PROGRESS |
| M4 - First Real Model | Integrated EPS FMU, full stack validation | DONE |
| M4.5 - Model Wiring | SSP-like wiring, decomposed EPS FMUs | PENDING |
| M5 - Campaign & Reporting | YAML campaigns, traceability matrix | PENDING |

---

## 11. Out of Scope (Initial Version)

- Real-time / HIL execution
- SMP2 model import
- CCSDS/PUS command adapter (SVF-DEV-037)
- Bus protocol adapters: 1553, CAN, I2C, UART, SpaceWire, WizardLink (SVF-DEV-038)
- SRDB calibration curves (SVF-DEV-096)
- XTCE export adapter (SVF-DEV-097)
- MIB import adapter (SVF-DEV-098)
- DOORS NG / Jama Connect integration
- Tool qualification (DO-178C, ECSS-E-ST-40C)
- Multi-node distributed simulation
- GUI / visual modelling environment
- SharedMemorySyncProtocol
- RealtimeTickSource
- ParameterStoreDdsBridge