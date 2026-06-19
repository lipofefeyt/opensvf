---
title: "OpenSVF  -  Software Validation Specification"
subtitle: "SVF-SVS-001 | Issue 1.0"
author: "Gonçalo Graças"
date: "2026-05-23"
subject: "Software Validation Specification"
keywords: [spacecraft, validation, V&V, PUS-C, SIL, ECSS, requirements, traceability]
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
header-left: "SVF-SVS-001"
header-right: "OpenSVF Software Validation Specification"
footer-left: "Issue 1.0  -  2026-05-23"
footer-right: "Page \\thepage"
classoption: oneside
---

# Introduction

## Purpose

This document specifies the validation strategy, test levels, acceptance
criteria, and traceability approach for **OpenSVF** (v0.7.1). It is the
governing V&V plan for the opensvf platform itself and defines the framework
within which operators use OpenSVF to validate their own flight software.

## Scope

This document covers validation of the `opensvf` Python package. It does not
specify validation of the flight software under test (openobsw)  -  that is
the operator's responsibility, and OpenSVF is the tool they use to discharge
it. The distinction is important:

> Levels 1–3 validate **OpenSVF itself**  -  that the simulation framework
> behaves correctly.
>
> Level 4 validates the **operator's OBSW** using OpenSVF as an instrument.
> L4 campaigns produce V&V evidence for the OBSW, not for OpenSVF.

## Applicable Documents

| Reference | Title |
|---|---|
| ECSS-E-ST-70-41C | Space Engineering  -  Telemetry and Telecommand Packet Utilisation |
| ECSS-E-HB-40A | Software Engineering Handbook |
| SVF-ADD-001 | OpenSVF Architecture Description Document |
| SVF-ICD-001 | OpenSVF Interface Control Document |
| `REQUIREMENTS.md` | OpenSVF Development Requirements (v1.1) |
| `VALIDATION.md` | OpenSVF Validation Strategy (v1.0) |
| `docs/sil-attitude-validation-guide.md` | SIL Attitude Validation  -  M13 Results |

## Terms and Abbreviations

| Term | Definition |
|---|---|
| ADCS | Attitude Determination and Control System |
| FDIR | Failure Detection, Isolation, and Recovery |
| HIL | Hardware-In-the-Loop |
| OBSW | On-Board Software |
| SIL | Software-In-the-Loop |
| SVF | Software Validation Facility |
| V&V | Verification and Validation |

---

# Validation Philosophy

## What OpenSVF Validates

OpenSVF answers a single question for the operator:

> *Does the flight software behave correctly against real physics and a real
> ground station?*

This is structurally different from MIL (Model-In-the-Loop) validation in
Simulink, which validates a design model against itself. OpenSVF validates
the **actual flight C code** that will run on the target hardware  -  against
a physics plant model, real sensor noise, and a real ground station. The
statistical performance it measures is the performance of the code that
flies, not a model of it.

## Determinism as a Validation Requirement

All validation runs in OpenSVF are fully deterministic and reproducible.
Per-model noise seeds are derived from a master seed via SHA-256. A test that
cannot be replayed is not a validation artefact. The seed manifest is
persisted to `results/seed.json` after every run.

Non-deterministic tests are a design error, not a known limitation.

## The Requirement Lifecycle

Requirements in `REQUIREMENTS.md` pass through the following states:

| Status | Meaning |
|---|---|
| `DRAFT` | Under discussion; not yet agreed |
| `BASELINED` | Agreed and frozen for the current milestone |
| `IMPLEMENTED` | Closed by a committed, merged, and tested implementation |
| `DEFERRED` | Out of scope for the current milestone |
| `SUPERSEDED` | Replaced by a later requirement |

A requirement reaches `IMPLEMENTED` status only when a `@pytest.mark.requirement`
marker referring to it appears in `results/traceability.txt` after a clean
`testosvf` run, or when a documented `KNOWN_GAPS` entry with an explicit
justification records why the requirement is verified by other means.

---

# Validation Pyramid

OpenSVF validation is structured in four levels. Each level adds external
dependencies and scope. CI covers L1 and L2 only.

```
┌──────────────────────────────────────────────────────────┐
│  Level 4  -  Operator Campaigns                            │
│  Validates the OBSW using the validated SVF              │
│  svf campaign <campaign.yaml> --report                   │
├──────────────────────────────────────────────────────────┤
│  Level 3  -  System / SIL Tests                            │
│  Full spacecraft, real binaries, Renode / QEMU           │
│  pytest tests/system/                                    │
├──────────────────────────────────────────────────────────┤
│  Level 2  -  Integration Tests                             │
│  Two or more SVF blocks, FMU infrastructure, DDS sync   │
│  testosvf  (tests/integration/)                          │
├──────────────────────────────────────────────────────────┤
│  Level 1  -  Unit Tests                                    │
│  Individual SVF classes, no binaries, no DDS             │
│  testosvf  (tests/unit/)                                 │
└──────────────────────────────────────────────────────────┘
```

*Table 1  -  Validation level summary*

| Level | Label | External prerequisites | Scope | CI |
|---|---|---|---|---|
| L1 | Unit | None | Equipment physics, PUS stack, stores, SRDB | Yes |
| L2 | Integration | `SimpleCounter.fmu` | FMU adapter, DDS sync, wiring, YAMCS bridge | Yes |
| L3 | System / SIL | `SpacecraftDynamics.fmu` + `obsw_sim` | Wire protocol, closed-loop ADCS, Renode | No |
| L4 | Campaign | Mission `spacecraft.yaml` | OBSW procedure validation, HTML report | No |

---

# Test Environments

## L1/L2  -  CI Environment

| Property | Value |
|---|---|
| Platform | Ubuntu 24.04, Python 3.12 |
| CI runner | GitHub Actions |
| Test runner | `pytest` via `testosvf` alias |
| FMU required | `models/SimpleCounter.fmu` (L2 only; committed to repo) |
| External binaries | None |
| DDS | Eclipse Cyclone DDS (installed via pip) |
| Execution | Fast-as-possible (`SoftwareTickSource`) |

## L3  -  System Test Environment

| Property | Value |
|---|---|
| Platform | Ubuntu 24.04, Python 3.12 |
| External binaries | `bin/obsw_sim` (x86_64) or `bin/obsw_sim_aarch64` (aarch64) |
| FMU required | `models/SpacecraftDynamics.fmu` (from opensvf-kde) |
| QEMU (optional) | `qemu-aarch64` for aarch64 binary validation |
| Renode (optional) | Renode 1.15.3 for ZynqMP socket-mode validation |
| Execution | Fast-as-possible; realtime for wall-clock timing tests |

L3 tests are excluded from the default `testosvf` run via `norecursedirs` in
`pyproject.toml`. They must be invoked explicitly:

```bash
pytest tests/system/ -v
```

## L4  -  Campaign Environment

| Property | Value |
|---|---|
| Platform | Any (Linux/macOS) |
| Prerequisites | L3 environment + mission `spacecraft.yaml` |
| Entry point | `svf campaign <campaign.yaml> --report` |
| Report format | Self-contained HTML (`results/<name>_report.html`) |

---

# Acceptance Criteria

## L1/L2 Acceptance

A test passes when its `@pytest.mark.requirement` assertion suite completes
without failure. The overall L1/L2 validation is accepted when:

1. `testosvf` exits with code 0 (all ~453 tests pass)
2. `checkosvf` exits with code 0 (mypy strict  -  zero type errors)
3. `checkcov` exits with code 0  -  all `BASELINED` requirements are covered

**Requirement coverage rule:** Every `BASELINED` requirement must appear in
`results/traceability.txt`, or have an entry in the `KNOWN_GAPS` dict in
`tools/check_coverage.py` with an explicit justification string. Requirements
that are `DRAFT`, `DEFERRED`, or `SUPERSEDED` are exempt from this check.

## L3 Acceptance

Each L3 test defines a quantitative acceptance criterion in its docstring or
assertion. See Section 6 for the SIL ADCS validation criteria. The overall L3
validation is accepted when all tests in `tests/system/` pass for the target
binary and platform configuration.

## L4 Acceptance (Operator OBSW)

Each campaign procedure defines its own acceptance criterion via
`ctx.assert_parameter()`, `ctx.expect_tm()`, and `ctx.wait_condition()` calls.
The procedure verdict is one of:

| Verdict | Meaning |
|---|---|
| `PASS` | All assertions satisfied within time limits |
| `FAIL` | One or more assertions failed |
| `INCONCLUSIVE` | Assertions could not be evaluated (e.g. missing TM) |
| `ERROR` | Unhandled exception during procedure execution |

A campaign is accepted when all procedures return `PASS`. Campaigns with any
`FAIL`, `INCONCLUSIVE`, or `ERROR` verdict are not accepted without dispositioned
non-conformance reports.

---

# Traceability

## Automated Traceability

The SVF pytest plugin (`src/svf/plugin/__init__.py`) writes
`results/traceability.txt` after every `testosvf` run. The file contains one
line per test that carries a `@pytest.mark.requirement` marker:

```
SVF-DEV-001 :: tests/unit/test_simulation_master.py::SimulationSuite::test_...
SVF-DEV-002 :: tests/unit/test_simulation_master.py::SimulationSuite::test_...
```

## `checkcov` Coverage Report

`checkcov` (`tools/check_coverage.py`) reads `results/traceability.txt` and
`REQUIREMENTS.md` and prints:

- All `BASELINED` requirements with their coverage status
- Uncovered `BASELINED` requirements (exit 1 if any found)
- Equipment fidelity level table (F1–F4 per model)

```bash
checkcov
```

## `KNOWN_GAPS`  -  Non-pytest Evidence

Some requirements are verified by means other than pytest markers:

- **CI pipeline checks**  -  `checkcons` struct size check ([1/7]) verifies the
  wire protocol struct byte counts match C layout without running pytest
- **Hardware tests**  -  L3 tests that require `obsw_sim` are not run in CI but
  are covered in the KNOWN_GAPS with a reference to the L3 test file
- **Script verification**  -  requirements verified by `svf validate` or `checkcov`
  output inspection

Every KNOWN_GAPS entry contains an explicit justification string. Undocumented
gaps are treated as uncovered requirements.

## Requirement Naming Convention

| Prefix | Domain | Example |
|---|---|---|
| `SVF-DEV-*` | SVF platform development | `SVF-DEV-001` |
| `KDE-*` | Kinematics & Dynamics Engine | `KDE-001` |
| `EQP-*` | Equipment contract | `EQP-001` |
| `OBC-*` | OBC DHS behaviour | `OBC-001` |
| `PUS-*` | PUS TM/TC | `PUS-001` |
| `1553-*` | MIL-STD-1553B bus | `1553-001` |
| `MIS-*` | Mission / OBSW requirements (L4) | `MIS-AOCS-042` |

---

# Level 1  -  Unit Test Catalogue

All L1 tests reside in `tests/unit/` and run via `testosvf`. Each test class
must end in `Suite` or `Tests` (non-default `python_classes` in
`pyproject.toml`). Test class names ending in `TestFoo` are silently ignored.

*Table 2  -  L1 unit test coverage summary*

| Test file | Requirements covered | Area |
|---|---|---|
| `test_simulation_master.py` | SVF-DEV-001/002/005–007/015/016 | Simulation core |
| `test_variable_timestep.py` | SVF-DEV-003 | Variable dt |
| `test_wiring.py` | SVF-DEV-004 | Auto-wiring |
| `test_parameter_store.py` | SVF-DEV-031/032/033 | Parameter store |
| `test_command_store.py` | SVF-DEV-035/036 | Command store |
| `test_equipment_contract.py` | EQP-001–006, EQP-011/012 | Equipment ABC |
| `test_equipment_fault.py` | SVF-DEV-132 | Fault engine |
| `test_temporal_monitor.py` | SVF-DEV-131 | Temporal assertions |
| `test_mil1553.py` | 1553-001–010 | MIL-STD-1553B |
| `test_can.py` | SVF-DEV-038 | CAN 2.0B |
| `test_bus.py` | 1553-007/008/009 | Bus fault framework |
| `test_replay.py` | SVF-DEV-110 | Deterministic replay |
| `test_srdb_definitions.py` | SVF-DEV-090/091 | SRDB schema |
| `test_srdb_loader.py` | SVF-DEV-092/093 | SRDB YAML parsing |
| `test_srdb_validation.py` | SVF-DEV-094/095 | SRDB range checks |
| `test_spacecraft_loader.py` | SVF-DEV-110 | Spacecraft DSL |
| `test_campaign_runner.py` | SVF-DEV-050–054, SVF-DEV-121 | Campaign runner |
| `test_procedure.py` | SVF-DEV-040–044 | Procedure API |
| `test_procedure_tc_tm.py` | SVF-DEV-037, SVF-DEV-159–161 | Wire protocol, OBC emulator |
| `test_report.py` | SVF-DEV-071/073–075/122 | HTML reporting |
| `test_monte_carlo.py` | SVF-DEV-120 | Monte Carlo runner |
| `test_verdict.py` | SVF-DEV-044 | ECSS verdict mapping |
| `test_observable.py` | SVF-DEV-043 | Observable assertions |
| `test_cli.py` | GAP-014 | SVF CLI subcommands |
| `test_thruster.py` | SVF-DEV-080/081 | Thruster model |
| `test_gps.py` | SVF-DEV-081 | GPS model |
| `test_aocs_models.py` | SVF-DEV-080/081 | AOCS model multi-instance |
| `test_aocs_equipment.py` | SVF-DEV-139–145 | AOCS equipment suite |
| `pus/test_pus_tc.py` | PUS-001/002/003 | PUS-C TC parser |
| `pus/test_pus_tm.py` | PUS-004 | PUS-C TM builder |
| `pus/test_pus_services.py` | PUS-005–011 | PUS service handlers |
| `pus/test_obc.py` | OBC-001 | OBC equipment ports |
| `pus/test_obc_dhs.py` | OBC-001 | OBC DHS mode FSM |
| `pus/test_obc_stub.py` | SVF-DEV-040 | OBC stub rule engine |

---

# Level 2  -  Integration Test Catalogue

All L2 tests reside in `tests/integration/` and run via `testosvf`. They
require `models/SimpleCounter.fmu` to be present.

*Table 3  -  L2 integration test coverage summary*

| Test file | Requirements covered | Area |
|---|---|---|
| `test_fmu_equipment.py` | SVF-DEV-014, SVF-DEV-063/065/066, EQP-007–009/012 | FMU adapter |
| `test_fixtures.py` | SVF-DEV-040–043 | pytest fixture lifecycle |
| `test_lockstep_loop.py` | SVF-DEV-009–012/014–016/020–023/026 | DDS lockstep |
| `test_wiring_integration.py` | SVF-DEV-004 | Auto-wiring propagation |
| `test_dynamics_bridge.py` | KDE-001–004 | KDE FMU ↔ sensor models |
| `test_closed_loop_detumbling.py` | KDE-001–004, SVF-DEV-001/004 | Closed-loop physics |
| `test_yamcs_bridge.py` | SVF-DEV-037 | YAMCS TM/TC bridge |

---

# Level 3  -  System / SIL Test Catalogue

L3 tests reside in `tests/system/` and are excluded from default `testosvf`
runs. They require external binaries. See Section 4 for environment setup.

*Table 4  -  L3 system test coverage summary*

| Test file | Requirements covered | Prerequisites |
|---|---|---|
| `test_obc_emulator.py` | SVF-DEV-029/034/037 | `bin/obsw_sim` |
| `test_obc_emulator_adapter.py` | SVF-DEV-029/034/037 | `bin/obsw_sim` |
| `test_kde_obsw_closed_loop.py` | KDE-001–004 | `bin/obsw_sim` + `SpacecraftDynamics.fmu` |
| `test_kde_obsw_adcs_closed_loop.py` | KDE-001–004 | `bin/obsw_sim` + `SpacecraftDynamics.fmu` |
| `test_aarch64_obsw.py` | SVF-DEV-100 | `bin/obsw_sim_aarch64` + `qemu-aarch64` |
| `test_realtime_detumbling.py` | SVF-DEV-089 | `bin/obsw_sim` |
| `test_renode_zynqmp.py` | SVF-DEV-101 | `renode` + `bin/obsw_zynqmp.bin` |

---

# SIL ADCS Closed-Loop Validation (M13)

This section records the SIL attitude validation performed at Milestone M13.
Full results and procedure details are in `docs/sil-attitude-validation-guide.md`.

## System Under Test

Three-project closed-loop configuration:

```
opensvf-kde (SpacecraftDynamics.fmu)
    → true angular rate ω [rad/s], true B-field [T]
    → Magnetometer model → noisy B measurement
    → Gyroscope model   → noisy angular rate
    → Star tracker model → noisy quaternion

OBCEmulatorAdapter → obsw_sim (C11)
    SAFE mode:    B-dot controller → MTQ dipole commands
    NOMINAL mode: ADCS PD controller → RW torque commands

MTQ model: torque = m × B → KDE (SAFE loop)
RW model:  torque command → KDE (NOMINAL loop)
```

## Software Configuration at Validation

| Component | Version |
|---|---|
| opensvf | v0.6.0 |
| openobsw | v0.5.0+ |
| opensvf-kde | v0.1.0 |

## Test Procedures and Results

*Table 5  -  SIL ADCS validation results*

| Procedure ID | Title | Acceptance Criterion | Result |
|---|---|---|---|
| TC-ADCS-001 | B-dot detumbling reduces angular rate | `|ω_final| < 1.0 rad/s` at t=30s | **PASS** |
| TC-ADCS-002 | MTQ dipole commands reach CommandStore | `cmd_store.peek("aocs.mtq.dipole_x") is not None` | **PASS** |
| TC-ADCS-003 | ADCS PD activates on NOMINAL transition | `cmd_store.peek("aocs.rw1.torque_cmd") is not None` | **PASS** |
| TC-ADCS-004 | Sensor frames drive obsw_sim each tick | `store.read("dhs.obc.obt").value > 4.0` at t=5s | **PASS** |

All tests use deterministic `seed=42` for exact replay.

## Controller Parameters

### B-dot (SAFE mode)

| Parameter | Value | Unit |
|---|---|---|
| Gain k | 1.0 × 10⁴ | Am²·s/T |
| Max dipole | 10.0 | Am² |

### ADCS PD (NOMINAL mode)

| Parameter | Value | Unit |
|---|---|---|
| Kp | 0.5 | N·m/rad |
| Kd | 0.1 | N·m·s/rad |
| Max torque | 0.01 | N·m |
| Target attitude | [1, 0, 0, 0] |  -  |

## Validation Notes

- TC-ADCS-001 uses a conservative threshold (1.0 rad/s). Full detumbling to
  near-zero rates requires 300–600 s depending on initial conditions.
- RW torques are not yet fed back into the KDE FMU. TC-ADCS-003 validates that
  the ADCS controller is active and producing commands  -  not that RW torques
  have closed the NOMINAL loop. RW feedback is planned for M14.
- Star tracker acquisition time is ~10 s from cold start. TC-ADCS-003 injects
  NOMINAL at t≈5 s and relies on the ST entering TRACKING mode during the run.

---

# Level 4  -  Operator Campaign Catalogue

L4 campaigns are in `mission_mysat1/campaigns/`. They validate the MySat-1
OBSW configuration using OpenSVF. They are run via:

```bash
svf campaign mission_mysat1/campaigns/<name>.yaml --report
```

*Table 6  -  MySat-1 campaign summary*

| Campaign file | Procedures | Mission requirements | Description |
|---|---|---|---|
| `aocs_campaign.yaml` | 3 | `MIS-AOCS-*`, `RW-*`, `ST-*` | B-dot convergence, RW fault derate, ST sun blinding |
| `demo_campaign.yaml` | 3 | `MIS-FDIR-001/002/003` | Safe mode recovery three-act scenario |
| `dhs_campaign.yaml` | 3 | `MIS-FDIR-001/002`, `OBC-001` | OBC boot, mode transition, watchdog |
| `platform_campaign.yaml` | 2 | `MIS-PLAT-*` | Platform health, bus routing |

Each procedure references its `requirement` class attribute. Campaigns that
do not trace to requirements are exploration, not validation.

---

# Running the Full Validation Suite

## Complete Sequence

```bash
# Pre-flight: type checking + SRDB consistency
checkosvf && checkcons

# L1 + L2 (CI-equivalent)
testosvf && checkcov

# L3: SIL tests (requires obsw_sim + SpacecraftDynamics.fmu)
pytest tests/system/ -v \
    --ignore=tests/system/test_renode_zynqmp.py \
    --ignore=tests/system/test_aarch64_obsw.py

# L3: ZynqMP (requires Renode + obsw_zynqmp.bin)
renode renode/zynqmp_obsw.resc &
pytest tests/system/test_renode_zynqmp.py -v

# L3: aarch64 QEMU
pytest tests/system/test_aarch64_obsw.py -v   # AARCH64_GLIBC must be set

# L4: MySat-1 campaigns
svf campaign mission_mysat1/campaigns/aocs_campaign.yaml --report
svf campaign mission_mysat1/campaigns/demo_campaign.yaml --report
svf campaign mission_mysat1/campaigns/dhs_campaign.yaml --report
svf campaign mission_mysat1/campaigns/platform_campaign.yaml --report
```

## Pre-PR Ritual

Before any pull request is submitted, the following must all pass:

```bash
checkosvf && testosvf && checkcov && checkcons
```

This ensures type safety, full requirement coverage, and cross-repository SRDB
consistency before any change is merged.

## CI Configuration

The GitHub Actions workflow (`.github/workflows/ci.yml`) runs on every push
and pull request:

1. `pip install -e ".[dev]"` on Ubuntu 24.04 / Python 3.12
2. `pytest tests/`  -  covers L1 and L2 (L3 excluded via `norecursedirs`)
3. Renode ZynqMP job  -  runs on push to `main`, pulls `obsw_zynqmp.bin`
   artifact from the openobsw repository

---

# Validation Constraints and Known Limitations

The following limitations are documented at the time of Issue 1.0. They do
not invalidate any `IMPLEMENTED` requirement but bound the scope of the
current validation evidence.

| ID | Limitation | Impact |
|---|---|---|
| LIM-001 | No orbit propagation or solar radiation pressure | B-field model is dipole only; no environmental perturbations beyond B-field |
| LIM-002 | RW torques not fed back into KDE in NOMINAL loop | ADCS PD controller produces commands (TC-ADCS-003 PASS) but RW loop is open |
| LIM-003 | No quantitative detumbling time statistics | TC-ADCS-001 validates activity, not convergence time distribution |
| LIM-004 | L3 tests excluded from CI | Require external binaries not available in CI environment |
| LIM-005 | YAMCS ground station not validated under load | TM/TC pipeline validated functionally; no latency or throughput characterisation |
| LIM-006 | B-dot and ADCS gain constants not in SRDB | Validation uses literal values from obsw_sim; SRDB parameter entries planned |
