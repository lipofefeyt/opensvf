# SVF Architecture

> **Status:** Draft — v0.4
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

**TM and TC are architecturally separate.** The ParameterStore holds telemetry outputs. The CommandStore holds telecommands. These are never conflated, mirroring the fundamental TM/TC separation in real spacecraft architecture.

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
|    inject() stimuli API                                      |
+------+--------------------------------------+----------------+
       |                                      |
+------v--------------+            +----------v---------------+
|  SIMULATION MASTER  |            |   TEST PROCEDURES        |
|                     |            |   Python scripts         |
|  TickSource         |            |   svf_session fixture    |
|  SyncProtocol       |            |   observe().reaches()    |
|  ModelAdapter[]     |            |     .within()            |
+------+--------------+            |   inject(name, value)    |
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
|   [Spacecraft Bus]  [AOCS]  [OBDH]  [Environment]                  |
|   [Ground Segment Sim]  [Failure Injector]  [Sensor Models]         |
|          pythonfmu (Python FMUs)  |  C/C++ FMUs                     |
+------+------+------------------------------------------------------+
       |      |
+------v--+   +---v-------------------------------------------------+
|PARAMETER|   | COMMAND STORE                                       |
|STORE    |   |                                                     |
|         |   | CommandEntry(name, value, t, source_id, consumed)  |
| TM only |   | TC only — take() reads and marks consumed atomically|
|         |   |                                                     |
| written |   | written by: inject() API in test procedures         |
| by models   | read by: FmuModelAdapter, NativeModelAdapter        |
|         |   |                                                     |
| read by |   | future: PUS adapter, bus protocol adapters          |
| observables | (1553, CAN, I2C, UART, SpW, WizardLink)            |
+---------+   +-----------------------------------------------------+
       |
+------v--------------------------------------------------------------+
|              COMMUNICATION BUS (Cyclone DDS)                       |
|                                                                     |
|   SVF/Sim/Tick           <- simulation tick broadcasts              |
|   SVF/Sim/Ready/{id}     <- model acknowledgements                 |
|   SVF/Command/{variable} <- injected commands (deferred bridge)    |
|                                                                     |
|   plugin adapters: CCSDS/PUS | SpaceWire | 1553 | CAN | UART       |
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

The simulation master does not call models directly. Instead it broadcasts time ticks. Models process each tick, write outputs to the ParameterStore, read any pending commands from the CommandStore, and acknowledge readiness. The master waits for all acknowledgements before advancing.

```
Master                    Model A                 Model B
  |                          |                       |
  |--- tick(t=0.1) --------->|                       |
  |--- tick(t=0.1) --------------------------------->|
  |                          |                       |
  |                    read commands           read commands
  |                    doStep()               doStep()
  |                    write ParameterStore   write ParameterStore
  |                    publish_ready()        publish_ready()
  |                          |                       |
  |<-- ready(A, t=0.1) ------|                       |
  |<-- ready(B, t=0.1) --------------------------------|
  |                          |                       |
  |--- tick(t=0.2) --------->|                       |
```

### 4.2 TM/TC Separation

Mirroring real spacecraft architecture, telemetry and telecommands flow through separate stores:

| Store | Direction | Written by | Read by |
|---|---|---|---|
| ParameterStore | TM (outputs) | Model adapters | Observables, loggers, reporters |
| CommandStore | TC (inputs) | inject() API, future PUS adapter | Model adapters before each tick |

### 4.3 DDS Topic Naming Convention

| Topic | Direction | Payload |
|---|---|---|
| SVF/Sim/Tick | Master -> Models | SimTick(t, dt) |
| SVF/Sim/Ready/{model_id} | Model -> Master | SimReady(model_id, t) |
| SVF/Command/{variable} | Future bridge only | CommandSample(t, name, value) |

---

## 5. Abstraction Layer

The abstraction layer is the key to real-time readiness. The SimulationMaster depends only on three interfaces — never on concrete implementations.

### 5.1 TickSource

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

```python
class SyncProtocol(ABC):
    def wait_for_ready(self, expected: list[str], timeout: float) -> bool: ...
    def publish_ready(self, model_id: str, t: float) -> None: ...
    def reset(self) -> None: ...
```

| Implementation | When used |
|---|---|
| DdsSyncProtocol | Default — acknowledgements over DDS, KEEP_ALL QoS |
| SharedMemorySyncProtocol (deferred) | Lock-free ring buffer, sub-millisecond latency |

### 5.3 ModelAdapter

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
| FmuModelAdapter | Wraps FMI 3.0 FMU, reads CommandStore, writes ParameterStore |
| NativeModelAdapter | Wraps plain Python class for lightweight testing |
| Hardware adapter (deferred) | Bridges to physical interfaces |

### 5.4 Real-Time Upgrade Path

| Step | What changes | What stays the same |
|---|---|---|
| Soft RT (RT_PREEMPT kernel) | Nothing in code | Everything |
| Deterministic ticking | SoftwareTickSource -> RealtimeTickSource | Everything else |
| Low-latency sync | DdsSyncProtocol -> SharedMemorySyncProtocol | Everything else |
| HIL interface | New ModelAdapter for hardware bridge | Everything else |

---

## 6. ParameterStore & CommandStore

### 6.1 ParameterStore

Thread-safe central state store for simulation telemetry outputs.

```python
store.write(name, value, t, model_id)   # called by model adapters
store.read(name) -> ParameterEntry | None  # called by observables, loggers
store.snapshot() -> dict[str, ParameterEntry]  # called by reporters
```

The store holds the last written value for each parameter. Any reader connecting at any time sees the current value — the late-joiner problem is eliminated by design.

### 6.2 CommandStore

Thread-safe store for telecommands. Architecturally separate from the ParameterStore — TM and TC are never conflated.

```python
store.inject(name, value, t, source_id)   # called by test procedures
store.take(name) -> CommandEntry | None   # called by model adapters, atomic read+consume
store.peek(name) -> CommandEntry | None   # non-consuming read for inspection
```

`take()` is atomic — it reads and marks the command as consumed in a single operation. This prevents a command from being applied more than once across consecutive ticks.

### 6.3 Commanding Architecture

SVF commanding mirrors real spacecraft TC architecture:

```
Test procedure (ground operator)
    └── inject("thruster_cmd", 1.0)         [SVF inject() API today]
            └── CommandStore
                    └── FmuModelAdapter.on_tick()
                            └── take("thruster_cmd") -> CommandEntry
                            └── fmu.setReal(vr, entry.value)
                            └── fmu.doStep()

Future layers (deferred):
    inject_pus(service=8, subservice=1)     [PUS adapter]
        └── CommandStore
    1553_bus.send(addr, cmd)               [Bus protocol adapter]
        └── CommandStore
```

---

## 7. pytest Plugin

### 7.1 Simulation Lifecycle Fixture

```python
@pytest.mark.svf_stop_time(10.0)
@pytest.mark.svf_fmus([FmuConfig("models/power.fmu", "power")])
def test_power_model(svf_session):
    svf_session.observe("battery_voltage").exceeds(3.3).within(5.0)
    svf_session.inject("solar_panel_angle", 45.0)
```

| Mark | Default | Description |
|---|---|---|
| svf_fmus([FmuConfig(...)]) | SimpleCounter.fmu | FMUs to load |
| svf_dt(float) | 0.1 | Simulation timestep in seconds |
| svf_stop_time(float) | 2.0 | Simulation stop time in seconds |

### 7.2 Observable Assertion API

Polls the ParameterStore. Returns the value that satisfied the condition.

```python
svf_session.observe("counter").reaches(1.0).within(2.0)
svf_session.observe("voltage").exceeds(3.3).within(5.0)
svf_session.observe("temperature").drops_below(100.0).within(10.0)
svf_session.observe("status").satisfies(lambda v: v > 0).within(3.0)
```

`reaches(v)` means the parameter has reached at least v — timing robust against the ParameterStore holding only the last written value.

### 7.3 Stimuli Injection API (M3 — in progress)

Writes to the CommandStore. Model adapters consume commands before each tick.

```python
svf_session.inject("thruster_cmd", 1.0)
svf_session.inject("safe_mode_flag", 1.0, at_time=5.0)
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
| System description | SSP | Version-controllable wiring diagrams |
| Communication bus | Eclipse Cyclone DDS | Open source, QoS-rich, RTPS-based |
| Telemetry store | ParameterStore | Thread-safe, late-joiner safe, poll-based |
| Command store | CommandStore | TM/TC separation, atomic take() |
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
| M3 - pytest Plugin | svf_session, observable API, verdict mapper, ParameterStore, CommandStore | IN PROGRESS |
| M4 - First Real Model | Spacecraft power or thermal model, full stack validation | PENDING |
| M5 - Campaign & Reporting | YAML campaign loader, JUnit XML + traceability matrix | PENDING |

---

## 11. Out of Scope (Initial Version)

- Real-time / HIL execution
- SMP2 model import
- CCSDS/PUS command adapter
- Bus protocol adapters (1553, CAN, I2C, UART, SpaceWire, WizardLink)
- DOORS NG / Jama Connect integration
- Tool qualification (DO-178C, ECSS-E-ST-40C toolchain qualification)
- Multi-node distributed simulation
- GUI / visual modelling environment
- SharedMemorySyncProtocol
- RealtimeTickSource
- ParameterStoreDdsBridge
