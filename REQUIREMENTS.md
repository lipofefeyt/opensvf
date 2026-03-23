# SVF Development Requirements

> **Status:** Draft — v0.5
> **Last updated:** 2026-03
> **Author:** TBD

---

## Overview

This document defines the development requirements for the Software Validation Facility (SVF) platform itself. These are distinct from the requirements of any spacecraft system being validated using SVF — they describe what SVF must do and how it must behave as a tool.

Requirements are identified by the prefix `SVF-DEV-` followed by a zero-padded sequence number. Each requirement belongs to a functional area, indicated by the area tag in square brackets.

### Functional Areas

| Tag | Area |
|---|---|
| [SIM] | Simulation Core |
| [ABS] | Abstraction Layer |
| [BUS] | Communication Bus, Parameter Store & Command Store |
| [ORC] | Test Orchestration |
| [CAM] | Campaign Manager |
| [MOD] | Model Authoring |
| [REP] | Reporting & Traceability |
| [SYS] | System & Infrastructure |

### Requirement Status Values

| Status | Meaning |
|---|---|
| DRAFT | Under discussion, not yet baselined |
| BASELINED | Agreed and frozen for current milestone |
| IMPLEMENTED | Closed by a committed and merged implementation |
| DEFERRED | Out of scope for current milestone, retained for future |
| SUPERSEDED | Replaced by a later requirement |

---

## Simulation Core Requirements [SIM]

**SVF-DEV-001** `[SIM]` `IMPLEMENTED`
The simulation master shall support loading and instantiating FMUs compliant with the FMI 3.0 standard.

**SVF-DEV-002** `[SIM]` `IMPLEMENTED`
The simulation master shall support fixed-timestep execution of a single FMU.

**SVF-DEV-003** `[SIM]` `DRAFT`
The simulation master shall support variable-timestep execution where the FMU exposes a step-size negotiation interface.

**SVF-DEV-004** `[SIM]` `DRAFT`
The simulation master shall support co-simulation of multiple FMUs connected according to an SSP system description file.

**SVF-DEV-005** `[SIM]` `IMPLEMENTED`
The simulation master shall record all FMU output variables to a time-stamped CSV log for each simulation run.

**SVF-DEV-006** `[SIM]` `IMPLEMENTED`
The simulation master shall expose a clean start, step, and teardown lifecycle API consumable by the test orchestration layer.

**SVF-DEV-007** `[SIM]` `IMPLEMENTED`
The simulation master shall handle FMU initialisation errors gracefully and report them with sufficient detail to identify the failing FMU and variable.

**SVF-DEV-008** `[SIM]` `DEFERRED`
The simulation master shall support FMI 3.0 Scheduled Execution mode for deterministic clock-driven stepping (prerequisite for real-time support).

---

## Abstraction Layer Requirements [ABS]

**SVF-DEV-009** `[ABS]` `IMPLEMENTED`
The platform shall define a TickSource abstract interface with start() and stop() methods. All simulation timing shall be driven through this interface.

**SVF-DEV-010** `[ABS]` `IMPLEMENTED`
The platform shall provide a SoftwareTickSource implementation of TickSource that advances simulation time in a Python loop as fast as possible.

**SVF-DEV-011** `[ABS]` `IMPLEMENTED`
The platform shall define a SyncProtocol abstract interface with wait_for_ready(), publish_ready(), and reset() methods. All tick synchronisation shall be driven through this interface.

**SVF-DEV-012** `[ABS]` `IMPLEMENTED`
The platform shall provide a DdsSyncProtocol implementation of SyncProtocol that exchanges tick acknowledgements over DDS topics using KEEP_ALL QoS.

**SVF-DEV-013** `[ABS]` `IMPLEMENTED`
The platform shall define a ModelAdapter abstract interface with model_id, initialise(), on_tick(), and teardown(). on_tick() shall return None — data flows through the ParameterStore, faults flow as exceptions.

**SVF-DEV-014** `[ABS]` `IMPLEMENTED`
The platform shall provide an FmuModelAdapter implementation of ModelAdapter that wraps an FMI 3.0 FMU via fmpy, writes outputs to the ParameterStore, reads commands from the CommandStore, and calls publish_ready() after each tick.

**SVF-DEV-015** `[ABS]` `IMPLEMENTED`
The platform shall provide a NativeModelAdapter implementation of ModelAdapter that wraps a plain Python class. Output variable names shall be declared at construction time — never inferred by calling step() during initialise().

**SVF-DEV-016** `[ABS]` `IMPLEMENTED`
The SimulationMaster shall accept TickSource, SyncProtocol, and a list of ModelAdapters via constructor injection. It shall not depend on any concrete implementation. It shall never call publish_ready() on behalf of models.

**SVF-DEV-017** `[ABS]` `DEFERRED`
The platform shall provide a RealtimeTickSource implementation of TickSource driven by an RT_PREEMPT timer or external hardware sync pulse.

**SVF-DEV-018** `[ABS]` `DEFERRED`
The platform shall provide a SharedMemorySyncProtocol implementation of SyncProtocol using a lock-free ring buffer for sub-millisecond tick acknowledgement latency.

---

## Communication Bus, Parameter Store & Command Store Requirements [BUS]

**SVF-DEV-020** `[BUS]` `IMPLEMENTED`
The communication bus shall be implemented over Eclipse Cyclone DDS using the DDS publish/subscribe model for tick synchronisation.

**SVF-DEV-021** `[BUS]` `IMPLEMENTED`
The bus shall define a standard topic naming convention: SVF/Sim/Tick, SVF/Sim/Ready/{model_id}, SVF/Telemetry/{variable}, SVF/Command/{variable}.

**SVF-DEV-022** `[BUS]` `IMPLEMENTED`
The SimTick topic shall carry: simulation time t (float) and timestep dt (float).

**SVF-DEV-023** `[BUS]` `IMPLEMENTED`
The SimReady topic shall carry: model_id (bounded string) and acknowledged time t (float).

**SVF-DEV-024** `[BUS]` `SUPERSEDED`
The TelemetrySample DDS topic is superseded by the ParameterStore (SVF-DEV-031). DDS telemetry publishing is replaced by ParameterStore writes in all model adapters.

**SVF-DEV-025** `[BUS]` `BASELINED`
The CommandSample topic shall carry: time t (float), variable name (bounded string), and value (float).

**SVF-DEV-026** `[BUS]` `IMPLEMENTED`
All DDS writers and readers used for multi-model synchronisation shall use KEEP_ALL QoS to prevent message loss under concurrent publication.

**SVF-DEV-027** `[BUS]` `BASELINED`
The bus shall support deadline monitoring: flagging a topic as overdue if no sample has been received within a configured period.

**SVF-DEV-028** `[BUS]` `IMPLEMENTED`
The bus integration shall be implemented as a plugin, such that alternative transport backends can be substituted without modifying the simulation master or orchestration layers.

**SVF-DEV-029** `[BUS]` `DEFERRED`
A CCSDS adapter plugin shall bridge DDS topics to CCSDS APID-addressed TM/TC packet streams.

**SVF-DEV-030** `[BUS]` `DEFERRED`
A SpaceWire adapter plugin shall bridge DDS topics to SpaceWire logical address-routed packets.

**SVF-DEV-031** `[BUS]` `IMPLEMENTED`
The platform shall implement a thread-safe ParameterStore as the central state store for all simulation outputs. Models write to it after each tick. Observables and loggers read from it. No subscriber registration required.

**SVF-DEV-032** `[BUS]` `IMPLEMENTED`
Each ParameterStore entry shall carry: value (float), timestamp (float), and model_id (string).

**SVF-DEV-033** `[BUS]` `IMPLEMENTED`
The ParameterStore shall expose write(), read(), and snapshot() methods. read() shall return the last written value regardless of when the reader first calls it — eliminating the late-joiner problem by design.

**SVF-DEV-034** `[BUS]` `DEFERRED`
The platform shall provide an optional ParameterStoreDdsBridge that mirrors store values to SVF/Telemetry/{variable} DDS topics for external inspection tools and ground segment simulation. The bridge shall be read-only from the external perspective.

**SVF-DEV-035** `[BUS]` `BASELINED`
The platform shall implement a CommandStore separate from the ParameterStore. TM and TC shall be architecturally separate, mirroring spacecraft TM/TC separation. A model shall never read its own telemetry outputs as commands.

**SVF-DEV-036** `[BUS]` `BASELINED`
Each CommandEntry shall carry: name (string), value (float), simulation time t (float), source_id (string), and a consumed flag (bool). The take() method shall read and mark a command as consumed atomically, preventing double-application.

**SVF-DEV-037** `[BUS]` `DEFERRED`
The platform shall provide a PUS command adapter that formats and validates CCSDS/PUS telecommands (PUS services) before writing to the CommandStore. This adapter is the entry point for external ground-segment commanding.

**SVF-DEV-038** `[BUS]` `DEFERRED`
The platform shall provide bus protocol adapters (MIL-STD-1553, CAN, I2C, UART, SpaceWire, WizardLink) that bridge CommandStore entries to equipment model interfaces, reflecting the internal commanding architecture of real spacecraft.

---

## Test Orchestration Requirements [ORC]

**SVF-DEV-040** `[ORC]` `IMPLEMENTED`
The test orchestration layer shall be implemented as a pytest plugin registered as a pytest11 entry point, compatible with pytest 7.x and above.

**SVF-DEV-041** `[ORC]` `IMPLEMENTED`
The plugin shall provide an svf_session fixture that starts a SimulationMaster in a background thread before a test, and performs clean teardown after the test regardless of outcome.

**SVF-DEV-042** `[ORC]` `BASELINED`
The plugin shall provide a stimuli injection API allowing test procedures to write commands to the CommandStore, which model adapters consume before each tick.

**SVF-DEV-043** `[ORC]` `IMPLEMENTED`
The plugin shall provide an observable assertion API (observe().reaches().within()) that polls the ParameterStore until conditions are met or timeout expires. reaches(v) means the parameter has reached at least v.

**SVF-DEV-044** `[ORC]` `IMPLEMENTED`
The plugin shall map test outcomes to ECSS-compatible verdicts: PASS, FAIL, INCONCLUSIVE, and ERROR.

**SVF-DEV-045** `[ORC]` `BASELINED`
The plugin shall capture a full execution timeline for each test, recording timestamps of stimuli injection events, observable evaluations, and verdict assignment.

**SVF-DEV-046** `[ORC]` `DRAFT`
The orchestration layer shall support parallel test execution via pytest-xdist without requiring shared mutable simulation state between workers.

**SVF-DEV-047** `[ORC]` `IMPLEMENTED`
Each test procedure shall be expressible as a standalone Python file with no mandatory inheritance from SVF base classes.

---

## Campaign Manager Requirements [CAM]

**SVF-DEV-050** `[CAM]` `DRAFT`
The campaign manager shall accept test campaign definitions expressed in YAML format.

**SVF-DEV-051** `[CAM]` `DRAFT`
A campaign definition shall specify: a unique campaign identifier, a model configuration baseline identifier, a list of requirement IDs under verification, and an ordered list of test case references.

**SVF-DEV-052** `[CAM]` `DRAFT`
The campaign manager shall validate campaign YAML files against a published schema before execution, reporting all schema violations before any test is started.

**SVF-DEV-053** `[CAM]` `DRAFT`
The campaign manager shall record the campaign definition file, its SHA-256 hash, and the SVF version used as part of every campaign execution record.

**SVF-DEV-054** `[CAM]` `DRAFT`
The campaign manager shall support per-test-case timeout configuration, aborting and marking a test as ERROR if execution exceeds the defined timeout.

**SVF-DEV-055** `[CAM]` `DEFERRED`
The campaign manager shall support conditional test execution: skipping or including test cases based on the outcome of previously executed tests in the same campaign.

---

## Model Authoring Requirements [MOD]

**SVF-DEV-060** `[MOD]` `IMPLEMENTED`
The platform shall support FMUs authored in Python using the pythonfmu library as first-class simulation components.

**SVF-DEV-061** `[MOD]` `DRAFT`
The platform shall support FMUs authored in C or C++ compiled to shared libraries conforming to the FMI 3.0 binary interface.

**SVF-DEV-062** `[MOD]` `DRAFT`
The platform shall provide a Python decorator API (@svf.model, @svf.input, @svf.output, @svf.state) that generates FMI-compliant scaffolding with minimal boilerplate.

**SVF-DEV-063** `[MOD]` `DRAFT`
All SVF-native models shall produce FMI 3.0 compliant FMU archives, usable in any third-party FMI-compliant simulation environment.

**SVF-DEV-064** `[MOD]` `DEFERRED`
The platform shall provide an SMP2 model importer that converts SMP2-compliant model packages into FMI 3.0 FMUs.

---

## Reporting & Traceability Requirements [REP]

**SVF-DEV-070** `[REP]` `DRAFT`
The platform shall produce JUnit XML test result reports natively from pytest, consumable by Jenkins, GitLab CI, and GitHub Actions without additional configuration.

**SVF-DEV-071** `[REP]` `DRAFT`
The platform shall produce structured test records aligned with ECSS-E-ST-10-02C, including: test case ID, objective, configuration baseline, preconditions, execution steps, observations, and verdict.

**SVF-DEV-072** `[REP]` `DRAFT`
Each test case shall declare the requirement IDs it verifies, expressed as pytest markers and in the campaign YAML file.

**SVF-DEV-073** `[REP]` `DRAFT`
The reporting layer shall generate a requirements traceability matrix mapping each declared requirement ID to the test cases that verify it and their verdicts.

**SVF-DEV-074** `[REP]` `DRAFT`
All reports shall include the campaign ID, model configuration baseline, SVF version, and execution timestamp as header metadata.

**SVF-DEV-075** `[REP]` `DRAFT`
The platform shall produce an HTML report via Allure, rendered from the same structured data used for the ECSS certification report.

**SVF-DEV-076** `[REP]` `DEFERRED`
The platform shall provide an adapter for exporting traceability data to IBM DOORS NG via its REST API.

**SVF-DEV-077** `[REP]` `DEFERRED`
The platform shall provide an adapter for exporting traceability data to Jama Connect via its REST API.

---

## System & Infrastructure Requirements [SYS]

**SVF-DEV-080** `[SYS]` `IMPLEMENTED`
The SVF core shall be packaged as a pip-installable Python package using pyproject.toml.

**SVF-DEV-081** `[SYS]` `IMPLEMENTED`
The platform shall support Linux (Ubuntu 22.04 LTS and above) as the primary execution environment.

**SVF-DEV-082** `[SYS]` `DRAFT`
The platform shall support macOS (Monterey and above) as a secondary supported execution environment.

**SVF-DEV-083** `[SYS]` `DRAFT`
The platform shall support Windows 10 and above as a best-effort execution environment.

**SVF-DEV-084** `[SYS]` `DRAFT`
Each simulation run shall be executable inside a Docker container, with no dependency on host-installed software beyond Docker itself.

**SVF-DEV-085** `[SYS]` `DRAFT`
The build system for mixed Python/C components shall use CMake with scikit-build-core.

**SVF-DEV-086** `[SYS]` `DRAFT`
FMU binary artefacts shall be managed in Git with Git LFS.

**SVF-DEV-087** `[SYS]` `IMPLEMENTED`
The SVF codebase shall maintain a minimum test coverage of 80% on the orchestration and campaign manager layers, measured on every CI run.

**SVF-DEV-088** `[SYS]` `IMPLEMENTED`
The platform shall expose a public Python API with type annotations throughout, compatible with mypy strict mode.

**SVF-DEV-089** `[SYS]` `DEFERRED`
The platform shall support soft real-time execution on Linux hosts running the RT_PREEMPT kernel patch, with no changes required to model or test procedure code.

---

## Traceability Index

| Requirement ID | Area | Status | Verified By |
|---|---|---|---|
| SVF-DEV-001 | SIM | IMPLEMENTED | test_fmu_adapter_initialises |
| SVF-DEV-002 | SIM | IMPLEMENTED | test_simulation_master_with_fmu |
| SVF-DEV-003 | SIM | DRAFT | — |
| SVF-DEV-004 | SIM | DRAFT | — |
| SVF-DEV-005 | SIM | IMPLEMENTED | test_csv_logger_wired_to_fmu_adapter |
| SVF-DEV-006 | SIM | IMPLEMENTED | test_simulation_master_context_manager |
| SVF-DEV-007 | SIM | IMPLEMENTED | test_fmu_adapter_missing_fmu |
| SVF-DEV-008 | SIM | DEFERRED | — |
| SVF-DEV-009 | ABS | IMPLEMENTED | test_simulation_master_runs |
| SVF-DEV-010 | ABS | IMPLEMENTED | test_lockstep_single_fmu |
| SVF-DEV-011 | ABS | IMPLEMENTED | test_lockstep_sync_timeout |
| SVF-DEV-012 | ABS | IMPLEMENTED | test_lockstep_multiple_models |
| SVF-DEV-013 | ABS | IMPLEMENTED | test_native_adapter_step |
| SVF-DEV-014 | ABS | IMPLEMENTED | test_fmu_adapter_on_tick |
| SVF-DEV-015 | ABS | IMPLEMENTED | test_native_adapter_step |
| SVF-DEV-016 | ABS | IMPLEMENTED | test_simulation_master_runs |
| SVF-DEV-017 | ABS | DEFERRED | — |
| SVF-DEV-018 | ABS | DEFERRED | — |
| SVF-DEV-020 | BUS | IMPLEMENTED | test_lockstep_single_fmu |
| SVF-DEV-021 | BUS | IMPLEMENTED | test_lockstep_single_fmu |
| SVF-DEV-022 | BUS | IMPLEMENTED | test_lockstep_single_fmu |
| SVF-DEV-023 | BUS | IMPLEMENTED | test_lockstep_single_fmu |
| SVF-DEV-024 | BUS | SUPERSEDED | SVF-DEV-031 |
| SVF-DEV-025 | BUS | BASELINED | — |
| SVF-DEV-026 | BUS | IMPLEMENTED | test_lockstep_multiple_models |
| SVF-DEV-027 | BUS | BASELINED | — |
| SVF-DEV-028 | BUS | IMPLEMENTED | test_lockstep_single_fmu |
| SVF-DEV-029 | BUS | DEFERRED | — |
| SVF-DEV-030 | BUS | DEFERRED | — |
| SVF-DEV-031 | BUS | IMPLEMENTED | test_parameter_store_populated_after_run |
| SVF-DEV-032 | BUS | IMPLEMENTED | test_write_and_read |
| SVF-DEV-033 | BUS | IMPLEMENTED | test_late_reader_sees_value |
| SVF-DEV-034 | BUS | DEFERRED | — |
| SVF-DEV-035 | BUS | BASELINED | — |
| SVF-DEV-036 | BUS | BASELINED | — |
| SVF-DEV-037 | BUS | DEFERRED | — |
| SVF-DEV-038 | BUS | DEFERRED | — |
| SVF-DEV-040 | ORC | IMPLEMENTED | test_fixture_default_fmu |
| SVF-DEV-041 | ORC | IMPLEMENTED | test_fixture_default_fmu |
| SVF-DEV-042 | ORC | BASELINED | — |
| SVF-DEV-043 | ORC | IMPLEMENTED | test_observe_reaches |
| SVF-DEV-044 | ORC | IMPLEMENTED | test_verdict_pass |
| SVF-DEV-045 | ORC | BASELINED | — |
| SVF-DEV-046 | ORC | DRAFT | — |
| SVF-DEV-047 | ORC | IMPLEMENTED | test_fixture_default_fmu |
| SVF-DEV-050 | CAM | DRAFT | — |
| SVF-DEV-051 | CAM | DRAFT | — |
| SVF-DEV-052 | CAM | DRAFT | — |
| SVF-DEV-053 | CAM | DRAFT | — |
| SVF-DEV-054 | CAM | DRAFT | — |
| SVF-DEV-055 | CAM | DEFERRED | — |
| SVF-DEV-060 | MOD | IMPLEMENTED | validate_fmpy.py |
| SVF-DEV-061 | MOD | DRAFT | — |
| SVF-DEV-062 | MOD | DRAFT | — |
| SVF-DEV-063 | MOD | DRAFT | — |
| SVF-DEV-064 | MOD | DEFERRED | — |
| SVF-DEV-070 | REP | DRAFT | — |
| SVF-DEV-071 | REP | DRAFT | — |
| SVF-DEV-072 | REP | DRAFT | — |
| SVF-DEV-073 | REP | DRAFT | — |
| SVF-DEV-074 | REP | DRAFT | — |
| SVF-DEV-075 | REP | DRAFT | — |
| SVF-DEV-076 | REP | DEFERRED | — |
| SVF-DEV-077 | REP | DEFERRED | — |
| SVF-DEV-080 | SYS | IMPLEMENTED | CI pipeline |
| SVF-DEV-081 | SYS | IMPLEMENTED | CI pipeline (ubuntu-latest) |
| SVF-DEV-082 | SYS | DRAFT | — |
| SVF-DEV-083 | SYS | DRAFT | — |
| SVF-DEV-084 | SYS | DRAFT | — |
| SVF-DEV-085 | SYS | DRAFT | — |
| SVF-DEV-086 | SYS | DRAFT | — |
| SVF-DEV-087 | SYS | IMPLEMENTED | CI pipeline (pytest) |
| SVF-DEV-088 | SYS | IMPLEMENTED | CI pipeline (mypy) |
| SVF-DEV-089 | SYS | DEFERRED | — |