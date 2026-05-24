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
| [KDE] | Dynamics and Kinematics Environment |
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

**SVF-DEV-120** `[SIM]` `IMPLEMENTED`
The platform shall provide a MonteCarloRunner that executes a user-supplied
simulation factory function N times with different integer seeds, collecting
metrics from each run. The runner shall support parallel execution via
ProcessPoolExecutor. Results shall include per-run metrics, statistical
summary (mean, std, percentiles), and a pass rate for boolean metrics.
Results shall be serialisable to JSON.


---

## Kinematics & Dynamics Environment Requirements [KDE]

**KDE-001** `[KDE]` `IMPLEMENTED`
The platform shall provide a 6-DOF rigid body kinematics and dynamics engine wrapped as an FMI Co-Simulation FMU.

**KDE-002** `[KDE]` `IMPLEMENTED`
The KDE FMU shall accept a 3-axis mechanical torque input vector (Nm) to drive rotational integration.

**KDE-003** `[KDE]` `IMPLEMENTED`
The KDE FMU shall numerically integrate and output the spacecraft attitude (quaternion) and angular velocity (rad/s) over time.

**KDE-004** `[KDE]` `IMPLEMENTED`
The KDE FMU shall compute and output the localized environmental magnetic field vector (Tesla) in the spacecraft body frame.

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

**SVF-DEV-159** `[BUS]` `IMPLEMENTED`
`OBCEmulatorAdapter._parse_tm()` shall append each successfully parsed `PusTmPacket` to a thread-safe internal queue. `get_tm_queue()` shall atomically drain and return all queued packets, leaving the queue empty after the call.

**SVF-DEV-160** `[BUS]` `IMPLEMENTED`
`OBCEmulatorAdapter` shall parse incoming TM(3,25) housekeeping packets (set_id=3) and update the `dhs.obc.watchdog_status`, `dhs.obc.memory_used_pct`, `dhs.obc.health`, `dhs.obc.reset_count`, and `dhs.obc.cpu_load` OUT ports from the HK fields.

**SVF-DEV-161** `[BUS]` `IMPLEMENTED`
`OBCEmulatorAdapter` shall raise `RuntimeError` after `MAX_DESYNC` (3) consecutive simulation ticks where the 0xFF sync byte is not received within `sync_timeout`. The desync counter shall reset to zero on any tick where sync is achieved.

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

**SVF-DEV-096** `[SDB]` `IMPLEMENTED`
The SRDB shall support raw-to-engineering calibration definitions. Two curve types are supported: polynomial (Horner evaluation of coefficient tuple) and table (piecewise-linear interpolation with endpoint clamping). Calibration is an optional field on ParameterDefinition; SrdbLoader parses calibration blocks from YAML and preserves them through mission override merges.

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

## CAN Bus Requirements [CAN]

**CAN-001** `[CAN]` `IMPLEMENTED`
The platform shall provide a CAN 2.0B bus adapter (CanBus) supporting standard 11-bit identifiers (range 0x000–0x7FF) and extended 29-bit identifiers (range 0x00000000–0x1FFFFFFF); identifiers outside the respective range shall raise `ValueError`.

**CAN-002** `[CAN]` `IMPLEMENTED`
CanBus shall route TX messages (direction="tx") from ParameterStore to CommandStore by CAN identifier; RX messages (direction="rx") shall be written to the canonical OBC telemetry parameter `can.{bus_id}.{node_id}.{parameter}`.

**CAN-003** `[CAN]` `IMPLEMENTED`
A BUS_ERROR fault targeting "all" shall put CanBus in bus-off state, suspending all TX and RX message routing for the duration of the fault.

**CAN-004** `[CAN]` `IMPLEMENTED`
NO_RESPONSE and BAD_PARITY faults shall block only the affected node's messages; unaffected nodes shall continue to route normally. Time-limited faults shall auto-expire. Faults shall be injectable via CommandStore using the convention `bus.{bus_id}.fault.{target}.{fault_type}`.

---

## SpaceWire Bus Requirements [SPW]

**SPW-001** `[SPW]` `IMPLEMENTED`
The platform shall provide a SpaceWire bus adapter (SpwBus) with RMAP read and write transaction routing by logical address; logical addresses outside the valid range 32–254 shall raise `ValueError`.

**SPW-002** `[SPW]` `IMPLEMENTED`
SpwBus RMAP write transactions shall route parameter values from ParameterStore to CommandStore for the target node.

**SPW-003** `[SPW]` `IMPLEMENTED`
SpwBus RMAP read transactions shall route node telemetry to the canonical OBC parameter `spw.{bus_id}.{node_id}.{parameter}`.

**SPW-004** `[SPW]` `IMPLEMENTED`
A BUS_ERROR fault targeting a node_id or "all" shall block all RMAP transactions to the affected node(s). Faults shall be injectable via CommandStore using the convention `bus.{bus_id}.fault.{target}.{fault_type}`.

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

**SVF-DEV-162** `[PUS]` `IMPLEMENTED`
The platform shall implement PUS Service 9 (Time Management): TC(9,128) Set OBT shall be accepted by ObcEquipment and OBCEmulatorAdapter. The CUC-4,2 timestamp (4-byte coarse + 2-byte fine) shall be parsed and applied to the OBT counter. ObcEquipment shall also accept OBT sync via the `dhs.obc.time_sync_cmd` IN port (seconds, -1 = idle). Assigned to M37.

**SVF-DEV-163** `[PUS]` `IMPLEMENTED`
The platform shall implement PUS Service 11 (Time-Based Scheduling): TC(11,4) Insert Activity, TC(11,5) Delete Activity, TC(11,6) Delete All, TC(11,17) Enable Schedule, TC(11,18) Disable Schedule. A `TimeBasedScheduler` shall hold a sorted list of `ScheduledActivity` items; on each OBC tick the scheduler shall fire all activities with `time_tag <= obt` by routing them through the normal `receive_tc()` path. `ProcedureContext.schedule_tc()` shall provide a convenience API for test procedures. Assigned to M38.

**SVF-DEV-164** `[PUS]` `IMPLEMENTED`
The platform shall implement PUS Service 12 (On-Board Monitoring): TC(12,1) Enable, TC(12,2) Disable, TC(12,3) Add/Replace Monitoring Definition, TC(12,4) Delete, TC(12,5) Delete All. An `OnBoardMonitor` shall evaluate each enabled `MonitoringDefinition` on every OBC tick and generate a PUS S5 event report on the first tick a parameter crosses a low or high limit (latching — no repeat until recovery). TC(12,3) app_data: 2B param_id, 4B low_limit (IEEE754 float, NaN=none), 4B high_limit, 2B event_id_low, 2B event_id_high, 1B severity. Assigned to M39.

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

**SVF-DEV-131** `[ORC]` `IMPLEMENTED`
The platform shall provide a ParameterMonitor that runs in a background
thread and continuously checks a named ParameterStore entry against a
threshold (less_than or greater_than) throughout a test procedure step.
assert_no_violations() shall raise ProcedureError on any breach.
summary() shall return a MonitorResult with compliance status, violation
list, and min/max observed values.

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

**SVF-DEV-121** `[CAM]` `IMPLEMENTED`
The platform shall provide a CampaignRunner that loads Procedure subclasses
from Python files declared in a campaign YAML, instantiates a spacecraft
per the campaign's spacecraft.yaml, runs each Procedure against it, and
returns a CampaignReport with per-procedure verdicts, pass/fail counts,
total duration, and a to_dict() method for serialisation.
 
**SVF-DEV-122** `[CAM]` `IMPLEMENTED`
The platform shall provide a generate_html_report() function that renders
a CampaignReport to a self-contained HTML file using Jinja2. The report
shall include: campaign metadata, summary statistics, per-procedure verdict
cards, per-step event timelines (TC/TM/INJECT/MONITOR events), and seed
information for deterministic replay. No CDN dependencies.

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

**SVF-DEV-100** `[SYS]` `IMPLEMENTED`
The platform shall support running obsw_sim binaries cross-compiled for
AArch64 (ZynqMP Cortex-A53) on x86_64 hosts via QEMU user-mode emulation
(qemu-aarch64). The OBCEmulatorAdapter shall auto-detect the binary
architecture via `file` and prepend the QEMU prefix transparently. The
wire protocol shall be identical to the native x86_64 case.
 
**SVF-DEV-101** `[SYS]` `IMPLEMENTED`
The platform shall support connecting OBCEmulatorAdapter to an OBSW
running inside Renode ZynqMP emulation via a TCP socket (socket mode).
The adapter shall connect to a Renode UART terminal exposed as a TCP
server and exchange the same wire protocol frames as in pipe mode.
 
**SVF-DEV-110** `[SYS]` `IMPLEMENTED`
The platform shall provide a SpacecraftLoader that instantiates a complete
SimulationMaster from a single YAML spacecraft configuration file. The YAML
shall declare: obsw transport mode (pipe/socket/stub), equipment list with
hardware profiles, wiring (auto or explicit overrides), and simulation
parameters (dt, stop_time, seed, realtime). This is the zero-Python entry
point.

**SVF-DEV-130** `[SYS]` `IMPLEMENTED`
The platform shall bundle hardware profiles in a directory shipped with
the opensvf package (mission_mysat1/hardware_profiles/ or srdb/hardware/).
Profile search order shall be: (1) bundled directory, (2) obsw-srdb
package if installed, (3) explicit hardware_dir argument. opensvf shall
function without obsw-srdb installed.
 
**SVF-DEV-132** `[EQP]` `IMPLEMENTED`
The platform shall provide an EquipmentFaultEngine that intercepts
NativeEquipment.read_port() and write_port() to inject standardised
faults without modifying model physics code. Supported fault modes:
stuck (fixed value), noise (Gaussian), bias (constant offset), scale
(multiplicative factor), fail (zero output). Faults shall have an
optional duration after which they expire automatically. Fault injection
shall be deterministic when seeded.

**SVF-DEV-133** `[GND]` `IMPLEMENTED`
The platform shall provide a YamcsBridge that connects a running SVF simulation to a YAMCS ground station instance. The bridge shall expose a TCP server on port 10015 for TM downlink and a UDP server on port 10025 for TC uplink.

**SVF-DEV-134** `[GND]` `IMPLEMENTED`
The YamcsBridge shall forward raw PUS TM packets from the OBC emulator to YAMCS in real time over the TM TCP connection.

**SVF-DEV-135** `[GND]` `IMPLEMENTED`
The YamcsBridge shall receive PUS TC packets from YAMCS via UDP and queue them for delivery to the OBC emulator on the next simulation tick.

**SVF-DEV-136** `[GND]` `IMPLEMENTED`
The platform shall provide a generate_xtce.py tool that auto-generates an XTCE mission database from the SRDB. The generated XTCE shall define a PUS_Packet abstract base container with RestrictionCriteria on all child containers so each TM service/subservice is correctly identified in the YAMCS packet viewer.

**SVF-DEV-137** `[GND]` `IMPLEMENTED`
The platform shall provide start-yamcs.sh and stop-yamcs.sh scripts that download YAMCS 5.12.6, write the instance configuration, and start/stop the YAMCS server on port 8090.

**SVF-DEV-138** `[GND]` `IMPLEMENTED`
The YAMCS instance configuration shall use PusPacketPreprocessor with useLocalGenerationTime=true so TM packets are timestamped with reception time rather than the PUS secondary header time field.

---

## AOCS Equipment Model Requirements [MOD]

**SVF-DEV-139** `[MOD]` `IMPLEMENTED`
The CSS model shall output a normalised illumination value in [0, 1] when sun-facing and 0.0 when the sun vector is behind the panel or the unit is powered off.

**SVF-DEV-140** `[MOD]` `IMPLEMENTED`
The gyroscope model shall output angular rate equal to the true rate plus additive Gaussian noise when powered, and 0.0 when powered off. Bias shall accumulate over time.

**SVF-DEV-141** `[MOD]` `IMPLEMENTED`
The magnetometer model shall output the true magnetic field vector plus additive Gaussian noise when powered, and 0.0 on all axes when powered off.

**SVF-DEV-142** `[MOD]` `IMPLEMENTED`
The magnetorquer model shall accept a dipole moment command and output a magnetic torque proportional to the dipole command cross the local magnetic field vector. Output shall be 0.0 when powered off.

**SVF-DEV-143** `[MOD]` `IMPLEMENTED`
The reaction wheel model shall integrate angular momentum from torque commands, saturate at maximum speed, and report the current speed. Speed shall be independent across multiple instances.

**SVF-DEV-144** `[MOD]` `IMPLEMENTED`
The star tracker model shall output a valid quaternion within acquisition time when powered and sun-exclusion constraints are met, and output a no-fix flag during acquisition or when the sun is in the exclusion zone.

**SVF-DEV-145** `[MOD]` `IMPLEMENTED`
The b-dot controller model shall output a dipole moment command proportional to the negative time-derivative of the magnetic field measurement, implementing the b-dot detumbling law.

**SVF-DEV-146** `[MOD]` `IMPLEMENTED`
The thermal model shall increase panel temperature when the solar illumination input is non-zero (sun-facing heating), and decrease panel temperature when illumination is zero (eclipse cooling), converging towards the respective equilibrium temperature.

**SVF-DEV-147** `[MOD]` `IMPLEMENTED`
The thermal model shall add equipment dissipation power to the cavity temperature node, raising cavity temperature proportionally to the sum of active equipment dissipation.

**SVF-DEV-148** `[MOD]` `IMPLEMENTED`
The thermal model shall maintain the radiator panel temperature strictly below the sun-facing panel temperature during steady-state illumination, reflecting the radiator's cooler thermal environment.

**SVF-DEV-149** `[SIM]` `IMPLEMENTED`
The OBT parameter file loader shall parse a tab/space-delimited file with three columns (OBT, PARAM_NAME, VALUE); blank lines and lines beginning with `#` shall be ignored; lines with wrong column count or non-numeric OBT/VALUE shall raise `ValueError` with the offending line number.

**SVF-DEV-150** `[SIM]` `IMPLEMENTED`
`SimulationMaster` shall accept an `ObtParamFile` and, on each simulation tick, inject all entries whose OBT is less than or equal to the current simulation time into the `CommandStore`, with each entry injected exactly once in OBT-ascending order.

**SVF-DEV-151** `[SIM]` `IMPLEMENTED`
The spacecraft configuration loader shall accept `simulation.obt_init_file` as a path (resolved relative to the spacecraft YAML directory) and load it as an `ObtParamFile` passed to `SimulationMaster`.

**SVF-DEV-152** `[CFG]` `IMPLEMENTED`
The spacecraft pre-flight validator (`SpacecraftValidator`) shall detect and report duplicate equipment IDs, wiring overrides that reference undefined equipment, and OBT parameter init file problems (missing file, parse errors) — all without instantiating DDS, models, or a tick source.

**SVF-DEV-153** `[CFG]` `IMPLEMENTED`
The spacecraft pre-flight validator shall detect bus address conflicts within each declared bus: duplicate CAN message IDs (CAN 2.0B), duplicate SpaceWire logical addresses, and duplicate MIL-STD-1553 RT/SA pairs.

**SVF-DEV-154** `[TOOLS]` `IMPLEMENTED`
The SRDB consistency checker (`checkcons`) shall verify that every OUT port declared by a NativeEquipment model factory has a corresponding `ParameterDefinition` in the SRDB baseline. Ports absent from the SRDB and not listed in `KNOWN_NAMESPACE_GAPS` shall be reported as errors. SRDB TM parameters with no model OUT port shall be reported as warnings.

**SVF-DEV-155** `[TOOLS]` `IMPLEMENTED`
The requirement coverage checker (`checkcov`) shall include a fidelity section reporting the F1–F4 fidelity level for each equipment model and the count of TM parameters with and without a `CalibrationCurve`. Models with F2 fidelity and uncalibrated TM parameters shall be flagged as F2→F3 upgrade candidates. Models where a `CalibrationCurve` exists in the SRDB but the declared fidelity level is F1 or F2 shall cause `checkcov` to exit non-zero as an inconsistency error.

**SVF-DEV-156** `[SIM]` `IMPLEMENTED`
`SimulationMaster` shall wrap each equipment `tick()` failure as an `EquipmentTickError` carrying `equipment_id`, `obt`, `cause`, and a structured `context` dict. An `on_tick_error` callback (default: re-raise as `SimulationError`) allows L3/L4 harnesses to choose record-and-continue behaviour without modifying `SimulationMaster`.

**SVF-DEV-157** `[CAM]` `IMPLEMENTED`
The campaign runner shall track `INCONCLUSIVE` verdicts separately from `PASS`, `FAIL`, and `ERROR`. A `Procedure` subclass may raise `ProcedureInconclusiveError` to produce an `INCONCLUSIVE` result. `CampaignReport` shall expose `n_inconclusive` and include the count in `to_dict()` and the HTML report summary.

**SVF-DEV-158** `[CAM]` `IMPLEMENTED`
A campaign YAML may declare a `requirements:` list of mission requirement IDs. `CampaignRunner` shall track which declared requirements have no covering procedure and expose them via `CampaignReport.uncovered_requirements`. The HTML report shall show each declared requirement's status as COVERED, FAILED, INCONCLUSIVE, or UNCOVERED.


**GAP-014** `[SYS]` `IMPLEMENTED`
The platform shall provide a `svf` command-line entrypoint (registered
as a console_scripts entry point in pyproject.toml) with the following
subcommands: `run <spacecraft.yaml>` (run a simulation), `validate
<spacecraft.yaml>` (fast pre-flight check, no DDS), `campaign
<campaign.yaml>` (run a test campaign), `campaign --report` (run and
generate an HTML report), `profiles` (list available hardware profiles),
`check <spacecraft.yaml>` (full config load without running).

---
 
## Power Conditioning and Distribution Unit Requirements [PCDU]
 
**PCDU-001** `[PCDU]` `IMPLEMENTED`
The PCDU model shall support per-channel load switching via 8 independent
Latching Current Limiters (LCLs). Each LCL shall accept an enable command
and report its status independently.
 
**PCDU-002** `[PCDU]` `IMPLEMENTED`
The PCDU model shall implement a simplified Maximum Power Point Tracking
(MPPT) efficiency curve. The efficiency shall peak at a nominal
illumination level and degrade towards zero and full illumination extremes.
 
**PCDU-003** `[PCDU]` `IMPLEMENTED`
The PCDU model shall implement Under-Voltage Lock-Out (UVLO) protection.
When battery voltage falls below the UVLO threshold (3.1 V), all LCL
loads shall be disconnected to protect the battery from deep discharge.
 
**PCDU-004** `[PCDU]` `IMPLEMENTED`
The PCDU model shall compute power balance each tick: effective solar
power (solar_power × MPPT_efficiency) minus total LCL load equals net
power; charge current shall be derived from net power and battery voltage,
clamped to ±MAX_CHARGE_CURRENT.
 
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
| SVF-DEV-096 | SDB | IMPLEMENTED | M31 | test_srdb_calibration |
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
| SVF-DEV-048 | ORC | IMPLEMENTED | M4.5 | test_tc_pwr_003_charging_in_sunlight |
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
| SVF-DEV-066 | MOD | IMPLEMENTED | M4.5 | test_decomposed_eps_charges_in_sunlight |
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
| PCDU-001      | PCDU | IMPLEMENTED | M9  | test_pcdu_lcl_switching         |
| PCDU-002      | PCDU | IMPLEMENTED | M9  | test_pcdu_mppt_efficiency        |
| PCDU-003      | PCDU | IMPLEMENTED | M9  | test_pcdu_uvlo_disconnects_loads  |
| PCDU-004      | PCDU | IMPLEMENTED | M9  | test_pcdu_power_balance          |
| SVF-DEV-100   | SYS  | IMPLEMENTED | M24 | test_aarch64_starts_and_prints_version |
| SVF-DEV-101   | SYS  | IMPLEMENTED | M24 | test_renode_zynqmp_ping_pong     |
| SVF-DEV-110   | SYS  | IMPLEMENTED | M19 | test_spacecraft_loader           |
| SVF-DEV-120   | SIM  | IMPLEMENTED | M24 | test_monte_carlo_runs            |
| SVF-DEV-121   | CAM  | IMPLEMENTED | M20 | test_campaign_runs_all_procedures |
| SVF-DEV-122   | CAM  | IMPLEMENTED | M21 | test_generates_html_file         |
| SVF-DEV-130   | SYS  | IMPLEMENTED | M16 | test_load_hardware_profile       |
| SVF-DEV-131   | ORC  | IMPLEMENTED | M23 | test_compliant_when_no_violations |
| SVF-DEV-132   | EQP  | IMPLEMENTED | M23 | test_stuck_fault_returns_fixed_value |
| SVF-DEV-133   | GND  | IMPLEMENTED | M25 | test_bridge_accepts_yamcs_tm_connection |
| SVF-DEV-134   | GND  | IMPLEMENTED | M25 | test_bridge_sends_tm_to_yamcs |
| SVF-DEV-135   | GND  | IMPLEMENTED | M25 | test_bridge_receives_tc_from_yamcs |
| SVF-DEV-136   | GND  | IMPLEMENTED | M25 | test_xtce_generation |
| SVF-DEV-137   | GND  | IMPLEMENTED | M25 | test_yamcs_start_stop |
| SVF-DEV-138   | GND  | IMPLEMENTED | M25 | test_bridge_receives_tc_from_yamcs |
| SVF-DEV-139   | MOD  | IMPLEMENTED | M26 | test_css_illumination_facing_sun |
| SVF-DEV-140   | MOD  | IMPLEMENTED | M26 | test_gyro_rate_output_with_noise |
| SVF-DEV-141   | MOD  | IMPLEMENTED | M26 | test_magnetometer_powered_and_off |
| SVF-DEV-142   | MOD  | IMPLEMENTED | M26 | test_magnetorquer_torque_output |
| SVF-DEV-143   | MOD  | IMPLEMENTED | M26 | test_rw_speed_integration |
| SVF-DEV-144   | MOD  | IMPLEMENTED | M26 | test_star_tracker_acquires_fix |
| SVF-DEV-145   | MOD  | IMPLEMENTED | M26 | test_bdot_dipole_output |
| SVF-DEV-146   | MOD  | IMPLEMENTED | M26 | test_sun_facing_panel_heats_up |
| SVF-DEV-147   | MOD  | IMPLEMENTED | M26 | test_equipment_dissipation_heats_internal |
| SVF-DEV-148   | MOD  | IMPLEMENTED | M26 | test_radiator_panel_cooler_than_sun_panel |
| SVF-DEV-149   | SIM  | IMPLEMENTED | M29 | test_obt_parse_happy_path |
| SVF-DEV-150   | SIM  | IMPLEMENTED | M29 | test_simulation_master_injects_obt_entries_at_correct_time |
| SVF-DEV-151   | SIM  | IMPLEMENTED | M29 | test_obt_parse_happy_path |
| SVF-DEV-152   | CFG  | IMPLEMENTED | M32 | test_clean_config_no_issues |
| SVF-DEV-153   | CFG  | IMPLEMENTED | M32 | test_can_duplicate_id_raises_error |
| SVF-DEV-154   | TOOLS| IMPLEMENTED | M33 | test_check_srdb_namespace_passes_on_current_codebase |
| SVF-DEV-155   | TOOLS| IMPLEMENTED | M34 | test_fidelity_report_returns_true_on_clean_srdb |
| SVF-DEV-156   | SIM  | IMPLEMENTED | M35 | test_default_handler_reraises_as_simulation_error |
| SVF-DEV-157   | CAM  | IMPLEMENTED | M36 | test_inconclusive_counted |
| SVF-DEV-158   | CAM  | IMPLEMENTED | M36 | test_declared_requirements_uncovered |
| SVF-DEV-159   | BUS  | IMPLEMENTED | M38 | test_get_tm_queue_returns_and_drains_parsed_packet |
| SVF-DEV-160   | BUS  | IMPLEMENTED | M38 | test_on_s3_25_updates_hk_ports |
| SVF-DEV-161   | BUS  | IMPLEMENTED | M38 | test_consecutive_desync_raises_after_max_desync |
| SVF-DEV-162   | PUS  | IMPLEMENTED | M37 | test_s9_build_and_parse_roundtrip |
| SVF-DEV-163   | PUS  | IMPLEMENTED | M38 | test_scheduler_due_returns_tc_at_correct_obt |
| SVF-DEV-164   | PUS  | IMPLEMENTED | M39 | test_monitor_high_limit_fires_once_on_entry |
| CAN-001       | CAN  | IMPLEMENTED | M30 | test_extended_id_out_of_range_raises |
| CAN-002       | CAN  | IMPLEMENTED | M30 | test_tx_message_routed_to_command_store |
| CAN-003       | CAN  | IMPLEMENTED | M30 | test_bus_error_fault_causes_bus_off |
| CAN-004       | CAN  | IMPLEMENTED | M30 | test_fault_injected_via_command_store |
| SPW-001       | SPW  | IMPLEMENTED | M30 | test_logical_address_below_minimum_raises |
| SPW-002       | SPW  | IMPLEMENTED | M30 | test_rmap_write_routes_to_command_store |
| SPW-003       | SPW  | IMPLEMENTED | M30 | test_rmap_read_routes_to_canonical_telemetry |
| SPW-004       | SPW  | IMPLEMENTED | M30 | test_fault_injected_via_command_store |
| GAP-014       | SYS  | IMPLEMENTED | M19 | test_check_valid_config_returns_zero |