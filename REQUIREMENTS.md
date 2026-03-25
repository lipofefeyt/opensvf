# SVF Development Requirements

> **Status:** Draft — v0.8
> **Last updated:** 2026-03
> **Author:** lipofefeyt

---

## Overview

This document defines the development requirements for the Software Validation Facility (SVF) platform itself and for the spacecraft models validated by SVF.

Requirements are identified by a prefix followed by a zero-padded sequence number. Each requirement belongs to a functional area indicated by the area tag in square brackets.

### Functional Areas

| Tag | Area |
|---|---|
| [SIM] | Simulation Core |
| [ABS] | Abstraction Layer |
| [BUS] | Communication Bus, Parameter Store & Command Store |
| [SDB] | Spacecraft Reference Database (SRDB) |
| [EQP] | Generic Equipment Contract |
| [EPS] | EPS Spacecraft Models |
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

**SVF-DEV-004** `[SIM]` `IMPLEMENTED`
The SimulationMaster shall accept an optional WiringMap defining connections between equipment OUT ports and IN ports. After each tick the master shall copy OUT port values to connected IN ports via CommandStore. Wiring shall be validated at run() time before the first tick.

**SVF-DEV-004b** `[SIM]` `DEFERRED`
The SimulationMaster shall support SSP (System Structure and Parameterization) files as an alternative to programmatic wiring maps. Assigned to M4.5.

**SVF-DEV-005** `[SIM]` `IMPLEMENTED`
The simulation master shall record all FMU output variables to a time-stamped CSV log for each simulation run.

**SVF-DEV-006** `[SIM]` `IMPLEMENTED`
The simulation master shall expose a clean start, step, and teardown lifecycle API consumable by the test orchestration layer.

**SVF-DEV-007** `[SIM]` `IMPLEMENTED`
The simulation master shall handle FMU initialisation errors gracefully and report them with sufficient detail to identify the failing FMU and variable.

**SVF-DEV-008** `[SIM]` `DEFERRED`
The simulation master shall support FMI 3.0 Scheduled Execution mode for deterministic clock-driven stepping.

---

## Abstraction Layer Requirements [ABS]

**SVF-DEV-009** `[ABS]` `IMPLEMENTED`
The platform shall define a TickSource abstract interface with start() and stop() methods.

**SVF-DEV-010** `[ABS]` `IMPLEMENTED`
The platform shall provide a SoftwareTickSource implementation of TickSource.

**SVF-DEV-011** `[ABS]` `IMPLEMENTED`
The platform shall define a SyncProtocol abstract interface with wait_for_ready(), publish_ready(), and reset() methods.

**SVF-DEV-012** `[ABS]` `IMPLEMENTED`
The platform shall provide a DdsSyncProtocol implementation of SyncProtocol using KEEP_ALL QoS.

**SVF-DEV-013** `[ABS]` `IMPLEMENTED`
The platform shall define a ModelAdapter abstract interface. Equipment extends ModelAdapter so every equipment model is directly driveable by SimulationMaster.

**SVF-DEV-014** `[ABS]` `IMPLEMENTED`
The platform shall provide FmuEquipment wrapping an FMI 3.0 FMU as Equipment.

**SVF-DEV-015** `[ABS]` `IMPLEMENTED`
The platform shall provide NativeEquipment wrapping a Python step function as Equipment.

**SVF-DEV-016** `[ABS]` `IMPLEMENTED`
The SimulationMaster shall accept TickSource, SyncProtocol, and a list of ModelAdapters via constructor injection.

**SVF-DEV-017** `[ABS]` `DEFERRED`
The platform shall provide a RealtimeTickSource driven by RT_PREEMPT timer.

**SVF-DEV-018** `[ABS]` `DEFERRED`
The platform shall provide a SharedMemorySyncProtocol using a lock-free ring buffer.

---

## Communication Bus, Parameter Store & Command Store Requirements [BUS]

**SVF-DEV-020** `[BUS]` `IMPLEMENTED`
The communication bus shall be implemented over Eclipse Cyclone DDS for tick synchronisation.

**SVF-DEV-021** `[BUS]` `IMPLEMENTED`
The bus shall define a standard topic naming convention: SVF/Sim/Tick, SVF/Sim/Ready/{model_id}.

**SVF-DEV-022** `[BUS]` `IMPLEMENTED`
The SimTick topic shall carry: simulation time t (float) and timestep dt (float).

**SVF-DEV-023** `[BUS]` `IMPLEMENTED`
The SimReady topic shall carry: model_id (bounded string) and acknowledged time t (float).

**SVF-DEV-024** `[BUS]` `SUPERSEDED`
Superseded by SVF-DEV-031. DDS telemetry publishing replaced by ParameterStore writes.

**SVF-DEV-025** `[BUS]` `DEFERRED`
The CommandSample topic shall carry: time t (float), variable name (bounded string), and value (float).

**SVF-DEV-026** `[BUS]` `IMPLEMENTED`
All DDS writers and readers for synchronisation shall use KEEP_ALL QoS.

**SVF-DEV-027** `[BUS]` `DEFERRED`
The bus shall support deadline monitoring.

**SVF-DEV-028** `[BUS]` `IMPLEMENTED`
The bus integration shall be implemented as a plugin.

**SVF-DEV-029** `[BUS]` `DEFERRED`
A CCSDS adapter plugin shall bridge DDS topics to CCSDS APID-addressed TM/TC streams.

**SVF-DEV-030** `[BUS]` `DEFERRED`
A SpaceWire adapter plugin shall bridge DDS topics to SpaceWire packets.

**SVF-DEV-031** `[BUS]` `IMPLEMENTED`
The platform shall implement a thread-safe ParameterStore as the central state store for all simulation outputs.

**SVF-DEV-032** `[BUS]` `IMPLEMENTED`
Each ParameterStore entry shall carry: value (float), timestamp (float), and model_id (string).

**SVF-DEV-033** `[BUS]` `IMPLEMENTED`
The ParameterStore shall expose write(), read(), and snapshot() methods. read() returns the last written value regardless of when the reader connects.

**SVF-DEV-034** `[BUS]` `DEFERRED`
The platform shall provide an optional ParameterStoreDdsBridge for external inspection tools.

**SVF-DEV-035** `[BUS]` `IMPLEMENTED`
The platform shall implement a CommandStore separate from the ParameterStore.

**SVF-DEV-036** `[BUS]` `IMPLEMENTED`
Each CommandEntry shall carry: name, value, t, source_id, consumed flag. take() shall be atomic.

**SVF-DEV-037** `[BUS]` `DEFERRED`
The platform shall provide a PUS command adapter for CCSDS/PUS telecommands.

**SVF-DEV-038** `[BUS]` `DEFERRED`
The platform shall provide bus protocol adapters (1553, CAN, I2C, UART, SpaceWire, WizardLink).

---

## Spacecraft Reference Database Requirements [SDB]

**SVF-DEV-090** `[SDB]` `IMPLEMENTED`
The platform shall implement a ParameterDefinition schema covering: name, description, unit, dtype, valid_range, classification (TM/TC), domain, model_id, and PUS mapping.

**SVF-DEV-091** `[SDB]` `IMPLEMENTED`
The platform shall provide YAML baseline parameter definitions for EPS, AOCS, TTC, OBDH, and Thermal domains.

**SVF-DEV-092** `[SDB]` `IMPLEMENTED`
The platform shall provide an SrdbLoader that parses YAML into typed ParameterDefinition objects with schema validation.

**SVF-DEV-093** `[SDB]` `IMPLEMENTED`
The SRDB shall support mission-level YAML overrides. Classification (TM/TC) cannot be changed by mission overrides.

**SVF-DEV-094** `[SDB]` `IMPLEMENTED`
The ParameterStore shall optionally accept an Srdb instance and warn when values fall outside valid_range.

**SVF-DEV-095** `[SDB]` `IMPLEMENTED`
The platform shall warn when a model writes to a TC-classified parameter or a test procedure injects to a TM-classified parameter.

**SVF-DEV-096** `[SDB]` `DEFERRED`
The SRDB shall support raw-to-engineering calibration definitions.

**SVF-DEV-097** `[SDB]` `DEFERRED`
The platform shall provide an XTCE 1.2 export adapter.

**SVF-DEV-098** `[SDB]` `DEFERRED`
The platform shall provide a MIB import adapter.

---

## Generic Equipment Contract Requirements [EQP]

These requirements define the contract that every Equipment implementation must satisfy, regardless of type (FMU, native Python, or future hardware).

**EQP-001** `[EQP]` `BASELINED`
Equipment shall declare all ports via _declare_ports() before initialise() is called. Port declaration occurs in __init__(). Duplicate port names shall raise ValueError.

**EQP-002** `[EQP]` `BASELINED`
Equipment.write_port() shall only accept OUT-direction ports. Calling write_port() on an IN port shall raise ValueError.

**EQP-003** `[EQP]` `BASELINED`
Equipment.read_port() shall accept any declared port. Calling read_port() on an undeclared port shall raise ValueError.

**EQP-004** `[EQP]` `BASELINED`
Equipment.receive() shall only accept IN-direction ports. Calling receive() on an OUT port shall raise ValueError.

**EQP-005** `[EQP]` `BASELINED`
Equipment.on_tick() shall read CommandStore entries into IN ports before calling do_step(). Each IN port name is used as the CommandStore key.

**EQP-006** `[EQP]` `BASELINED`
Equipment.on_tick() shall write all OUT port values to ParameterStore after do_step() completes. The ParameterStore key shall be the port name.

**EQP-007** `[EQP]` `BASELINED`
Equipment.on_tick() shall call SyncProtocol.publish_ready() after ParameterStore writes. The master shall never call publish_ready() on behalf of equipment.

**EQP-008** `[EQP]` `BASELINED`
FmuEquipment shall translate FMU variable names to port names via an optional parameter_map. If no mapping exists for a variable, the raw FMU name shall be used as the port name.

**EQP-009** `[EQP]` `BASELINED`
FmuEquipment.do_step() shall apply all IN port values to FMU input variables before calling fmu.doStep(). FMU output values shall be read into OUT ports after doStep() returns.

**EQP-010** `[EQP]` `BASELINED`
NativeEquipment shall call step_fn(equipment, t, dt) on each tick. The step function receives the equipment instance as first argument so it can call read_port() and write_port().

**EQP-011** `[EQP]` `BASELINED`
All port values shall default to 0.0 before the first write or receive. Equipment shall never raise on reading an unwritten port.

**EQP-012** `[EQP]` `BASELINED`
Equipment.teardown() shall be safe to call even if initialise() was never called.

---

## EPS Spacecraft Model Requirements [EPS]

These requirements define the expected behaviour of the EPS spacecraft models. They are verified by the spacecraft-level test procedures in tests/spacecraft/.

### Solar Array

**EPS-001** `[EPS]` `BASELINED`
SolarArrayFmu shall produce generated_power proportional to solar_illumination: generated_power = solar_illumination * MAX_POWER_W * PANEL_EFFICIENCY.

**EPS-002** `[EPS]` `BASELINED`
SolarArrayFmu shall produce generated_power = 0.0 when solar_illumination = 0.0 (eclipse).

**EPS-003** `[EPS]` `BASELINED`
SolarArrayFmu shall produce generated_power = MAX_POWER_W * PANEL_EFFICIENCY when solar_illumination = 1.0 (full sun).

### Battery

**EPS-004** `[EPS]` `BASELINED`
BatteryFmu battery_soc shall decrease over time when charge_current is negative (discharge).

**EPS-005** `[EPS]` `BASELINED`
BatteryFmu battery_soc shall increase over time when charge_current is positive (charge).

**EPS-006** `[EPS]` `BASELINED`
BatteryFmu battery_voltage shall follow a non-linear SoC curve in the range 3.0V to 4.2V.

**EPS-007** `[EPS]` `BASELINED`
BatteryFmu battery_soc shall never fall below SOC_MIN (0.05) or exceed SOC_MAX (1.0).

### PCDU

**EPS-008** `[EPS]` `BASELINED`
PcduFmu shall produce positive charge_current when generated_power exceeds load_power.

**EPS-009** `[EPS]` `BASELINED`
PcduFmu shall produce negative charge_current when load_power exceeds generated_power.

**EPS-010** `[EPS]` `BASELINED`
PcduFmu bus_voltage shall equal battery_voltage (simplified — no active regulation).

### Integrated EPS

**EPS-011** `[EPS]` `BASELINED`
The integrated EpsFmu shall charge the battery when solar_illumination = 1.0 and load_power = 30W. battery_soc shall exceed 0.88 within 120 simulated seconds starting from soc = 0.8.

**EPS-012** `[EPS]` `BASELINED`
The integrated EpsFmu shall discharge the battery when solar_illumination = 0.0 and load_power = 30W. battery_soc shall drop below 0.75 within 120 simulated seconds starting from soc = 0.8.

**EPS-013** `[EPS]` `BASELINED`
The integrated EpsFmu bus_voltage shall remain above 3.0V at all times during normal operation.

### Decomposed EPS

**EPS-014** `[EPS]` `BASELINED`
The decomposed EPS (SolarArray + Battery + PCDU connected via WiringMap) shall charge the battery when solar_illumination = 1.0 and load_power = 30W. battery_soc shall increase from initial value within 120 simulated seconds.

**EPS-015** `[EPS]` `BASELINED`
The decomposed EPS shall discharge the battery when solar_illumination = 0.0 and load_power = 30W. battery_soc shall decrease from initial value within 120 simulated seconds.

**EPS-016** `[EPS]` `BASELINED`
The decomposed EPS generated_power shall be 0.0 in eclipse and approximately 90W in full sun — consistent with integrated EPS behaviour.

---

## Test Orchestration Requirements [ORC]

**SVF-DEV-040** `[ORC]` `IMPLEMENTED`
The test orchestration layer shall be implemented as a pytest plugin registered as a pytest11 entry point.

**SVF-DEV-041** `[ORC]` `IMPLEMENTED`
The plugin shall provide an svf_session fixture that starts a SimulationMaster in a background thread before a test and tears down cleanly after.

**SVF-DEV-042** `[ORC]` `IMPLEMENTED`
The plugin shall provide a stimuli injection API (svf_session.inject()) writing to the CommandStore.

**SVF-DEV-043** `[ORC]` `IMPLEMENTED`
The plugin shall provide an observable assertion API polling the ParameterStore until conditions are met or timeout expires.

**SVF-DEV-044** `[ORC]` `IMPLEMENTED`
The plugin shall map test outcomes to ECSS-compatible verdicts: PASS, FAIL, INCONCLUSIVE, ERROR.

**SVF-DEV-045** `[ORC]` `DEFERRED`
The plugin shall capture a full execution timeline for each test.

**SVF-DEV-046** `[ORC]` `DRAFT`
The orchestration layer shall support parallel test execution via pytest-xdist.

**SVF-DEV-047** `[ORC]` `IMPLEMENTED`
Each test procedure shall be expressible as a standalone Python file with no mandatory inheritance from SVF base classes.

**SVF-DEV-048** `[ORC]` `IMPLEMENTED`
The plugin shall provide an svf_command_schedule mark allowing test procedures to schedule commands at specific simulation times. Assigned to M4.5 close-out.

---

## Campaign Manager Requirements [CAM]

**SVF-DEV-050** `[CAM]` `DRAFT`
The campaign manager shall accept test campaign definitions expressed in YAML format.

**SVF-DEV-051** `[CAM]` `DRAFT`
A campaign definition shall specify: campaign ID, model configuration baseline, requirement IDs under verification, and ordered test case references.

**SVF-DEV-052** `[CAM]` `DRAFT`
The campaign manager shall validate campaign YAML files against a published schema before execution.

**SVF-DEV-053** `[CAM]` `DRAFT`
The campaign manager shall record the campaign definition file, its SHA-256 hash, and the SVF version.

**SVF-DEV-054** `[CAM]` `DRAFT`
The campaign manager shall support per-test-case timeout configuration.

**SVF-DEV-055** `[CAM]` `DEFERRED`
The campaign manager shall support conditional test execution.

---

## Model Authoring Requirements [MOD]

**SVF-DEV-060** `[MOD]` `IMPLEMENTED`
The platform shall support FMUs authored in Python using the pythonfmu library.

**SVF-DEV-061** `[MOD]` `DRAFT`
The platform shall support FMUs authored in C or C++.

**SVF-DEV-062** `[MOD]` `DRAFT`
The platform shall provide a Python decorator API for FMU authoring.

**SVF-DEV-063** `[MOD]` `IMPLEMENTED`
The platform shall provide an integrated EPS FMU as the first reference spacecraft model.

**SVF-DEV-064** `[MOD]` `DEFERRED`
The platform shall provide an SMP2 model importer.

**SVF-DEV-065** `[MOD]` `IMPLEMENTED`
The integrated EPS FMU shall expose: solar_illumination, load_power (inputs); bus_voltage, battery_soc, battery_voltage, generated_power, charge_current (outputs).

**SVF-DEV-066** `[MOD]` `IMPLEMENTED`
The EPS shall be decomposed into three separate FMUs (SolarArray, Battery, PCDU) connected via WiringMap.

---

## Reporting & Traceability Requirements [REP]

**SVF-DEV-070** `[REP]` `DRAFT`
The platform shall produce JUnit XML test result reports natively from pytest.

**SVF-DEV-071** `[REP]` `DRAFT`
The platform shall produce structured test records aligned with ECSS-E-ST-10-02C.

**SVF-DEV-072** `[REP]` `IMPLEMENTED`
Each test case shall declare the requirement IDs it verifies via @pytest.mark.requirement() markers.

**SVF-DEV-073** `[REP]` `IMPLEMENTED`
The reporting layer shall generate a requirements traceability matrix mapping requirement IDs to test cases and verdicts.

**SVF-DEV-074** `[REP]` `DRAFT`
All reports shall include campaign ID, model baseline, SVF version, and execution timestamp.

**SVF-DEV-075** `[REP]` `DRAFT`
The platform shall produce an HTML report via Allure.

**SVF-DEV-076** `[REP]` `DEFERRED`
The platform shall provide a DOORS NG export adapter.

**SVF-DEV-077** `[REP]` `DEFERRED`
The platform shall provide a Jama Connect export adapter.

---

## System & Infrastructure Requirements [SYS]

**SVF-DEV-080** `[SYS]` `IMPLEMENTED`
The SVF core shall be packaged as a pip-installable Python package using pyproject.toml.

**SVF-DEV-081** `[SYS]` `IMPLEMENTED`
The platform shall support Linux (Ubuntu 22.04 LTS and above) as the primary execution environment.

**SVF-DEV-082** `[SYS]` `DRAFT`
The platform shall support macOS (Monterey and above).

**SVF-DEV-083** `[SYS]` `DRAFT`
The platform shall support Windows 10 and above as a best-effort environment.

**SVF-DEV-084** `[SYS]` `DRAFT`
Each simulation run shall be executable inside a Docker container.

**SVF-DEV-085** `[SYS]` `DRAFT`
The build system for mixed Python/C components shall use CMake with scikit-build-core.

**SVF-DEV-086** `[SYS]` `DRAFT`
FMU binary artefacts shall be managed in Git with Git LFS.

**SVF-DEV-087** `[SYS]` `IMPLEMENTED`
The SVF codebase shall maintain minimum 80% test coverage on orchestration and campaign manager layers.

**SVF-DEV-088** `[SYS]` `IMPLEMENTED`
The platform shall expose a public Python API with type annotations compatible with mypy strict mode.

**SVF-DEV-089** `[SYS]` `DEFERRED`
The platform shall support soft real-time execution on RT_PREEMPT patched Linux.

---

## Traceability Index

| Requirement ID | Area | Status | Milestone | Verified By |
|---|---|---|---|---|
| SVF-DEV-001 | SIM | IMPLEMENTED | M1 | test_fmu_equipment_initialises |
| SVF-DEV-002 | SIM | IMPLEMENTED | M1 | test_simulation_master_with_fmu |
| SVF-DEV-003 | SIM | DRAFT | — | — |
| SVF-DEV-004 | SIM | IMPLEMENTED | M4.5 | test_wiring_propagates_values |
| SVF-DEV-004b | SIM | BASELINED | M4.5 | — |
| SVF-DEV-005 | SIM | IMPLEMENTED | M1 | test_csv_logger_wired_to_fmu_adapter |
| SVF-DEV-006 | SIM | IMPLEMENTED | M1 | test_simulation_master_context_manager |
| SVF-DEV-007 | SIM | IMPLEMENTED | M1 | test_fmu_equipment_missing_fmu |
| SVF-DEV-008 | SIM | DEFERRED | — | — |
| SVF-DEV-009 | ABS | IMPLEMENTED | M2 | test_simulation_master_runs |
| SVF-DEV-010 | ABS | IMPLEMENTED | M2 | test_lockstep_single_fmu |
| SVF-DEV-011 | ABS | IMPLEMENTED | M2 | test_lockstep_sync_timeout |
| SVF-DEV-012 | ABS | IMPLEMENTED | M2 | test_lockstep_multiple_models |
| SVF-DEV-013 | ABS | IMPLEMENTED | M2 | test_native_equipment_step |
| SVF-DEV-014 | ABS | IMPLEMENTED | M3 | test_fmu_equipment_on_tick_writes_store |
| SVF-DEV-015 | ABS | IMPLEMENTED | M2 | test_native_equipment_step |
| SVF-DEV-016 | ABS | IMPLEMENTED | M2 | test_simulation_master_runs |
| SVF-DEV-017 | ABS | DEFERRED | — | — |
| SVF-DEV-018 | ABS | DEFERRED | — | — |
| SVF-DEV-020 | BUS | IMPLEMENTED | M2 | test_lockstep_single_fmu |
| SVF-DEV-021 | BUS | IMPLEMENTED | M2 | test_lockstep_single_fmu |
| SVF-DEV-022 | BUS | IMPLEMENTED | M2 | test_lockstep_single_fmu |
| SVF-DEV-023 | BUS | IMPLEMENTED | M2 | test_lockstep_single_fmu |
| SVF-DEV-024 | BUS | SUPERSEDED | — | SVF-DEV-031 |
| SVF-DEV-025 | BUS | BASELINED | M3 | — |
| SVF-DEV-026 | BUS | IMPLEMENTED | M2 | test_lockstep_multiple_models |
| SVF-DEV-027 | BUS | BASELINED | M3 | — |
| SVF-DEV-028 | BUS | IMPLEMENTED | M2 | test_lockstep_single_fmu |
| SVF-DEV-029 | BUS | DEFERRED | — | — |
| SVF-DEV-030 | BUS | DEFERRED | — | — |
| SVF-DEV-031 | BUS | IMPLEMENTED | M3 | test_parameter_store_populated_after_run |
| SVF-DEV-032 | BUS | IMPLEMENTED | M3 | test_write_and_read |
| SVF-DEV-033 | BUS | IMPLEMENTED | M3 | test_late_reader_sees_value |
| SVF-DEV-034 | BUS | DEFERRED | — | — |
| SVF-DEV-035 | BUS | IMPLEMENTED | M3 | test_inject_and_take |
| SVF-DEV-036 | BUS | IMPLEMENTED | M3 | test_take_is_atomic |
| SVF-DEV-037 | BUS | DEFERRED | — | — |
| SVF-DEV-038 | BUS | DEFERRED | — | — |
| SVF-DEV-090 | SDB | IMPLEMENTED | M3.5 | test_srdb_definitions |
| SVF-DEV-091 | SDB | IMPLEMENTED | M3.5 | test_load_all_baselines |
| SVF-DEV-092 | SDB | IMPLEMENTED | M3.5 | test_load_baseline |
| SVF-DEV-093 | SDB | IMPLEMENTED | M3.5 | test_mission_override_description |
| SVF-DEV-094 | SDB | IMPLEMENTED | M3.5 | test_parameter_store_range_violation_warns |
| SVF-DEV-095 | SDB | IMPLEMENTED | M3.5 | test_command_store_tm_inject_warns |
| SVF-DEV-096 | SDB | DEFERRED | — | — |
| SVF-DEV-097 | SDB | DEFERRED | — | — |
| SVF-DEV-098 | SDB | DEFERRED | — | — |
| EQP-001 | EQP | BASELINED | M3.6 | — |
| EQP-002 | EQP | BASELINED | M3.6 | — |
| EQP-003 | EQP | BASELINED | M3.6 | — |
| EQP-004 | EQP | BASELINED | M3.6 | — |
| EQP-005 | EQP | BASELINED | M3.6 | — |
| EQP-006 | EQP | BASELINED | M3.6 | — |
| EQP-007 | EQP | BASELINED | M3.6 | — |
| EQP-008 | EQP | BASELINED | M3.6 | — |
| EQP-009 | EQP | BASELINED | M3.6 | — |
| EQP-010 | EQP | BASELINED | M3.6 | — |
| EQP-011 | EQP | BASELINED | M3.6 | — |
| EQP-012 | EQP | BASELINED | M3.6 | — |
| EPS-001 | EPS | BASELINED | M3.6 | — |
| EPS-002 | EPS | BASELINED | M3.6 | — |
| EPS-003 | EPS | BASELINED | M3.6 | — |
| EPS-004 | EPS | BASELINED | M3.6 | — |
| EPS-005 | EPS | BASELINED | M3.6 | — |
| EPS-006 | EPS | BASELINED | M3.6 | — |
| EPS-007 | EPS | BASELINED | M3.6 | — |
| EPS-008 | EPS | BASELINED | M3.6 | — |
| EPS-009 | EPS | BASELINED | M3.6 | — |
| EPS-010 | EPS | BASELINED | M3.6 | — |
| EPS-011 | EPS | BASELINED | M3.6 | — |
| EPS-012 | EPS | BASELINED | M3.6 | — |
| EPS-013 | EPS | BASELINED | M3.6 | — |
| EPS-014 | EPS | BASELINED | M3.6 | — |
| EPS-015 | EPS | BASELINED | M3.6 | — |
| EPS-016 | EPS | BASELINED | M3.6 | — |
| SVF-DEV-040 | ORC | IMPLEMENTED | M3 | test_fixture_default_fmu |
| SVF-DEV-041 | ORC | IMPLEMENTED | M3 | test_fixture_default_fmu |
| SVF-DEV-042 | ORC | IMPLEMENTED | M3 | test_fixture_inject_command |
| SVF-DEV-043 | ORC | IMPLEMENTED | M3 | test_observe_reaches |
| SVF-DEV-044 | ORC | IMPLEMENTED | M3 | test_verdict_pass |
| SVF-DEV-045 | ORC | BASELINED | M3 | — |
| SVF-DEV-046 | ORC | DRAFT | — | — |
| SVF-DEV-047 | ORC | IMPLEMENTED | M3 | test_fixture_default_fmu |
| SVF-DEV-048 | ORC | BASELINED | M4.5 | — |
| SVF-DEV-050 | CAM | DRAFT | — | — |
| SVF-DEV-051 | CAM | DRAFT | — | — |
| SVF-DEV-052 | CAM | DRAFT | — | — |
| SVF-DEV-053 | CAM | DRAFT | — | — |
| SVF-DEV-054 | CAM | DRAFT | — | — |
| SVF-DEV-055 | CAM | DEFERRED | — | — |
| SVF-DEV-060 | MOD | IMPLEMENTED | M1 | validate_fmpy.py |
| SVF-DEV-061 | MOD | DRAFT | — | — |
| SVF-DEV-062 | MOD | DRAFT | — | — |
| SVF-DEV-063 | MOD | IMPLEMENTED | M4 | test_tc_pwr_001 |
| SVF-DEV-064 | MOD | DEFERRED | — | — |
| SVF-DEV-065 | MOD | IMPLEMENTED | M4 | test_tc_pwr_001 |
| SVF-DEV-066 | MOD | IMPLEMENTED | M4.5 | test_decomposed_eps_sunlight |
| SVF-DEV-070 | REP | DRAFT | — | — |
| SVF-DEV-071 | REP | DRAFT | — | — |
| SVF-DEV-072 | REP | BASELINED | M3.6 | — |
| SVF-DEV-073 | REP | BASELINED | M3.6 | — |
| SVF-DEV-074 | REP | DRAFT | — | — |
| SVF-DEV-075 | REP | DRAFT | — | — |
| SVF-DEV-076 | REP | DEFERRED | — | — |
| SVF-DEV-077 | REP | DEFERRED | — | — |
| SVF-DEV-080 | SYS | IMPLEMENTED | M1 | CI pipeline |
| SVF-DEV-081 | SYS | IMPLEMENTED | M1 | CI pipeline (ubuntu-latest) |
| SVF-DEV-082 | SYS | DRAFT | — | — |
| SVF-DEV-083 | SYS | DRAFT | — | — |
| SVF-DEV-084 | SYS | DRAFT | — | — |
| SVF-DEV-085 | SYS | DRAFT | — | — |
| SVF-DEV-086 | SYS | DRAFT | — | — |
| SVF-DEV-087 | SYS | IMPLEMENTED | M1 | CI pipeline (pytest) |
| SVF-DEV-088 | SYS | IMPLEMENTED | M1 | CI pipeline (mypy) |
| SVF-DEV-089 | SYS | DEFERRED | — | — |