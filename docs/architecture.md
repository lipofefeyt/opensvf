# SVF Architecture

> **Status:** Draft — v0.3
> **Last updated:** 2026-03
> **Author:** lipofefeyt

---

## 1. Overview

The Software Validation Facility (SVF) is an open-core platform for the validation of spacecraft software and systems. It provides a simulation infrastructure, a communication bus, a component modelling framework, and a test orchestration layer — designed to be standards-based, modular, and incrementally scalable.

The initial target domain is aerospace (small satellites, NewSpace), with architecture choices made to allow later extension into adjacent regulated industries (automotive, rail, medical).

The platform is designed to start small — a single developer, a single spacecraft model — and scale toward distributed multi-model campaigns, hardware-in-the-loop, and real-time execution without requiring architectural rewrites.

---

## 2. Design Principles

**Standards at the boundaries.** Every integration point between layers uses an open standard. This ensures model interoperability, avoids tool lock-in, and supports procurement in regulated environments.

**Python orchestrates, C executes.** Python handles test logic, campaign management, and orchestration. C handles simulation model internals where timing and throughput matter.

**Plugin-first design.** Every integration point is a plugin slot from day one, even if only one adapter is initially implemented. This is what allows later support for CCSDS, SpaceWire, real hardware interfaces, without touching the core.

**Dependency injection for real-time readiness.** The SimulationMaster declares what it needs via abstract interfaces. Concrete implementations are injected at startup. Switching from software to real-time execution is a one-line change at the composition root — no surgery on the core.

**Models speak for themselves.** The SimulationMaster never publishes telemetry or sync acknowledgements on behalf of models. Each ModelAdapter is responsible for publishing its own outputs and acknowledging its own readiness. The master only drives and waits.

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
+------+--------------------------------------+----------------+
       |                                      |
+------v--------------+            +----------v---------------+
|  SIMULATION MASTER  |            |   TEST PROCEDURES        |
|                     |            |   Python scripts         |
|  TickSource         |            |   svf_session fixture    |
|  SyncProtocol       |            |   observe().reaches()    |
|  ModelAdapter[]     |            |     .within()            |
+------+--------------+            +--------------------------+
       |
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
|   [Spacecraft Bus]  [AOCS]  [OBDH]  [Environment]                  |
|   [Ground Segment Sim]  [Failure Injector]  [Sensor Models]         |
|          pythonfmu (Python FMUs)  |  C/C++ FMUs                     |
+------+--------------------------------------------------------------+
       |
+------v--------------------------------------------------------------+
|              COMMUNICATION BUS (Cyclone DDS)                       |
|                                                                     |
|   SVF/Sim/Tick           <- simulation tick broadcasts              |
|   SVF/Sim/Ready/{id}     <- model acknowledgements                 |
|   SVF/Telemetry/{name}   <- FMU output variables                   |
|   SVF/Command/{name}     <- injected commands                      |
|                                                                     |
|   plugin adapters: CCSDS | SpaceWire | custom EGSE                  |
+------+--------------------------------------------------------------+
       |
+------v--------------------------------------------------------------+
|              REPORTING & TRACEABILITY                               |
|     JUnit XML  |  Allure HTML  |  ECSS verdict records              |
|     requirements linkage  |  full timeline export                   |
+---------------------------------------------------------------------+
```

---

## 4. Simulation Execution Model

### 4.1 Tick-Based Lockstep Protocol

The simulation master does not call models directly. Instead it broadcasts time ticks over DDS. Models subscribe to ticks, perform their computation, publish their outputs to telemetry topics, and acknowledge readiness. The master waits for all acknowledgements before advancing to the next tick.

```
Master                    Model A                 Model B
  |                          |                       |
  |--- tick(t=0.1) --------->|                       |
  |--- tick(t=0.1) --------------------------------->|
  |                          |                       |
  |                     doStep()               doStep()
  |                     publish telemetry      publish telemetry
  |                     publish_ready()        publish_ready()
  |                          |                       |
  |<-- ready(A, t=0.1) ------|                       |
  |<-- ready(B, t=0.1) --------------------------------|
  |                          |                       |
  |--- tick(t=0.2) --------->|                       |
```

This gives deterministic, reproducible simulation runs — essential for certification traceability.

### 4.2 DDS Topic Naming Convention

| Topic | Direction | Payload |
|---|---|---|
| SVF/Sim/Tick | Master -> Models | SimTick(t, dt) |
| SVF/Sim/Ready/{model_id} | Model -> Master | SimReady(model_id, t) |
| SVF/Telemetry/{variable} | Model -> Subscribers | TelemetrySample(model_id, variable, t, value) |
| SVF/Command/{variable} | Publisher -> Model | CommandSample(t, name, value) |

---

## 5. Abstraction Layer

The abstraction layer is the key to real-time readiness. The SimulationMaster depends only on three interfaces — never on concrete implementations.

### 5.1 TickSource

Responsible for generating simulation time ticks.

```python
class TickSource(ABC):
    def start(self, on_tick: TickCallback, dt: float, stop_time: float) -> None: ...
    def stop(self) -> None: ...
```

| Implementation | When used |
|---|---|
| SoftwareTickSource | Default — Python loop, runs as fast as hardware allows |
| RealtimeTickSource (deferred) | RT_PREEMPT timer or external hardware sync pulse |

### 5.2 SyncProtocol

Responsible for coordinating tick acknowledgements. Each ModelAdapter calls publish_ready() itself after on_tick() — the master never speaks for models.

```python
class SyncProtocol(ABC):
    def wait_for_ready(self, expected: list[str], timeout: float) -> bool: ...
    def publish_ready(self, model_id: str, t: float) -> None: ...
    def reset(self) -> None: ...
```

| Implementation | When used |
|---|---|
| DdsSyncProtocol | Default — acknowledgements over DDS topics |
| SharedMemorySyncProtocol (deferred) | Lock-free ring buffer for sub-millisecond latency |

### 5.3 ModelAdapter

Wraps any simulation model. Each adapter publishes its own telemetry and sync acknowledgements.

```python
class ModelAdapter(ABC):
    @property
    def model_id(self) -> str: ...
    def initialise(self, start_time: float = 0.0) -> None: ...
    def on_tick(self, t: float, dt: float) -> None: ...
    def teardown(self) -> None: ...
```

| Implementation | When used |
|---|---|
| FmuModelAdapter | Wraps an FMI 3.0 FMU via fmpy |
| NativeModelAdapter | Wraps a plain Python class for lightweight testing |
| Hardware adapter (deferred) | Bridges DDS topics to physical interfaces |

### 5.4 Real-Time Upgrade Path

| Step | What changes | What stays the same |
|---|---|---|
| Soft RT (RT_PREEMPT kernel) | Nothing in code | Everything |
| Deterministic ticking | SoftwareTickSource -> RealtimeTickSource | Everything else |
| Low-latency sync | DdsSyncProtocol -> SharedMemorySyncProtocol | Everything else |
| HIL interface | New ModelAdapter for hardware bridge | Everything else |

---

## 6. pytest Plugin

The SVF pytest plugin turns the simulation infrastructure into a test tool. It is registered as a pytest11 entry point and is automatically available to any project that installs opensvf.

### 6.1 Simulation Lifecycle Fixture

The svf_session fixture starts a SimulationMaster in a background thread before the test body runs, and tears it down cleanly after — regardless of whether the test passes or fails.

```python
@pytest.mark.svf_stop_time(10.0)
@pytest.mark.svf_dt(0.1)
@pytest.mark.svf_fmus([FmuConfig("models/power.fmu", "power")])
def test_power_model(svf_session):
    svf_session.observe("battery_voltage").exceeds(3.3).within(5.0)
```

Configuration is via pytest marks:

| Mark | Default | Description |
|---|---|---|
| svf_fmus([FmuConfig(...)]) | SimpleCounter.fmu | FMUs to load |
| svf_dt(float) | 0.1 | Simulation timestep in seconds |
| svf_stop_time(float) | 2.0 | Simulation stop time in seconds |

### 6.2 Observable Assertion API

Fluent API for time-bounded telemetry assertions. Subscribes to SVF/Telemetry/{variable} DDS topics and polls until the condition is met or the timeout expires.

```python
# Assert a variable reaches an exact value
svf_session.observe("counter").reaches(1.0).within(2.0)

# Assert a variable crosses a threshold
svf_session.observe("voltage").exceeds(3.3).within(5.0)

# Assert a variable drops below a threshold
svf_session.observe("temperature").drops_below(100.0).within(10.0)

# Assert an arbitrary condition
svf_session.observe("status").satisfies(
    lambda v: v > 0, description="status is active"
).within(3.0)
```

Returns the value that satisfied the condition. Raises ConditionNotMet (a subclass of AssertionError) if the timeout expires, which pytest maps to a FAIL verdict.

### 6.3 ECSS Verdict Mapper

Maps pytest outcomes to ECSS-E-ST-10-02C compatible verdicts after each test:

| pytest outcome | ECSS Verdict |
|---|---|
| Passed | PASS |
| Failed (AssertionError) | FAIL |
| Error (infrastructure fault) | ERROR |
| Neither passed nor failed | INCONCLUSIVE |

Verdicts are recorded in the SimulationSession and included in JUnit XML output.

---

## 7. Layer Descriptions

### 7.1 Simulation Core — FMI 3.0 + SSP

The simulation core is built around the Functional Mock-up Interface (FMI) 3.0 standard (Modelica Association).

Key reasons for this choice:
- Open standard with broad industry adoption (aerospace, automotive, energy)
- Models from MATLAB/Simulink, OpenModelica, Dymola and others export as FMUs and plug in without modification
- FMI 3.0 Scheduled Execution mode provides the foundation for future real-time support
- FMI 3.0 adds arrays, binary variables, and clocks — all relevant for spacecraft modelling

The Python library fmpy is used to load, instantiate, and step FMUs. The FmuModelAdapter wraps fmpy and implements the ModelAdapter interface.

SSP (System Structure and Parameterization) is used for describing FMU interconnections. SSP files are version-controllable and allow subsystem models to be swapped between campaigns without changing test logic.

For model authoring, pythonfmu allows models to be written as Python classes with minimal boilerplate. Performance-critical models are written in C and compiled to native FMUs.

### 7.2 Communication Bus — Eclipse Cyclone DDS

Eclipse Cyclone DDS (Apache 2.0) is the internal communication backbone.

DDS (OMG standard) provides publish/subscribe with rich QoS policies. For aerospace this maps directly onto spacecraft TM/TC behaviour: reliable vs best-effort delivery, telemetry history windows, and deadline monitoring.

All DDS writers and readers use KEEP_ALL QoS to ensure no messages are lost when multiple models publish concurrently.

### 7.3 Test Orchestration — pytest + SVF Plugin

pytest is the base test runner. The SVF plugin (registered as a pytest11 entry point) adds:
- svf_session fixture for simulation lifecycle management
- ObservableFactory for fluent telemetry assertions
- ECSS verdict mapping via pytest hooks
- Custom marks for simulation configuration

### 7.4 Campaign Manager (M5)

Test campaigns are defined in YAML files specifying: campaign ID, model configuration baseline, requirement IDs under verification, and ordered test case references. Campaign files are versioned artefacts forming the traceable link between requirements and execution.

### 7.5 Reporting & Traceability (M5)

Two output streams: JUnit XML for CI/CD pipelines, and structured ECSS-E-ST-10-02C aligned records for certification. Requirements traceability matrix generated automatically from pytest markers and campaign YAML declarations.

---

## 8. Technology Stack Summary

| Concern | Choice | Rationale |
|---|---|---|
| Simulation standard | FMI 3.0 | Open, widely adopted, real-time ready |
| Simulation library | fmpy | Mature Python FMI implementation |
| Model authoring | pythonfmu (Python), C FMUs | Low barrier, FMI-compliant output |
| System description | SSP | Version-controllable wiring diagrams |
| Communication bus | Eclipse Cyclone DDS | Open source, QoS-rich, RTPS-based |
| Abstractions | Python ABC | Dependency injection, real-time switchable |
| Test runner | pytest + SVF plugin | Ecosystem, CI compatibility, extensibility |
| Plugin registration | pytest11 entry point | Auto-discovery, zero configuration |
| Build system | CMake + scikit-build-core | Mixed C/Python project support |
| Packaging | pyproject.toml | pip-installable core |
| Containerisation | Docker | Parallel execution, cloud-scalable |
| Configuration | TOML (system), YAML (campaigns) | Structured config vs human-authored |

---

## 9. Model Authoring Philosophy

The developer experience for model authoring follows a Python-first approach:

```python
@svf.model
class PowerModel:
    solar_input: svf.input(float)
    battery_voltage: svf.output(float)
    charge_level: svf.state(float, initial=0.8)

    def step(self, dt: float) -> None:
        ...
```

This produces a standard FMI 3.0 compliant FMU via pythonfmu. An SMP2 importer is a future plugin option for customers with existing model libraries.

---

## 10. Development Milestones

| Milestone | Objective | Status |
|---|---|---|
| M1 - Simulation Master | fmpy stepping a single FMU, CSV output, CI pipeline | DONE |
| M2 - Simulation Bus & Abstractions | TickSource, SyncProtocol, ModelAdapter + DDS implementations | DONE |
| M3 - pytest Plugin | svf_session fixture, observable API, verdict mapper | IN PROGRESS |
| M4 - First Real Model | Spacecraft power or thermal model, full stack validation | PENDING |
| M5 - Campaign & Reporting | YAML campaign loader, JUnit XML + traceability matrix | PENDING |

---

## 11. Out of Scope (Initial Version)

- Real-time / HIL execution
- SMP2 model import
- DOORS NG / Jama Connect integration
- Tool qualification (DO-178C, ECSS-E-ST-40C toolchain qualification)
- Multi-node distributed simulation
- GUI / visual modelling environment
- SharedMemorySyncProtocol
- RealtimeTickSource
