---
title: "OpenSVF  -  Architecture Description Document"
subtitle: "SVF-ADD-001 | Issue 1.0"
author: "Gonçalo Graças"
date: "2026-05-23"
subject: "Architecture Description Document"
keywords: [spacecraft, validation, PUS-C, FMI, SIL, ECSS]
lang: en
titlepage: true
titlepage-color: "1a1a2e"
titlepage-text-color: "EEEEEE"
titlepage-rule-color: "4a90d9"
titlepage-rule-height: 4
toc: true
toc-own-page: true
numbersections: true
colorlinks: true
linkcolor: "4a90d9"
fontsize: 11pt
geometry: "margin=2.5cm"
header-left: "SVF-ADD-001"
header-right: "OpenSVF Architecture Description Document"
footer-left: "Issue 1.0  -  2026-05-23"
footer-right: "Page \\thepage"
classoption: oneside
---

# Introduction

## Purpose

This document describes the software architecture of **OpenSVF**  -  an open-source
spacecraft Software Validation Facility. It is intended for engineers who need to:

- understand the structural decomposition and data flows in OpenSVF
- integrate a flight software binary (OBSW) with the SVF framework
- author new equipment models or campaign procedures
- extend the platform for new mission profiles

## Scope

This document covers the `opensvf` Python orchestration package (v0.7.1).
It references but does not internally document the following external components,
which are covered by their own technical documentation:

| Component | Scope boundary |
|---|---|
| `opensvf-kde` | C++/Eigen3 6-DOF physics FMU  -  FMI interface only |
| `openobsw` | C11 flight software  -  wire protocol interface only (see SVF-ICD-001) |
| YAMCS 5.12.6 | Ground station  -  XTCE MDB interface only |

## Applicable Documents

| Reference | Title |
|---|---|
| ECSS-E-ST-70-41C | Space Engineering  -  Telemetry and Telecommand Packet Utilisation |
| ECSS-E-HB-40A | Software Engineering Handbook |
| FMI 2.0 Specification | Functional Mock-up Interface for Model Exchange and Co-Simulation |
| SVF-ICD-001 | OpenSVF Interface Control Document |
| SVF-SVS-001 | OpenSVF Software Validation Specification |

## Terms and Abbreviations

| Term | Definition |
|---|---|
| ADD | Architecture Description Document |
| ADCS | Attitude Determination and Control System |
| FDIR | Failure Detection, Isolation, and Recovery |
| FMI | Functional Mock-up Interface |
| FMU | Functional Mock-up Unit |
| HIL | Hardware-In-the-Loop |
| ICD | Interface Control Document |
| KDE | Kinematics and Dynamics Engine |
| OBC | On-Board Computer |
| OBSW | On-Board Software |
| PUS | Packet Utilisation Standard |
| SRDB | Spacecraft Reference Database |
| SIL | Software-In-the-Loop |
| SVF | Software Validation Facility |
| TC | Telecommand |
| TM | Telemetry |
| XTCE | XML Telemetry and Command Exchange |

---

# System Overview

## Mission Statement

OpenSVF answers a single question:

> *Does the flight software behave correctly against real physics and a real ground station?*

It is not an AOCS design tool, a code generator, or a formal verification
platform. It produces validation evidence  -  structured test results traceable to
requirements  -  for spacecraft software teams that hand-code their flight algorithms.

## System Context

OpenSVF operates as the orchestration hub connecting four independent components
in a closed-loop simulation (Figure 1).

```
┌──────────────────────────────────────────────────────────┐
│  YAMCS 5.12.6  http://localhost:8090                     │
│  XTCE MDB: parameters, containers, commands              │
└──────────────────────┬───────────────────────────────────┘
                       │ PUS TM/TC via TCP/UDP
┌──────────────────────▼───────────────────────────────────┐
│  YamcsBridge + TtcEquipment (opensvf)                    │
└──────────────────────┬───────────────────────────────────┘
                       │ PUS bytes
┌──────────────────────▼───────────────────────────────────┐
│  OBCEmulatorAdapter  (opensvf)                           │
│  PIPE:   obsw_sim subprocess via stdin/stdout            │
│  SOCKET: Renode ZynqMP uart0 TCP:3456                    │
│  STUB:   ObcStub rule engine (no binary required)        │
└──────────────────────┬───────────────────────────────────┘
                       │ SVF Wire Protocol v3
┌──────────────────────▼───────────────────────────────────┐
│  openobsw  -  C11 flight software                          │
│  B-dot → MTQ dipoles | ADCS PD → RW torques             │
│  PUS S1/3/5/8/17/20  |  FDIR FSM                        │
└──────────────────────┬───────────────────────────────────┘
                       │ actuator commands → CommandStore
┌──────────────────────▼───────────────────────────────────┐
│  Bus Adapters (opensvf, optional)                        │
│  MIL-STD-1553B | SpaceWire+RMAP | CAN 2.0B (ECSS)       │
│  Fault injection: BUS_ERROR, NO_RESPONSE, BAD_PARITY     │
└──────────────────────┬───────────────────────────────────┘
                       │ torques
┌──────────────────────▼───────────────────────────────────┐
│  opensvf-kde FMU (C++ / Eigen3)                          │
│  6-DOF Euler equations, quaternion kinematics            │
│  Earth B-field model (dipole)                            │
│  OUT: true angular rate, true B-field, true quaternion   │
└──────────────────────┬───────────────────────────────────┘
                       │ true state → sensor models
┌──────────────────────▼───────────────────────────────────┐
│  Sensor Models (opensvf NativeEquipment)                 │
│  MAG | GYRO | ST | CSS | GPS | Thermal                   │
│  Noisy measurements → sensor frames → OBSW              │
└──────────────────────────────────────────────────────────┘
```

*Figure 1  -  Full system architecture. Arrows indicate primary data flow direction.*

## Validation Pyramid

OpenSVF supports four validation levels, each adding dependencies and scope:

| Level | Label | External Requirements | Scope |
|---|---|---|---|
| L1 | Unit | None | Equipment physics, bus logic, PUS packets, parameter stores |
| L2 | Integration | `SimpleCounter.fmu` | FMU wiring, `FmuEquipment` adapter, `SimulationMaster` |
| L3 | System (SIL) | `SpacecraftDynamics.fmu` + `obsw_sim` binary | Full software-in-the-loop with flight software |
| L4 | Campaign | Mission `spacecraft.yaml` | Operator procedures, HTML verdict report |

Continuous Integration covers L1 and L2 only. L3 and L4 require external
binaries (`SpacecraftDynamics.fmu` from opensvf-kde, `obsw_sim` from openobsw)
which are not committed to this repository.

---

# Architectural Decomposition

## Package Structure

```
src/svf/
├── core/           SimulationMaster, TickSource, SyncProtocol, Equipment ABC
├── config/         SpacecraftLoader, SpacecraftValidator, wiring resolver
├── models/         Equipment model library (NativeEquipment factories)
│   ├── aocs/       Magnetometer, Gyroscope, StarTracker, CSS, GPS,
│   │               Magnetorquer, ReactionWheel, BdotController, Thruster
│   ├── dynamics/   KdeEquipment (FmuEquipment adapter for SpacecraftDynamics.fmu)
│   ├── eps/        SolarArray, Battery, PCDU
│   ├── dhs/        ObcStub, OBCEmulatorAdapter, HilAdapter ABC
│   ├── ttc/        TtcEquipment, SBandTransponder
│   └── thermal/    ThermalModel
├── pus/            PUS-C packet builders and parsers (S1/3/5/8/17/20)
├── srdb/           SRDB loader, definitions (Dtype, Classification), YAML parser
├── campaign/       CampaignRunner, Procedure ABC, ProcedureContext, reporter
├── plugin/         pytest plugin: svf_session fixture, FmuConfig, markers
└── tools/          (excluded from mypy strict) generate_xtce.py, consistency checks
```

## Core Abstractions

`SimulationMaster` (`src/svf/core/`) drives deterministic fixed-step simulation
against three pluggable interfaces:

### TickSource

Controls the simulation clock. Two implementations:

- **`SoftwareTickSource`**  -  runs as fast as the CPU allows; used for CI, unit
  tests, and Monte Carlo sweeps
- **`RealtimeTickSource`**  -  aligns ticks to wall-clock time via `RT_PREEMPT`
  timer; required for hardware-in-the-loop with real equipment

`Equipment.suggested_dt()` may return a smaller step size than the configured
`dt`. `SimulationMaster._effective_dt()` resolves the minimum across all models,
enabling variable-timestep co-simulation.

### SyncProtocol

Coordinates tick acknowledgement between `SimulationMaster` and equipment models.
After completing a tick, each model signals readiness. Two implementations:

- **`DdsSyncProtocol`**  -  Eclipse Cyclone DDS; publishes on `SVF/Sim/Tick`,
  subscribes on `SVF/Sim/Ready/{model_id}` with `KEEP_ALL` QoS
- **`SharedMemorySyncProtocol`**  -  lock-free ring buffer for zero-copy
  inter-process synchronisation; required for real-time HIL

### Equipment

Base class for all simulation models. Two concrete subtypes:

- **`NativeEquipment`**  -  pure-Python closure; no compiled binary; used for all
  SVF reference models (sensors, actuators, bus adapters, EPS, thermal)
- **`FmuEquipment`**  -  FMI 2.0 co-simulation adapter; used for operator-supplied
  external physics and the `SpacecraftDynamics.fmu` from opensvf-kde

FMU binaries (`SimpleCounter.fmu`, `SpacecraftDynamics.fmu`) are committed to
`models/` at the repository root. `SimpleCounter.fmu` is a minimal test double
used exclusively for L2 integration tests of the `FmuEquipment` infrastructure.

---

# Data Model

## Parameter and Command Stores

All inter-model data exchange passes through two in-memory stores:

- **`ParameterStore`**  -  keyed telemetry values (TM parameters); models write
  OUT ports and read IN ports using SRDB canonical names
- **`CommandStore`**  -  keyed command values (TC parameters); commanding
  equipment writes here; controller models read commands

Store keys are **SRDB canonical parameter names** of the form
`domain.subsystem.parameter` (e.g. `aocs.mag1.field_x`, `dhs.obc.mode`).

## SRDB  -  Spacecraft Reference Database

The SRDB is the shared parameter contract between opensvf, openobsw, and YAMCS.
It is the single source of truth for:

- Canonical parameter names and domains
- Engineering units and valid ranges
- PUS service/subservice/parameter_id assignments
- XTCE MDB generation (via `tools/generate_xtce.py`)

Baseline definitions live in `srdb/baseline/*.yaml`  -  one file per subsystem domain:

| File | Domain |
|---|---|
| `aocs.yaml` | Attitude and Orbit Control |
| `dhs.yaml` | Data Handling System (OBC health, HK telemetry) |
| `eps.yaml` | Electrical Power System |
| `thermal.yaml` | Thermal Control |
| `ttc.yaml` | Tracking, Telemetry and Command |
| `obdh.yaml` | On-Board Data Handling (future OBDH subsystem) |

**PUS ID allocation** within APID 0x103 / S3(25):

| Range | Domain |
|---|---|
| 0x4001 – 0x400F | `dhs.*`  -  OBC health telemetry (current OBSW) |
| 0x4010 – 0x403F | `obdh.mode.*`  -  mode management |
| 0x4040 – 0x404F | `obdh.obc.*`  -  OBDH OBC health (future) |

## Auto-wiring

`src/svf/config/wiring.py` connects equipment OUT ports to IN ports automatically
when they share the same SRDB canonical name. Explicit overrides in
`spacecraft.yaml` handle non-standard connections (e.g. redundant sensors,
cross-strap configurations).

---

# OBC Integration Architecture

## HilAdapter ABC

`src/svf/models/dhs/hil_adapter.py` defines the `HilAdapter` abstract base class,
which is the plug-in point for the OBC. All three OBC modes implement this
interface identically; the selection is made by the `obsw.type` key in
`spacecraft.yaml`.

## Three OBC Modes

| Mode | Key | Implementation | Binary required |
|---|---|---|---|
| Software stub | `stub` | `ObcStub` rule engine | No |
| Pipe (SIL) | `pipe` | `OBCEmulatorAdapter` subprocess | `obsw_sim` |
| Socket (Renode) | `socket` | `OBCEmulatorAdapter` TCP | Renode + `obsw_zynqmp.bin` |

`ObcStub` implements a rule engine for quick functional tests without a compiled
binary. `OBCEmulatorAdapter` implements the full SVF Wire Protocol v3 (see
SVF-ICD-001) and is used for both pipe and socket modes.

## Wire Protocol v3

Communication between opensvf and openobsw uses type-prefixed binary frames over
stdin/stdout (pipe mode) or a TCP socket (socket mode). Every tick ends with a
`0xFF` synchronisation byte. Full frame definitions are specified in SVF-ICD-001.

## Desynchronisation Recovery

`OBCEmulatorAdapter` counts consecutive ticks where the `0xFF` sync byte is not
received. After `MAX_DESYNC = 3` consecutive missed syncs, a `RuntimeError` is
raised with the message "Lost sync". The desync counter resets to zero on any
tick where sync is achieved.

---

# Campaign Architecture

## Campaign Runner

`CampaignRunner` (`src/svf/campaign/`) loads a `campaign.yaml` file,
instantiates a spacecraft from `SpacecraftLoader`, and executes each `Procedure`
subclass in sequence. Each procedure receives a `ProcedureContext` that provides
time-advancing assertions and parameter injection.

## Procedure API

```python
from svf.procedure import Procedure, ProcedureContext

class BdotConvergence(Procedure):
    id          = "TC-AOCS-001"
    title       = "B-dot detumbling convergence"
    requirement = "MIS-AOCS-042"

    def run(self, ctx: ProcedureContext) -> None:
        self.step("Power on sensors")
        ctx.inject("aocs.mag.power_enable", 1.0)

        self.step("Wait for detumbling")
        ctx.wait(60.0)

        self.step("Verify convergence")
        ctx.assert_parameter("aocs.truth.rate_x", less_than=0.1)
```

Verdicts: `PASS` / `FAIL` / `INCONCLUSIVE` / `ERROR`. Each procedure is traced to
its requirement via the `requirement` class attribute.

## Reporting

`reporter.generate_html_report()` produces a self-contained HTML report (no CDN
dependencies) containing summary cards, per-procedure verdicts with step detail,
and a requirement coverage table.

---

# Test Architecture

## Two Test APIs

OpenSVF distinguishes two test APIs by validation level:

### L1/L2 pytest Tests (`tests/`)

Standard pytest test functions and classes. Class names must end in `Suite` or
`Tests` (non-default `python_classes` setting in `pyproject.toml`). Classes named
`TestFoo` are silently ignored.

- L2 integration tests use the `svf_session` pytest fixture and `FmuConfig`
  from `src/svf/plugin/fixtures.py`
- Decorated with `@pytest.mark.svf_fmus(...)`, `@pytest.mark.svf_dt(...)`, etc.
- Every test must carry `@pytest.mark.requirement("ID")` with an ID present in
  `REQUIREMENTS.md`

### L4 Campaign Procedures (`mission_mysat1/procedures/`)

Subclasses of `Procedure` (`src/svf/campaign/procedure.py`). Run via
`svf campaign <campaign.yaml>`, not via pytest. These are operator-level test
scripts  -  they exercise the full closed-loop system including the OBSW binary,
physics FMU, and YAMCS ground station.

## Traceability

The pytest plugin (`src/svf/plugin/__init__.py`) writes `results/traceability.txt`
after every `testosvf` run by collecting `@pytest.mark.requirement` markers.
`checkcov` (`tools/check_coverage.py`) cross-references this file against
`REQUIREMENTS.md` to report uncovered BASELINED requirements.

---

# Consistency Toolchain

## `checkcons`  -  Cross-Repository Consistency

`checkcons` (`tools/srdb_consistency_check.py`) runs seven automated checks
to detect divergence between the opensvf Python layer and the openobsw C layer:

| Check | What it detects |
|---|---|
| [1/7] Struct sizes | `_SENSOR_FMT` / `_ACTUATOR_FMT` drift from C struct byte count |
| [2/7] Python-side mapping | `obc_emulator.py` store keys diverging from parameter mapping table |
| [3/7] C struct fields | Field renames in openobsw not propagated to SVF packer |
| [4/7] Producer/consumer | Sensor model port renames producing silent zeros in the OBSW |
| [5/7] Requirement orphans | `@pytest.mark.requirement` IDs absent from `REQUIREMENTS.md` |
| [6/7] Profile symmetry | Mission hardware profiles missing from bundled directory |
| [7/7] SRDB namespace | Equipment OUT ports declared but absent from SRDB baseline |

The C struct check ([3/7]) accepts either a real openobsw checkout or a
gitingest snapshot file  -  the correct approach in single-workspace environments
where both repositories cannot coexist.

---

# Deployment Configurations

## Configuration by `obsw.type`

```yaml
# spacecraft.yaml  -  select OBC mode
obsw:
  type: stub    # No binary; uses ObcStub rule engine
  type: pipe    # SIL: runs obsw_sim as subprocess
  type: socket  # Renode: connects to TCP localhost:3456
```

## Hardware Profile Resolution

Equipment physics constants are overridden by hardware profiles  -  YAML files
specifying sensor noise figures, actuator performance parameters, and thermal
properties. Profile search order:

1. Explicit `hardware_dir` argument in `spacecraft.yaml`
2. Bundled `mission_mysat1/hardware_profiles/` (always available)
3. `obsw-srdb` Python package (if installed)

## YAMCS Ground Station

The XTCE Mission Database is generated from the SRDB by
`tools/generate_xtce.py` and committed to `yamcs/mdb/opensvf.xml`. TM downlink
uses TCP port 10015; TC uplink uses UDP port 10025. The YAMCS web UI is
accessible at `http://localhost:8090` (credentials: `admin` / `password`).

---

# Error Handling

## Equipment Tick Errors

When an equipment model raises an exception during a simulation tick,
`SimulationMaster` wraps it in an `EquipmentTickError` and dispatches it to the
configured `on_tick_error` handler.

| Field | Type | Description |
|---|---|---|
| `equipment_id` | `str` | The failing model's identifier |
| `obt` | `float` | On-board time at fault (seconds) |
| `cause` | `Exception` | Original exception raised by the model |
| `context` | `dict` | Structured dict with type and message |

Default behaviour: re-raise as `SimulationError` (abort the run). The handler
can be replaced at construction time to implement record-and-continue or
domain-specific abort logic.

## Pre-flight Validation

`svf validate <spacecraft.yaml>` runs `SpacecraftValidator` before any
simulation infrastructure is instantiated. It catches:

- Duplicate equipment IDs
- Bus address conflicts (CAN node-id, SpaceWire logical address, 1553 RT address)
- Wiring overrides referencing non-existent equipment IDs or ports
- Missing or malformed OBT parameter files

---

# Design Principles

## SRDB as the Shared Contract

Every inter-component parameter has one canonical name defined in the SRDB. The
OBSW, SVF, and YAMCS all use the same names. A parameter rename in the SRDB
breaks the build  -  intentionally. This property is enforced by `checkcons` checks
[2/7] and [4/7].

## Equipment as the Universal Abstraction

`SimulationMaster` does not distinguish between a Python sensor model, a C++ FMU,
or a real C OBSW binary. All are `Equipment` instances. Only the `spacecraft.yaml`
wiring changes between configurations.

## Determinism by Default

Every run is fully reproducible. Per-model seeds are derived deterministically
from a master seed via SHA-256. Non-deterministic models require explicit seed
injection  -  this is a deliberate design choice for a flight software validation
platform where non-reproducible test failures are unacceptable.

---

# Milestone Summary

| Milestone | Description | Status |
|---|---|---|
| M1–M12 | Core platform through ground segment | Done |
| M13 | SIL attitude loop closure | Done |
| M14 | Real-time and HIL, Renode socket, variable timestep | Done |
| M15 | Extended bus protocols (SpaceWire, CAN) | Done |
| M16 | SRDB maturity | Done |
| M17 | Equipment configurability | Done |
| M18 | Architecture refactor | Done |
| M19 | Spacecraft configuration DSL | Done |
| M20 | Structured test procedure API | Done |
| M21 | Mission-level results reporting | Done |
| M22 | OBSW integration guide | Done |
| M23 | Temporal assertions, equipment fault engine | Done |
| M24 | ZynqMP SIL (aarch64 QEMU + Renode socket) | Done |
| M25 | YAMCS ground segment integration | Done |
| M26 | EPS/AOCS/thermal native models, test pyramid restructure | Done |
| M29 | Time-tagged parameter init file (OBT startup state) | Done |
| M30 | CAN 2.0B full validation, SpaceWire RMAP completion | Done |
| M31 | Equipment fidelity levels, SRDB calibration curves | Done |
| M32 | SpacecraftValidator pre-flight config check | Done |
| M33 | SRDB namespace linting (`checkcons` [7/7]) | Done |
| M34 | Equipment fidelity coverage in `checkcov` | Done |
| M35 | `EquipmentTickError` and `on_tick_error` callback | Done |
