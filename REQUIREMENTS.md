# SVF Development Requirements

> **Status:** Draft — v0.1  
> **Last updated:** 2026-03  
> **Author:** TBD

---

## Overview

This document defines the development requirements for the Software Validation Facility (SVF) platform itself. These are distinct from the requirements of any spacecraft system being validated using SVF — they describe what SVF must do and how it must behave as a tool.

Requirements are identified by the prefix `SVF-DEV-` followed by a zero-padded sequence number. Each requirement belongs to a functional area, indicated by the area tag in square brackets.

### Functional Areas

| Tag | Area |
|---|---|
| `[SIM]` | Simulation Core |
| `[BUS]` | Communication Bus |
| `[ORC]` | Test Orchestration |
| `[CAM]` | Campaign Manager |
| `[MOD]` | Model Authoring |
| `[REP]` | Reporting & Traceability |
| `[SYS]` | System & Infrastructure |

### Requirement Status Values

| Status | Meaning |
|---|---|
| `DRAFT` | Under discussion, not yet baselined |
| `BASELINED` | Agreed and frozen for current milestone |
| `IMPLEMENTED` | Closed by a committed and merged implementation |
| `DEFERRED` | Out of scope for current milestone, retained for future |

---

## Simulation Core Requirements `[SIM]`

**SVF-DEV-001** `[SIM]` `DRAFT`  
The simulation master shall support loading and instantiating FMUs compliant with the FMI 3.0 standard.

**SVF-DEV-002** `[SIM]` `DRAFT`  
The simulation master shall support fixed-timestep execution of a single FMU.

**SVF-DEV-003** `[SIM]` `DRAFT`  
The simulation master shall support variable-timestep execution where the FMU exposes a step-size negotiation interface.

**SVF-DEV-004** `[SIM]` `DRAFT`  
The simulation master shall support co-simulation of multiple FMUs connected according to an SSP system description file.

**SVF-DEV-005** `[SIM]` `DRAFT`  
The simulation master shall record all FMU output variables to a time-stamped CSV log for each simulation run.

**SVF-DEV-006** `[SIM]` `DRAFT`  
The simulation master shall expose a clean start, step, and teardown lifecycle API consumable by the test orchestration layer.

**SVF-DEV-007** `[SIM]` `DRAFT`  
The simulation master shall handle FMU initialisation errors gracefully and report them with sufficient detail to identify the failing FMU and variable.

**SVF-DEV-008** `[SIM]` `DEFERRED`  
The simulation master shall support FMI 3.0 Scheduled Execution mode for deterministic clock-driven stepping (prerequisite for real-time support).

---

## Communication Bus Requirements `[BUS]`

**SVF-DEV-010** `[BUS]` `DRAFT`  
The communication bus shall be implemented over Eclipse Cyclone DDS using the DDS publish/subscribe model.

**SVF-DEV-011** `[BUS]` `DRAFT`  
The bus shall publish FMU output variables as typed DDS topics with configurable QoS policies per topic.

**SVF-DEV-012** `[BUS]` `DRAFT`  
The bus shall support subscription to DDS command topics and injection of received values into FMU input variables.

**SVF-DEV-013** `[BUS]` `DRAFT`  
The bus shall support at minimum the following QoS modes: reliable delivery, best-effort delivery, and last-value caching.

**SVF-DEV-014** `[BUS]` `DRAFT`  
The bus shall support deadline monitoring: flagging a topic as overdue if no sample has been received within a configured period.

**SVF-DEV-015** `[BUS]` `DRAFT`  
The bus integration shall be implemented as a plugin, such that alternative transport backends can be substituted without modifying the simulation master or orchestration layers.

**SVF-DEV-016** `[BUS]` `DEFERRED`  
A CCSDS adapter plugin shall bridge DDS topics to CCSDS APID-addressed TM/TC packet streams.

**SVF-DEV-017** `[BUS]` `DEFERRED`  
A SpaceWire adapter plugin shall bridge DDS topics to SpaceWire logical address-routed packets.

---

## Test Orchestration Requirements `[ORC]`

**SVF-DEV-020** `[ORC]` `DRAFT`  
The test orchestration layer shall be implemented as a pytest plugin, compatible with pytest 7.x and above.

**SVF-DEV-021** `[ORC]` `DRAFT`  
The plugin shall provide a simulation lifecycle fixture that starts the simulation master before a test, and performs clean teardown after the test regardless of outcome.

**SVF-DEV-022** `[ORC]` `DRAFT`  
The plugin shall provide a stimuli injection API allowing test procedures to send commands and inject values into the simulation via the communication bus.

**SVF-DEV-023** `[ORC]` `DRAFT`  
The plugin shall provide an observable assertion API that evaluates telemetry conditions with configurable time bounds (e.g. "parameter X shall reach value Y within T seconds").

**SVF-DEV-024** `[ORC]` `DRAFT`  
The plugin shall map test outcomes to ECSS-compatible verdicts: PASS, FAIL, INCONCLUSIVE, and ERROR.

**SVF-DEV-025** `[ORC]` `DRAFT`  
The plugin shall capture a full execution timeline for each test, recording timestamps of stimuli injection events, observable evaluations, and verdict assignment.

**SVF-DEV-026** `[ORC]` `DRAFT`  
The orchestration layer shall support parallel test execution via pytest-xdist without requiring shared mutable simulation state between workers.

**SVF-DEV-027** `[ORC]` `DRAFT`  
Each test procedure shall be expressible as a standalone Python file with no mandatory inheritance from SVF base classes.

---

## Campaign Manager Requirements `[CAM]`

**SVF-DEV-030** `[CAM]` `DRAFT`  
The campaign manager shall accept test campaign definitions expressed in YAML format.

**SVF-DEV-031** `[CAM]` `DRAFT`  
A campaign definition shall specify: a unique campaign identifier, a model configuration baseline identifier, a list of requirement IDs under verification, and an ordered list of test case references.

**SVF-DEV-032** `[CAM]` `DRAFT`  
The campaign manager shall validate campaign YAML files against a published schema before execution, reporting all schema violations before any test is started.

**SVF-DEV-033** `[CAM]` `DRAFT`  
The campaign manager shall record the campaign definition file, its SHA-256 hash, and the SVF version used as part of every campaign execution record.

**SVF-DEV-034** `[CAM]` `DRAFT`  
The campaign manager shall support per-test-case timeout configuration, aborting and marking a test as ERROR if execution exceeds the defined timeout.

**SVF-DEV-035** `[CAM]` `DEFERRED`  
The campaign manager shall support conditional test execution: skipping or including test cases based on the outcome of previously executed tests in the same campaign.

---

## Model Authoring Requirements `[MOD]`

**SVF-DEV-040** `[MOD]` `DRAFT`  
The platform shall support FMUs authored in Python using the pythonfmu library as first-class simulation components.

**SVF-DEV-041** `[MOD]` `DRAFT`  
The platform shall support FMUs authored in C or C++ compiled to shared libraries conforming to the FMI 3.0 binary interface.

**SVF-DEV-042** `[MOD]` `DRAFT`  
The platform shall provide a Python decorator API (`@svf.model`, `@svf.input`, `@svf.output`, `@svf.state`) that generates FMI-compliant scaffolding with minimal boilerplate.

**SVF-DEV-043** `[MOD]` `DRAFT`  
The platform shall provide a C macro API equivalent to the Python decorator API for performance-critical model authoring.

**SVF-DEV-044** `[MOD]` `DRAFT`  
All SVF-native models shall produce FMI 3.0 compliant FMU archives, usable in any third-party FMI-compliant simulation environment.

**SVF-DEV-045** `[MOD]` `DEFERRED`  
The platform shall provide an SMP2 model importer that converts SMP2-compliant model packages into FMI 3.0 FMUs.

---

## Reporting & Traceability Requirements `[REP]`

**SVF-DEV-050** `[REP]` `DRAFT`  
The platform shall produce JUnit XML test result reports natively from pytest, consumable by Jenkins, GitLab CI, and GitHub Actions without additional configuration.

**SVF-DEV-051** `[REP]` `DRAFT`  
The platform shall produce structured test records aligned with ECSS-E-ST-10-02C, including: test case ID, objective, configuration baseline, preconditions, execution steps, observations, and verdict.

**SVF-DEV-052** `[REP]` `DRAFT`  
Each test case shall declare the requirement IDs it verifies, expressed as pytest markers and in the campaign YAML file.

**SVF-DEV-053** `[REP]` `DRAFT`  
The reporting layer shall generate a requirements traceability matrix mapping each declared requirement ID to the test cases that verify it and their verdicts.

**SVF-DEV-054** `[REP]` `DRAFT`  
All reports shall include the campaign ID, model configuration baseline, SVF version, and execution timestamp as header metadata.

**SVF-DEV-055** `[REP]` `DRAFT`  
The platform shall produce an HTML report via Allure, rendered from the same structured data used for the ECSS certification report.

**SVF-DEV-056** `[REP]` `DEFERRED`  
The platform shall provide an adapter for exporting traceability data to IBM DOORS NG via its REST API.

**SVF-DEV-057** `[REP]` `DEFERRED`  
The platform shall provide an adapter for exporting traceability data to Jama Connect via its REST API.

---

## System & Infrastructure Requirements `[SYS]`

**SVF-DEV-060** `[SYS]` `DRAFT`  
The SVF core shall be packaged as a pip-installable Python package using `pyproject.toml`.

**SVF-DEV-061** `[SYS]` `DRAFT`  
The platform shall support Linux (Ubuntu 22.04 LTS and above) as the primary execution environment.

**SVF-DEV-062** `[SYS]` `DRAFT`  
The platform shall support macOS (Monterey and above) as a secondary supported execution environment.

**SVF-DEV-063** `[SYS]` `DRAFT`  
The platform shall support Windows 10 and above as a best-effort execution environment.

**SVF-DEV-064** `[SYS]` `DRAFT`  
Each simulation run shall be executable inside a Docker container, with no dependency on host-installed software beyond Docker itself.

**SVF-DEV-065** `[SYS]` `DRAFT`  
The build system for mixed Python/C components shall use CMake with scikit-build-core.

**SVF-DEV-066** `[SYS]` `DRAFT`  
FMU binary artefacts shall be managed in Git with Git LFS.

**SVF-DEV-067** `[SYS]` `DRAFT`  
The SVF codebase shall maintain a minimum test coverage of 80% on the orchestration and campaign manager layers, measured on every CI run.

**SVF-DEV-068** `[SYS]` `DRAFT`  
The platform shall expose a public Python API with type annotations throughout, compatible with mypy strict mode.

**SVF-DEV-069** `[SYS]` `DEFERRED`  
The platform shall support soft real-time execution on Linux hosts running the RT_PREEMPT kernel patch, with no changes required to model or test procedure code.

---

## Traceability Index

This index is updated automatically by the reporting layer during campaign execution. Manual updates here are for reference only.

| Requirement ID | Area | Status | Verified By |
|---|---|---|---|
| SVF-DEV-001 | SIM | DRAFT | — |
| SVF-DEV-002 | SIM | DRAFT | — |
| SVF-DEV-003 | SIM | DRAFT | — |
| SVF-DEV-004 | SIM | DRAFT | — |
| SVF-DEV-005 | SIM | DRAFT | — |
| SVF-DEV-006 | SIM | DRAFT | — |
| SVF-DEV-007 | SIM | DRAFT | — |
| SVF-DEV-008 | SIM | DEFERRED | — |
| SVF-DEV-010 | BUS | DRAFT | — |
| SVF-DEV-011 | BUS | DRAFT | — |
| SVF-DEV-012 | BUS | DRAFT | — |
| SVF-DEV-013 | BUS | DRAFT | — |
| SVF-DEV-014 | BUS | DRAFT | — |
| SVF-DEV-015 | BUS | DRAFT | — |
| SVF-DEV-016 | BUS | DEFERRED | — |
| SVF-DEV-017 | BUS | DEFERRED | — |
| SVF-DEV-020 | ORC | DRAFT | — |
| SVF-DEV-021 | ORC | DRAFT | — |
| SVF-DEV-022 | ORC | DRAFT | — |
| SVF-DEV-023 | ORC | DRAFT | — |
| SVF-DEV-024 | ORC | DRAFT | — |
| SVF-DEV-025 | ORC | DRAFT | — |
| SVF-DEV-026 | ORC | DRAFT | — |
| SVF-DEV-027 | ORC | DRAFT | — |
| SVF-DEV-030 | CAM | DRAFT | — |
| SVF-DEV-031 | CAM | DRAFT | — |
| SVF-DEV-032 | CAM | DRAFT | — |
| SVF-DEV-033 | CAM | DRAFT | — |
| SVF-DEV-034 | CAM | DRAFT | — |
| SVF-DEV-035 | CAM | DEFERRED | — |
| SVF-DEV-040 | MOD | DRAFT | — |
| SVF-DEV-041 | MOD | DRAFT | — |
| SVF-DEV-042 | MOD | DRAFT | — |
| SVF-DEV-043 | MOD | DRAFT | — |
| SVF-DEV-044 | MOD | DRAFT | — |
| SVF-DEV-045 | MOD | DEFERRED | — |
| SVF-DEV-050 | REP | DRAFT | — |
| SVF-DEV-051 | REP | DRAFT | — |
| SVF-DEV-052 | REP | DRAFT | — |
| SVF-DEV-053 | REP | DRAFT | — |
| SVF-DEV-054 | REP | DRAFT | — |
| SVF-DEV-055 | REP | DRAFT | — |
| SVF-DEV-056 | REP | DEFERRED | — |
| SVF-DEV-057 | REP | DEFERRED | — |
| SVF-DEV-060 | SYS | DRAFT | — |
| SVF-DEV-061 | SYS | DRAFT | — |
| SVF-DEV-062 | SYS | DRAFT | — |
| SVF-DEV-063 | SYS | DRAFT | — |
| SVF-DEV-064 | SYS | DRAFT | — |
| SVF-DEV-065 | SYS | DRAFT | — |
| SVF-DEV-066 | SYS | DRAFT | — |
| SVF-DEV-067 | SYS | DRAFT | — |
| SVF-DEV-068 | SYS | DRAFT | — |
| SVF-DEV-069 | SYS | DEFERRED | — |
