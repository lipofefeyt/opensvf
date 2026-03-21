# SVF Architecture

> **Status:** Draft — v0.1  
> **Last updated:** 2026-03  
> **Author:** TBD

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

**CI/CD compatibility.** All outputs (test verdicts, reports, traceability records) are consumable by standard CI/CD pipelines. SVF fits into existing developer workflows, it does not replace them.

---

## 3. Layered Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                    CAMPAIGN MANAGER                          │
│            YAML/TOML test campaign definitions               │
│         requirements traceability  |  config baseline        │
└───────────────────────┬──────────────────────────────────────┘
                        │
┌───────────────────────▼──────────────────────────────────────┐
│                  TEST ORCHESTRATOR                           │
│               pytest core + custom plugins                   │
│        fixtures | verdict engine | timeline recorder         │
└──────┬──────────────────────────────────────┬────────────────┘
       │                                      │
┌──────▼──────────────┐            ┌──────────▼───────────────┐
│  SIMULATION MASTER  │            │   TEST PROCEDURES        │
│  fmpy + SSP         │            │   Python scripts         │
│  time-step control  │            │   stimuli injection      │
│  event handling     │            │   observable assertions  │
└──────┬──────────────┘            └──────────────────────────┘
       │
┌──────▼──────────────────────────────────────────────────────┐
│                    FMU ECOSYSTEM                            │
│   [Spacecraft Bus]  [AOCS]  [OBDH]  [Environment]          │
│   [Ground Segment Sim]  [Failure Injector]  [Sensor Models] │
│          pythonfmu (Python FMUs)  |  C/C++ FMUs             │
└──────┬──────────────────────────────────────────────────────┘
       │
┌──────▼──────────────────────────────────────────────────────┐
│              COMMUNICATION BUS (Cyclone DDS)                │
│    TM/TC channels  |  telemetry streams  |  events          │
│    plugin adapters: CCSDS | SpaceWire | custom EGSE         │
└──────┬──────────────────────────────────────────────────────┘
       │
┌──────▼──────────────────────────────────────────────────────┐
│              REPORTING & TRACEABILITY                       │
│     JUnit XML  |  Allure HTML  |  ECSS verdict records      │
│     requirements linkage  |  full timeline export           │
└──────────────────────────────────────────────────────────────┘
```

---

## 4. Layer Descriptions

### 4.1 Simulation Core — FMI 3.0 + SSP

The simulation core is built around the **Functional Mock-up Interface (FMI) 3.0** standard (Modelica Association). FMI is the architectural centre of the platform.

Key reasons for this choice:
- Open standard with broad industry adoption (aerospace, automotive, energy)
- Models from MATLAB/Simulink, OpenModelica, Dymola and others export as FMUs and plug in without modification
- FMI 3.0 Scheduled Execution mode provides the foundation for future real-time support
- FMI 3.0 adds arrays, binary variables, and clocks — all relevant for spacecraft modelling

The Python library **fmpy** is used to load, instantiate, and step FMUs. The Simulation Master is a Python-implemented FMI Master Algorithm (MA) on top of fmpy.

**SSP (System Structure and Parameterization)** is used for describing FMU interconnections. SSP files are version-controllable and allow subsystem models to be swapped between campaigns without changing test logic.

For model authoring, **pythonfmu** allows models to be written as Python classes with minimal boilerplate — low barrier to entry for the initial model library. Performance-critical models are written in C and compiled to native FMUs.

### 4.2 Communication Bus — Eclipse Cyclone DDS

Eclipse Cyclone DDS (Apache 2.0) is the internal communication backbone, replacing the ISIS-style messaging layer.

DDS (OMG standard) provides publish/subscribe with rich QoS policies. For aerospace this is directly useful: reliable vs best-effort delivery, telemetry history windows, and deadline monitoring (flagging missing packets) all map naturally onto spacecraft TM/TC behaviour.

The Python bindings (`cyclonedds-python`) are used for orchestration-side integration. Plugin adapters at this layer later bridge DDS topics to CCSDS APID streams, SpaceWire packets, or serial EGSE protocols — without touching anything above.

Cyclone DDS is also the backbone of ROS2, giving it broad real-world validation. Its RTPS wire protocol is deterministic-capable, which is relevant for the future real-time path.

### 4.3 Test Orchestration — pytest + Custom Plugins

**pytest** is the base test runner. This avoids building a custom runner and gives users immediate compatibility with fixtures, parametrize, markers, parallel execution (pytest-xdist), and JUnit XML output.

Custom plugins and fixtures built on top of pytest:

- **Simulation lifecycle fixture** — starts the simulation master, waits for initialisation, tears down cleanly, captures the full execution timeline
- **Verdict engine** — maps pytest outcomes to ECSS verdicts (PASS, FAIL, INCONCLUSIVE, ERROR)
- **Observable assertions** — a DSL for time-bounded telemetry assertions (e.g. "parameter X shall reach value Y within 500ms of command injection")
- **Stimuli injector** — clean API to inject commands, failure modes, or environment changes via DDS

### 4.4 Campaign Manager

Test campaigns are defined in YAML files. A campaign file specifies: which test cases to run, in what order, against which model configuration baseline, with which parameters. Campaign files are versioned artefacts — they form the traceable link between requirements and test execution.

Example campaign structure:

```yaml
campaign:
  id: SVF-CAMP-2026-042
  baseline: spacecraft_model_v1.3.2
  requirements:
    - REQ-AOCS-045
    - REQ-POWER-012
  tests:
    - id: TC-AOCS-001
      procedure: tests/aocs/safe_mode_transition.py
      timeout: 120s
```

### 4.5 Reporting & Traceability

Two output streams:

**CI/CD stream** — JUnit XML natively from pytest, directly consumable by Jenkins, GitLab CI, and GitHub Actions. This is the primary adoption mechanism for modern NewSpace pipelines.

**Certification stream** — Structured reports aligned with ECSS-E-ST-10-02C test records: test case ID, objective, configuration baseline, preconditions, steps, observations, verdict. Allure provides the HTML rendering layer; an ECSS exporter sits on top.

Requirements traceability is first-class. Test cases declare which requirement IDs they verify (via YAML campaign files and pytest markers). Reports generate a traceability matrix automatically. Future adapters will integrate with DOORS NG and Jama Connect.

---

## 5. Technology Stack Summary

| Concern | Choice | Rationale |
|---|---|---|
| Simulation standard | FMI 3.0 | Open, widely adopted, real-time ready |
| Simulation library | fmpy | Mature Python FMI implementation |
| Model authoring | pythonfmu (Python), C FMUs | Low barrier, FMI-compliant output |
| System description | SSP | Version-controllable wiring diagrams |
| Communication bus | Eclipse Cyclone DDS | Open source, QoS-rich, RTPS-based |
| Test runner | pytest + custom plugins | Ecosystem, CI compatibility, extensibility |
| Build system | CMake + scikit-build-core | Mixed C/Python project support |
| Packaging | pyproject.toml | pip-installable core |
| Containerisation | Docker | Parallel execution, cloud-scalable |
| Configuration | TOML (system), YAML (campaigns) | Structured config vs human-authored content |

---

## 6. Model Authoring Philosophy

The developer experience for model authoring follows a Python-first approach that compiles down to FMUs:

```python
@svf.model
class PowerModel:
    solar_input: svf.input(float)
    battery_voltage: svf.output(float)
    charge_level: svf.state(float, initial=0.8)

    def step(self, dt):
        ...
```

This is deliberately lower friction than the SMP2 approach (XML modelling language → code generator → compiled library), while producing the same interoperable FMU artefact at the boundary. An SMP2 importer is a future plugin option for customers with existing model libraries.

---

## 7. Real-Time Roadmap

Real-time support is explicitly deferred but the architecture is designed to accommodate it without surgery. The upgrade path is additive:

1. **Soft real-time** — RT Linux kernel (RT_PREEMPT patch) on the simulation host. No software changes required.
2. **Deterministic stepping** — FMI 3.0 Scheduled Execution mode replaces the free-running master algorithm with clock-driven stepping.
3. **Low-latency bus** — Cyclone DDS with RT Linux scheduling policies reaches sub-millisecond latency.
4. **HIL interface** — a hardware bridge from DDS topics to physical interfaces (SpaceWire card, CAN bus, etc.). This is where the majority of HIL-specific effort sits.

Each step is independent and does not require changes to the layers above it.

---

## 8. Development Milestones

| Milestone | Objective |
|---|---|
| M1 — Simulation Master | fmpy stepping a single FMU, variable outputs logged to CSV |
| M2 — DDS Integration | Cyclone DDS publishing FMU outputs as typed topics |
| M3 — pytest Plugin | Simulation lifecycle fixture, verdict engine |
| M4 — First Real Model | Spacecraft power or thermal model, full stack validation |
| M5 — Campaign & Reporting | YAML campaign loader, JUnit XML + traceability matrix output |

---

## 9. Out of Scope (Initial Version)

- Real-time / HIL execution
- SMP2 model import
- DOORS NG / Jama Connect integration
- Tool qualification (DO-178C, ECSS-E-ST-40C toolchain qualification)
- Multi-node distributed simulation
- GUI / visual modelling environment
