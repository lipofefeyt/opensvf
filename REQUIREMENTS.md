# SVF Development Requirements

> **Status:** v1.1
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
| [1553] | MIL-STD-1553 Bus |
| [PUS] | PUS TM/TC |
| [OBC] | OBC DHS behaviour |
| [PCDU] | Power Conditioning and Distribution Unit |
| [ST] | Star Tracker |
| [SBT] | S-Band Transponder |
| [RW] | Reaction Wheel |
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
The SimulationMaster shall support SSP (System Structure and Parameterization) files as an alternative to programmatic wiring maps. Assigned to M8.

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
The platform shall provide a RealtimeTickSource driven by RT_PREEMPT timer. Assigned to M9.

**SVF-DEV-018** `[ABS]` `DEFERRED`
The platform shall provide a SharedMemorySyncProtocol using a lock-free ring buffer. Assigned to M9.

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
The CommandSample DDS topic shall carry: time t, variable name, and value.

**SVF-DEV-026** `[BUS]` `IMPLEMENTED`
All DDS writers and readers for synchronisation shall use KEEP_ALL QoS.

**SVF-DEV-027** `[BUS]` `DEFERRED`
The bus shall support deadline monitoring.

**SVF-DEV-028** `[BUS]` `IMPLEMENTED`
The bus integration shall be implemented as a plugin.

**SVF-DEV-029** `[BUS]` `DEFERRED`
A CCSDS adapter plugin shall bridge DDS topics to CCSDS APID-addressed TM/TC streams. Assigned to M10.

**SVF-DEV-030** `[BUS]` `DEFERRED`
A SpaceWire adapter plugin shall bridge DDS topics to SpaceWire packets. Assigned to M10.

**SVF-DEV-031** `[BUS]` `IMPLEMENTED`
The platform shall implement a thread-safe ParameterStore as the central state store for all simulation outputs.

**SVF-DEV-032** `[BUS]` `IMPLEMENTED`
Each ParameterStore entry shall carry: value (float), timestamp (float), and model_id (string).

**SVF-DEV-033** `[BUS]` `IMPLEMENTED`
The ParameterStore shall expose write(), read(), and snapshot() methods. read() returns the last written value regardless of when the reader connects.

**SVF-DEV-034** `[BUS]` `DEFERRED`
The platform shall provide an optional ParameterStoreDdsBridge for external inspection tools. Assigned to M10.

**SVF-DEV-035** `[BUS]` `IMPLEMENTED`
The platform shall implement a CommandStore separate from the ParameterStore.

**SVF-DEV-036** `[BUS]` `IMPLEMENTED`
Each CommandEntry shall carry: name, value, t, source_id, consumed flag. take() shall be atomic.

**SVF-DEV-037** `[BUS]` `IMPLEMENTED`
The platform shall provide a PUS TM/TC adapter implementing ECSS-E-ST-70-41C. Assigned to M7.

**SVF-DEV-038** `[BUS]` `IMPLEMENTED`
The platform shall provide bus protocol adapters. MIL-STD-1553 implemented in M6. SpaceWire and CAN deferred to M10.

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
The platform shall provide an XTCE 1.2 export adapter. Assigned to M10.

**SVF-DEV-098** `[SDB]` `DEFERRED`
The platform shall provide a MIB import adapter. Assigned to M10.

---

## Generic Equipment Contract Requirements [EQP]

**EQP-001** `[EQP]` `IMPLEMENTED`
Equipment shall declare all ports via _declare_ports() before initialise() is called. Duplicate port names shall raise ValueError.

**EQP-002** `[EQP]` `IMPLEMENTED`
Equipment.write_port() shall only accept OUT-direction ports.

**EQP-003** `[EQP]` `IMPLEMENTED`
Equipment.read_port() shall accept any declared port. Undeclared ports raise ValueError.

**EQP-004** `[EQP]` `IMPLEMENTED`
Equipment.receive() shall only accept IN-direction ports.

**EQP-005** `[EQP]` `IMPLEMENTED`
Equipment.on_tick() shall read CommandStore entries into IN ports before calling do_step().

**EQP-006** `[EQP]` `IMPLEMENTED`
Equipment.on_tick() shall write all OUT port values to ParameterStore after do_step() completes.

**EQP-007** `[EQP]` `IMPLEMENTED`
Equipment.on_tick() shall call SyncProtocol.publish_ready() after ParameterStore writes.

**EQP-008** `[EQP]` `IMPLEMENTED`
FmuEquipment shall translate FMU variable names to port names via an optional parameter_map.

**EQP-009** `[EQP]` `IMPLEMENTED`
FmuEquipment.do_step() shall apply all IN port values to FMU inputs before doStep(). FMU outputs read into OUT ports after doStep().

**EQP-010** `[EQP]` `IMPLEMENTED`
NativeEquipment shall call step_fn(equipment, t, dt) on each tick.

**EQP-011** `[EQP]` `IMPLEMENTED`
All port values shall default to 0.0 before the first write or receive.

**EQP-012** `[EQP]` `IMPLEMENTED`
Equipment.teardown() shall be safe to call even if initialise() was never called.

---

## EPS Spacecraft Model Requirements [EPS]

**EPS-001** `[EPS]` `IMPLEMENTED`
SolarArrayFmu shall produce generated_power proportional to solar_illumination.

**EPS-002** `[EPS]` `IMPLEMENTED`
SolarArrayFmu shall produce generated_power = 0.0 when solar_illumination = 0.0.

**EPS-003** `[EPS]` `IMPLEMENTED`
SolarArrayFmu shall produce generated_power = MAX_POWER_W * PANEL_EFFICIENCY when solar_illumination = 1.0.

**EPS-004** `[EPS]` `IMPLEMENTED`
BatteryFmu battery_soc shall decrease over time when charge_current is negative.

**EPS-005** `[EPS]` `IMPLEMENTED`
BatteryFmu battery_soc shall increase over time when charge_current is positive.

**EPS-006** `[EPS]` `IMPLEMENTED`
BatteryFmu battery_voltage shall follow a non-linear SoC curve in the range 3.0V to 4.2V.

**EPS-007** `[EPS]` `IMPLEMENTED`
BatteryFmu battery_soc shall never fall below SOC_MIN (0.05) or exceed SOC_MAX (1.0).

**EPS-008** `[EPS]` `IMPLEMENTED`
PcduFmu shall produce positive charge_current when generated_power exceeds load_power.

**EPS-009** `[EPS]` `IMPLEMENTED`
PcduFmu shall produce negative charge_current when load_power exceeds generated_power.

**EPS-010** `[EPS]` `IMPLEMENTED`
PcduFmu bus_voltage shall equal battery_voltage (simplified — no active regulation).

**EPS-011** `[EPS]` `IMPLEMENTED`
The integrated EpsFmu shall charge the battery when solar_illumination = 1.0 and load_power = 30W.

**EPS-012** `[EPS]` `IMPLEMENTED`
The integrated EpsFmu shall discharge the battery when solar_illumination = 0.0 and load_power = 30W.

**EPS-013** `[EPS]` `IMPLEMENTED`
The integrated EpsFmu bus_voltage shall remain above 3.0V at all times during normal operation.

**EPS-014** `[EPS]` `IMPLEMENTED`
The decomposed EPS shall charge the battery when solar_illumination = 1.0 and load_power = 30W.

**EPS-015** `[EPS]` `IMPLEMENTED`
The decomposed EPS shall discharge the battery when solar_illumination = 0.0 and load_power = 30W.

**EPS-016** `[EPS]` `IMPLEMENTED`
The decomposed EPS generated_power shall be 0.0 in eclipse and approximately 90W in full sun.

---

## MIL-STD-1553 Bus Requirements [1553]

**1553-001** `[1553]` `IMPLEMENTED`
The platform shall provide a MIL-STD-1553B bus adapter (Mil1553Bus) extending Bus Equipment.

**1553-002** `[1553]` `IMPLEMENTED`
Mil1553Bus shall provide one BC input port (type: MIL1553_BC) and up to 30 RT output ports (type: MIL1553_RT).

**1553-003** `[1553]` `IMPLEMENTED`
Mil1553Bus shall route BC_to_RT messages from ParameterStore to equipment CommandStore according to the subaddress mapping.

**1553-004** `[1553]` `IMPLEMENTED`
Mil1553Bus shall route RT_to_BC messages from equipment ParameterStore to OBC telemetry namespace.

**1553-005** `[1553]` `IMPLEMENTED`
Mil1553Bus shall support broadcast commands (RT address 31) delivered to all connected RTs.

**1553-006** `[1553]` `IMPLEMENTED`
Mil1553Bus shall support dual redundant bus (A/B) with automatic switchover on BUS_ERROR fault.

**1553-007** `[1553]` `IMPLEMENTED`
The Bus fault injection framework shall support: NO_RESPONSE, LATE_RESPONSE, BAD_PARITY, WRONG_WORD_COUNT, BUS_ERROR.

**1553-008** `[1553]` `IMPLEMENTED`
Bus faults shall support time-limited duration (auto-expire) and permanent injection (duration=0.0).

**1553-009** `[1553]` `IMPLEMENTED`
Bus faults shall be injectable via CommandStore using the naming convention: bus.{bus_id}.fault.{target}.{fault_type}.

**1553-010** `[1553]` `IMPLEMENTED`
The OBC Equipment model shall act as 1553 Bus Controller, receiving PUS TC packets and routing commands to RTs. Assigned to M7.

---

## PUS TM/TC Requirements [PUS]

**PUS-001** `[PUS]` `IMPLEMENTED`
The platform shall implement a PUS-C TC packet parser (PusTcParser) compliant with ECSS-E-ST-70-41C.

**PUS-002** `[PUS]` `IMPLEMENTED`
PusTcParser shall validate: packet type (TC=1), data field header flag, PUS version (PUS-C), and CRC-16/CCITT.

**PUS-003** `[PUS]` `IMPLEMENTED`
The platform shall implement a PUS-C TC packet builder (PusTcBuilder) with CRC-16 generation.

**PUS-004** `[PUS]` `IMPLEMENTED`
The platform shall implement a PUS-C TM packet builder (PusTmBuilder) and parser (PusTmParser) with CRC-16.

**PUS-005** `[PUS]` `IMPLEMENTED`
The platform shall implement PUS Service 3 (Housekeeping): HK report structure definition (TC(3,1)), periodic generation enable/disable (TC(3,5/6)), and HK parameter report generation (TM(3,25)). Essential HK reports shall be activated automatically at OBC initialise(). Assigned to M7.

**PUS-006** `[PUS]` `IMPLEMENTED`
The platform shall implement PUS Service 5 (Event Reporting): normal, low, medium, and high severity event reports. Assigned to M7.

**PUS-007** `[PUS]` `IMPLEMENTED`
The platform shall implement PUS Service 17 (Test): are-you-alive TC(17,1) and TM(17,2) response. Assigned to M7.

**PUS-008** `[PUS]` `IMPLEMENTED`
The platform shall implement PUS Service 20 (On-Board Parameter Management): parameter value set TC(20,1) and get TC(20,3)/TM(20,4). Assigned to M7.

**PUS-009** `[PUS]` `IMPLEMENTED`
The platform shall implement PUS Service 1 (Request Verification): acceptance TM(1,1), execution started TM(1,3), completion TM(1,7), failure reports TM(1,2/4/8). Assigned to M7.

**PUS-010** `[PUS]` `IMPLEMENTED`
The OBC Equipment model shall receive raw PUS TC bytes, parse them using PusTcParser, route commands to equipment via the appropriate bus interface, and generate PUS TM acknowledgement packets. Assigned to M7.

**PUS-011** `[PUS]` `IMPLEMENTED`
The TTC Equipment model shall bridge the ground segment to the OBC via simulated RF link, forwarding TC bytes and exposing TM for observable assertions. Assigned to M7.

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
The plugin shall provide an svf_command_schedule mark allowing test procedures to schedule commands at specific simulation times.

---

## Campaign Manager Requirements [CAM]

**SVF-DEV-050** `[CAM]` `IMPLEMENTED`
The campaign manager shall accept test campaign definitions expressed in YAML format.

**SVF-DEV-051** `[CAM]` `IMPLEMENTED`
A campaign definition shall specify: campaign ID, model configuration baseline, requirement IDs under verification, and ordered test case references.

**SVF-DEV-052** `[CAM]` `IMPLEMENTED`
The campaign manager shall validate campaign YAML files against a published schema before execution.

**SVF-DEV-053** `[CAM]` `IMPLEMENTED`
The campaign manager shall record the campaign definition file, its SHA-256 hash, and the SVF version.

**SVF-DEV-054** `[CAM]` `IMPLEMENTED`
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
The platform shall provide an SMP2 model importer. Assigned to M8.

**SVF-DEV-065** `[MOD]` `IMPLEMENTED`
The integrated EPS FMU shall expose: solar_illumination, load_power (inputs); bus_voltage, battery_soc, battery_voltage, generated_power, charge_current (outputs).

**SVF-DEV-066** `[MOD]` `IMPLEMENTED`
The EPS shall be decomposed into three separate FMUs (SolarArray, Battery, PCDU) connected via WiringMap.

---

## Reporting & Traceability Requirements [REP]

**SVF-DEV-070** `[REP]` `IMPLEMENTED`
The platform shall produce JUnit XML test result reports natively from pytest.

**SVF-DEV-071** `[REP]` `IMPLEMENTED`
The platform shall produce structured test records aligned with ECSS-E-ST-10-02C.

**SVF-DEV-072** `[REP]` `IMPLEMENTED`
Each test case shall declare the requirement IDs it verifies via @pytest.mark.requirement() markers.

**SVF-DEV-073** `[REP]` `IMPLEMENTED`
The reporting layer shall generate a requirements traceability matrix mapping requirement IDs to test cases and verdicts.

**SVF-DEV-074** `[REP]` `IMPLEMENTED`
All reports shall include campaign ID, model baseline, SVF version, and execution timestamp.

**SVF-DEV-075** `[REP]` `IMPLEMENTED`
The platform shall produce a self-contained HTML report after each campaign run.

**SVF-DEV-076** `[REP]` `DEFERRED`
The platform shall provide a DOORS NG export adapter. Assigned to M10.

**SVF-DEV-077** `[REP]` `DEFERRED`
The platform shall provide a Jama Connect export adapter. Assigned to M10.

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
The platform shall support soft real-time execution on RT_PREEMPT patched Linux. Assigned to M9.

---

## Traceability Index

| Requirement ID | Area | Status | Milestone | Verified By |
|---|---|---|---|---|
| SVF-DEV-001 | SIM | IMPLEMENTED | M1 | test_fmu_equipment_initialises |
| SVF-DEV-002 | SIM | IMPLEMENTED | M1 | test_simulation_master_with_fmu |
| SVF-DEV-003 | SIM | DRAFT | — | — |
| SVF-DEV-004 | SIM | IMPLEMENTED | M4.5 | test_wiring_propagates_values |
| SVF-DEV-004b | SIM | DEFERRED | M8 | — |
| SVF-DEV-005 | SIM | IMPLEMENTED | M1 | test_csv_logger_creates_file |
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
| SVF-DEV-017 | ABS | DEFERRED | M9 | — |
| SVF-DEV-018 | ABS | DEFERRED | M9 | — |
| SVF-DEV-020 | BUS | IMPLEMENTED | M2 | test_lockstep_single_fmu |
| SVF-DEV-021 | BUS | IMPLEMENTED | M2 | test_lockstep_single_fmu |
| SVF-DEV-022 | BUS | IMPLEMENTED | M2 | test_lockstep_single_fmu |
| SVF-DEV-023 | BUS | IMPLEMENTED | M2 | test_lockstep_single_fmu |
| SVF-DEV-024 | BUS | SUPERSEDED | — | SVF-DEV-031 |
| SVF-DEV-025 | BUS | DEFERRED | — | — |
| SVF-DEV-026 | BUS | IMPLEMENTED | M2 | test_lockstep_multiple_models |
| SVF-DEV-027 | BUS | DEFERRED | — | — |
| SVF-DEV-028 | BUS | IMPLEMENTED | M2 | test_lockstep_single_fmu |
| SVF-DEV-029 | BUS | DEFERRED | M10 | — |
| SVF-DEV-030 | BUS | DEFERRED | M10 | — |
| SVF-DEV-031 | BUS | IMPLEMENTED | M3 | test_parameter_store_populated_after_run |
| SVF-DEV-032 | BUS | IMPLEMENTED | M3 | test_write_and_read |
| SVF-DEV-033 | BUS | IMPLEMENTED | M3 | test_late_reader_sees_value |
| SVF-DEV-034 | BUS | DEFERRED | M10 | — |
| SVF-DEV-035 | BUS | IMPLEMENTED | M3 | test_inject_and_take |
| SVF-DEV-036 | BUS | IMPLEMENTED | M3 | test_take_is_atomic |
| SVF-DEV-037 | BUS | IMPLEMENTED | M7 | test_tc_pus_005_full_chain_ground_to_rw |
| SVF-DEV-038 | BUS | IMPLEMENTED | M6 | test_tc_1553_001_rw_speed_increases_when_commanded |
| SVF-DEV-090 | SDB | IMPLEMENTED | M3.5 | test_srdb_definitions |
| SVF-DEV-091 | SDB | IMPLEMENTED | M3.5 | test_load_all_baselines |
| SVF-DEV-092 | SDB | IMPLEMENTED | M3.5 | test_load_baseline |
| SVF-DEV-093 | SDB | IMPLEMENTED | M3.5 | test_mission_override_description |
| SVF-DEV-094 | SDB | IMPLEMENTED | M3.5 | test_parameter_store_range_violation_warns |
| SVF-DEV-095 | SDB | IMPLEMENTED | M3.5 | test_command_store_tm_inject_warns |
| SVF-DEV-096 | SDB | DEFERRED | — | — |
| SVF-DEV-097 | SDB | DEFERRED | M10 | — |
| SVF-DEV-098 | SDB | DEFERRED | M10 | — |
| EQP-001 | EQP | IMPLEMENTED | M3.6 | test_equipment_construction |
| EQP-002 | EQP | IMPLEMENTED | M3.6 | test_write_port_to_in_raises |
| EQP-003 | EQP | IMPLEMENTED | M3.6 | test_read_port_unknown_raises |
| EQP-004 | EQP | IMPLEMENTED | M3.6 | test_receive_into_out_port_raises |
| EQP-005 | EQP | IMPLEMENTED | M3.6 | test_source_to_sink_wiring |
| EQP-006 | EQP | IMPLEMENTED | M3.6 | test_fmu_equipment_on_tick_writes_store |
| EQP-007 | EQP | IMPLEMENTED | M3.6 | test_parameter_map_translates_port_names |
| EQP-008 | EQP | IMPLEMENTED | M3.6 | test_fmu_equipment_ports_declared |
| EQP-009 | EQP | IMPLEMENTED | M3.6 | test_fmu_equipment_step |
| EQP-010 | EQP | IMPLEMENTED | M3.6 | test_native_equipment_step |
| EQP-011 | EQP | IMPLEMENTED | M3.6 | test_port_default_value_is_zero |
| EQP-012 | EQP | IMPLEMENTED | M3.6 | test_teardown_safe_without_initialise |
| EPS-001 | EPS | IMPLEMENTED | M3.6 | test_solar_power_proportional_to_illumination |
| EPS-002 | EPS | IMPLEMENTED | M3.6 | test_solar_zero_power_in_eclipse |
| EPS-003 | EPS | IMPLEMENTED | M3.6 | test_solar_full_power_in_sunlight |
| EPS-004 | EPS | IMPLEMENTED | M3.6 | test_battery_soc_decreases_when_discharging |
| EPS-005 | EPS | IMPLEMENTED | M3.6 | test_battery_soc_increases_when_charging |
| EPS-006 | EPS | IMPLEMENTED | M3.6 | test_battery_voltage_within_lion_range |
| EPS-007 | EPS | IMPLEMENTED | M3.6 | test_battery_soc_clamped_at_min |
| EPS-008 | EPS | IMPLEMENTED | M3.6 | test_pcdu_positive_current_when_generation_exceeds_load |
| EPS-009 | EPS | IMPLEMENTED | M3.6 | test_pcdu_negative_current_when_load_exceeds_generation |
| EPS-010 | EPS | IMPLEMENTED | M3.6 | test_pcdu_bus_voltage_equals_battery_voltage |
| EPS-011 | EPS | IMPLEMENTED | M4 | test_tc_pwr_001_battery_charges_in_sunlight |
| EPS-012 | EPS | IMPLEMENTED | M4 | test_tc_pwr_002_battery_discharges_in_eclipse |
| EPS-013 | EPS | IMPLEMENTED | M4 | test_tc_pwr_002_battery_discharges_in_eclipse |
| EPS-014 | EPS | IMPLEMENTED | M4.5 | test_decomposed_eps_charges_in_sunlight |
| EPS-015 | EPS | IMPLEMENTED | M4.5 | test_decomposed_eps_discharges_in_eclipse |
| EPS-016 | EPS | IMPLEMENTED | M4.5 | test_decomposed_eps_charges_in_sunlight |
| 1553-001 | 1553 | IMPLEMENTED | M6 | test_bus_declares_correct_ports |
| 1553-002 | 1553 | IMPLEMENTED | M6 | test_bus_declares_correct_ports |
| 1553-003 | 1553 | IMPLEMENTED | M6 | test_bc_to_rt_routes_parameter |
| 1553-004 | 1553 | IMPLEMENTED | M6 | test_rt_to_bc_routes_telemetry |
| 1553-005 | 1553 | IMPLEMENTED | M6 | test_broadcast_mapping_reaches_all_rts |
| 1553-006 | 1553 | IMPLEMENTED | M6 | test_bus_error_triggers_switchover |
| 1553-007 | 1553 | IMPLEMENTED | M6 | test_fault_is_active_immediately |
| 1553-008 | 1553 | IMPLEMENTED | M6 | test_fault_expires_after_duration |
| 1553-009 | 1553 | IMPLEMENTED | M6 | test_fault_injected_via_command_store |
| 1553-010 | 1553 | IMPLEMENTED | M7 | test_tc_pus_005_full_chain_ground_to_rw |
| PUS-001 | PUS | IMPLEMENTED | M7 | test_build_and_parse_roundtrip |
| PUS-002 | PUS | IMPLEMENTED | M7 | test_invalid_crc_raises |
| PUS-003 | PUS | IMPLEMENTED | M7 | test_crc_is_appended |
| PUS-004 | PUS | IMPLEMENTED | M7 | test_build_and_parse_roundtrip (TM) |
| PUS-005 | PUS | IMPLEMENTED | M7 | test_s3_define_and_generate_report |
| PUS-006 | PUS | IMPLEMENTED | M7 | test_s5_informative_event |
| PUS-007 | PUS | IMPLEMENTED | M7 | test_tc_pus_001_are_you_alive |
| PUS-008 | PUS | IMPLEMENTED | M7 | test_tc_pus_002_s20_set_rw_torque |
| PUS-009 | PUS | IMPLEMENTED | M7 | test_tc_pus_004_invalid_crc_rejected |
| PUS-010 | PUS | IMPLEMENTED | M7 | test_tc_pus_005_full_chain_ground_to_rw |
| PUS-011 | PUS | IMPLEMENTED | M7 | test_ttc_are_you_alive_roundtrip |
| SVF-DEV-040 | ORC | IMPLEMENTED | M3 | test_fixture_default_fmu |
| SVF-DEV-041 | ORC | IMPLEMENTED | M3 | test_fixture_default_fmu |
| SVF-DEV-042 | ORC | IMPLEMENTED | M3 | test_fixture_inject_command |
| SVF-DEV-043 | ORC | IMPLEMENTED | M3 | test_observe_reaches |
| SVF-DEV-044 | ORC | IMPLEMENTED | M3 | test_verdict_pass |
| SVF-DEV-045 | ORC | DEFERRED | — | — |
| SVF-DEV-046 | ORC | DRAFT | — | — |
| SVF-DEV-047 | ORC | IMPLEMENTED | M3 | test_fixture_default_fmu |
| SVF-DEV-048 | ORC | IMPLEMENTED | M4.5 | test_tc_pwr_003_sunlight_to_eclipse_transition |
| SVF-DEV-050 | CAM | IMPLEMENTED | M5 | test_load_valid_campaign |
| SVF-DEV-051 | CAM | IMPLEMENTED | M5 | test_test_cases_ordered |
| SVF-DEV-052 | CAM | IMPLEMENTED | M5 | test_missing_required_field_raises |
| SVF-DEV-053 | CAM | IMPLEMENTED | M5 | test_file_hash_recorded |
| SVF-DEV-054 | CAM | IMPLEMENTED | M5 | test_overall_verdict_pass_when_all_pass |
| SVF-DEV-055 | CAM | DEFERRED | — | — |
| SVF-DEV-060 | MOD | IMPLEMENTED | M1 | validate_fmpy.py |
| SVF-DEV-061 | MOD | DRAFT | — | — |
| SVF-DEV-062 | MOD | DRAFT | — | — |
| SVF-DEV-063 | MOD | IMPLEMENTED | M4 | test_tc_pwr_001 |
| SVF-DEV-064 | MOD | DEFERRED | M8 | — |
| SVF-DEV-065 | MOD | IMPLEMENTED | M4 | test_tc_pwr_001 |
| SVF-DEV-066 | MOD | IMPLEMENTED | M4.5 | test_decomposed_eps_sunlight |
| SVF-DEV-070 | REP | IMPLEMENTED | M5 | results/test_results.xml |
| SVF-DEV-071 | REP | IMPLEMENTED | M5 | test_report_contains_verdicts |
| SVF-DEV-072 | REP | IMPLEMENTED | M3.6 | traceability.txt |
| SVF-DEV-073 | REP | IMPLEMENTED | M3.6 | traceability.txt |
| SVF-DEV-074 | REP | IMPLEMENTED | M5 | test_report_contains_metadata |
| SVF-DEV-075 | REP | IMPLEMENTED | M5 | test_report_generated |
| SVF-DEV-076 | REP | DEFERRED | M10 | — |
| SVF-DEV-077 | REP | DEFERRED | M10 | — |
| SVF-DEV-080 | SYS | IMPLEMENTED | M1 | CI pipeline |
| SVF-DEV-081 | SYS | IMPLEMENTED | M1 | CI pipeline (ubuntu-latest) |
| SVF-DEV-082 | SYS | DRAFT | — | — |
| SVF-DEV-083 | SYS | DRAFT | — | — |
| SVF-DEV-084 | SYS | DRAFT | — | — |
| SVF-DEV-085 | SYS | DRAFT | — | — |
| SVF-DEV-086 | SYS | DRAFT | — | — |
| SVF-DEV-087 | SYS | IMPLEMENTED | M1 | CI pipeline (pytest) |
| SVF-DEV-088 | SYS | IMPLEMENTED | M1 | CI pipeline (mypy) |
| SVF-DEV-089 | SYS | DEFERRED | M9 | — |