# OpenSVF Validation Strategy

> **Status:** v1.0 — 2026-04
> **Author:** lipofefeyt

---

## Overview

OpenSVF validation follows a four-level pyramid. Each level builds on the
level below it. A requirement is considered validated only when it appears
in `results/traceability.txt` after a successful `testosvf` run, or is
listed in `KNOWN_GAPS` with an explicit justification.

```
┌─────────────────────────────────────────────────────────┐
│  Level 4 — Operator Campaigns                           │
│  Validates OBSW behaviour using the validated SVF       │
│  mission_mysat1/campaigns/    svf campaign ...          │
├─────────────────────────────────────────────────────────┤
│  Level 3 — System Tests                                 │
│  Full spacecraft, all blocks, real binaries             │
│  tests/system/              pytest tests/system/        │
├─────────────────────────────────────────────────────────┤
│  Level 2 — Integration Tests                            │
│  Two or more SVF blocks together                        │
│  tests/integration/           testosvf                  │
├─────────────────────────────────────────────────────────┤
│  Level 1 — Unit Tests                                   │
│  Individual SVF classes in isolation, no binaries       │
│  tests/unit/                          testosvf          │
└─────────────────────────────────────────────────────────┘
```

**Key distinction:**

- Levels 1–3 validate **OpenSVF itself** against `SVF-DEV-*`, `EQP-*`,
  `EPS-*`, `PUS-*`, `1553-*`, and `KDE-*` requirements.
- Level 4 validates **the operator's OBSW** using OpenSVF as a tool.
  These campaigns are not SVF self-validation — they produce V&V evidence
  for the OBSW under test.

Monte Carlo runs, realtime detumbling experiments, and parameter sweeps
are **engineering tools**, not validation artefacts. They do not appear
in this document.

---

## Level 1 — Unit Tests

**What:** Individual SVF classes tested in isolation with no real physics,
no DDS, and no flight binary.

**Run with:** `testosvf`

**Directory:** `tests/unit/`

**Criterion:** No compiled FMU binaries, no DDS, no flight binary. Pure Python + NativeEquipment only.

| Test file | What it validates | Requirements |
|---|---|---|
| `test_parameter_store.py` | ParameterStore thread-safety, read/write, snapshot | SVF-DEV-031/032/033 |
| `test_command_store.py` | CommandStore inject/take atomicity | SVF-DEV-035/036 |
| `test_equipment_contract.py` | Equipment port direction, default values, NativeEquipment teardown | EQP-001 through EQP-006, EQP-011, EQP-012 |
| `test_equipment_fault.py` | EquipmentFaultEngine — stuck, noise, bias, scale, fail | SVF-DEV-132 |
| `test_temporal_monitor.py` | ParameterMonitor threshold checking, violations | SVF-DEV-131 |
| `test_mil1553.py` | MIL-STD-1553B routing, broadcast, fault injection | 1553-001 through 1553-010 |
| `test_can.py` | CAN 2.0B bus routing, fault injection | SVF-DEV-038 |
| `test_bus.py` | Generic bus fault framework (duration, expiry, injection) | 1553-007/008/009 |
| `test_sbt.py` | S-Band transponder model | SVF-DEV-038 |
| `test_wiring.py` | WiringMap validation, duplicate detection | SVF-DEV-004 |
| `test_simulation_master.py` | SimulationMaster lifecycle, NativeEquipment step, CSV logging | SVF-DEV-001/002/005/006/007/015/016 |
| `test_variable_timestep.py` | Variable timestep execution | SVF-DEV-003 |
| `test_replay.py` | Deterministic seed replay | SVF-DEV-110 |
| `test_srdb_definitions.py` | SRDB parameter definition schema | SVF-DEV-090/091 |
| `test_srdb_loader.py` | SrdbLoader YAML parsing, validation | SVF-DEV-092/093 |
| `test_srdb_validation.py` | SRDB range violation warnings, TC/TM classification | SVF-DEV-094/095 |
| `test_spacecraft_loader.py` | SpacecraftLoader YAML → SimulationMaster | SVF-DEV-110 |
| `test_campaign_runner.py` | CampaignRunner execution, verdicts, pass rate | SVF-DEV-050 through SVF-DEV-054, SVF-DEV-121 |
| `test_procedure.py` | Procedure API — steps, assert_parameter, monitor | SVF-DEV-040/041/042/043/044 |
| `test_procedure_tc_tm.py` | ctx.tc() / ctx.expect_tm() PUS commanding | SVF-DEV-037 |
| `test_report.py` | HTML campaign report generation, traceability | SVF-DEV-071/073/074/075/122 |
| `test_monte_carlo.py` | MonteCarloRunner parallel execution, metrics | SVF-DEV-120 |
| `test_verdict.py` | ECSS verdict mapping (PASS/FAIL/INCONCLUSIVE/ERROR) | SVF-DEV-044 |
| `test_observable.py` | Observable assertion API, timeout, polling | SVF-DEV-043 |
| `test_cli.py` | SVF CLI subcommands (run/campaign/check/profiles) | GAP-014 |
| `test_thruster.py` | Thruster propellant burn, temperature rise, Isp | SVF-DEV-080/081 |
| `test_gps.py` | GPS fix acquisition, noise, power-off | SVF-DEV-081 |
| `test_aocs_models.py` | Multi-instance isolation; hardware profile physics application | SVF-DEV-080/081 |
| `test_aocs_equipment.py` | CSS, gyroscope, MAG, MTQ, RW, star tracker, b-dot behaviors | SVF-DEV-139 through SVF-DEV-145 |
| `pus/test_pus_tc.py` | PUS-C TC packet parser, CRC-16 | PUS-001/002/003 |
| `pus/test_pus_tm.py` | PUS-C TM packet builder | PUS-004 |
| `pus/test_pus_services.py` | S1/S3/S5/S6/S8/S17/S20 service handlers | PUS-005 through PUS-011 |
| `pus/test_obc.py` | OBC Equipment model, port declarations | OBC-001 |
| `pus/test_obc_dhs.py` | OBC DHS behaviour, mode FSM, watchdog | OBC-001 |
| `pus/test_obc_stub.py` | OBC Stub rule engine | SVF-DEV-040 |

---

## Level 2 — Integration Tests

**What:** Two or more SVF blocks operating together. No real flight binary
— the OBC is either a stub or a simulated model. Tests DDS synchronisation,
wiring propagation, and equipment handshake.

**Run with:** `testosvf`

**Directory:** `tests/integration/`

**Criterion:** May use compiled FMU binaries from `models/`. No real flight binary, no Renode, no QEMU.

| Test file | What it validates | Requirements |
|---|---|---|
| `test_fmu_equipment.py` | FmuEquipment port declaration, step, parameter_map, teardown; SimulationMaster with FMU | SVF-DEV-014, SVF-DEV-063/065/066, EQP-007/008/009/012 |
| `test_fixtures.py` | pytest fixture lifecycle: default FMU, custom stop time/dt, inject, ConditionNotMet | SVF-DEV-040/041/042/043 |
| `test_lockstep_loop.py` | DDS tick/ready protocol, multi-model lockstep synchronisation | SVF-DEV-009/010/011/012/014/015/016/020/021/022/023/026 |
| `test_wiring_integration.py` | WiringMap auto-propagation between Equipment instances | SVF-DEV-004 |
| `test_dynamics_bridge.py` | KDE FMU ↔ sensor models data flow (MAG/GYRO truth pass-through) | KDE-001/002/003/004 |
| `test_closed_loop_detumbling.py` | KDE FMU + magnetometer + gyroscope + magnetorquer closed-loop physics | KDE-001/002/003/004, SVF-DEV-001/004 |
| `test_yamcs_bridge.py` | YAMCS TM/TC bridge — parameter store ↔ YAMCS telemetry | SVF-DEV-037 |

---

## Level 3 — System Tests

**What:** Full spacecraft simulation with all blocks connected and a real
flight binary (`obsw_sim`, `obsw_sim_aarch64`, or ZynqMP in Renode).
These tests require external tooling (obsw_sim binary, QEMU, or Renode)
and are excluded from the default `testosvf` run via `norecursedirs`.

**Run with:** `pytest tests/system/ -v` (requires binary and/or Renode)

**Directory:** `tests/system/`

| Test file | What it validates | Requirements | Requires |
|---|---|---|---|
| `test_obc_emulator.py` | OBCEmulatorAdapter pipe mode — wire protocol, sensor injection, TM parsing | SVF-DEV-029/034/037 | `bin/obsw_sim` |
| `test_obc_emulator_adapter.py` | OBCEmulatorAdapter full tick cycle, mode transitions via S5 events | SVF-DEV-029/034/037 | `bin/obsw_sim` |
| `test_kde_obsw_closed_loop.py` | KDE FMU + obsw_sim b-dot closed loop — angular rate convergence | KDE-001/002/003/004 | `bin/obsw_sim` |
| `test_kde_obsw_adcs_closed_loop.py` | KDE FMU + obsw_sim ADCS PD controller closed loop — attitude tracking | KDE-001/002/003/004 | `bin/obsw_sim` |
| `test_aarch64_obsw.py` | obsw_sim_aarch64 under QEMU user-mode — wire protocol identical to x86_64 | SVF-DEV-100 | `bin/obsw_sim_aarch64`, `qemu-aarch64` |
| `test_realtime_detumbling.py` | Realtime tick source — wall-clock synchronisation under load | SVF-DEV-089 | `bin/obsw_sim` |
| `test_renode_zynqmp.py` | OBCEmulatorAdapter socket mode — TC(17,1) ping/pong via Renode UART | SVF-DEV-101 | `renode`, `bin/obsw_zynqmp.bin` |

**Setup for system tests:**

```bash
# Pipe mode (obsw_sim must be in bin/)
pytest tests/system/test_obc_emulator.py -v

# aarch64 QEMU
pytest tests/system/test_aarch64_obsw.py -v   # AARCH64_GLIBC must be set

# Renode ZynqMP
renode renode/zynqmp_obsw.resc &
pytest tests/system/test_renode_zynqmp.py -v
```

---

## Level 4 — Operator Campaigns

**What:** The operator uses the validated SVF to run campaigns that
validate their own OBSW. These are not SVF self-validation — they produce
V&V evidence for the OBSW under test.

**Run with:** `svf campaign <campaign.yaml> [--report]`

**Directory:** `mission_mysat1/campaigns/`

| Campaign | Procedures | Requirements | Description |
|---|---|---|---|
| `aocs_campaign.yaml` | 3 | MIS-AOCS-*, RW-*, ST-* | B-dot convergence, RW fault derate, ST sun blinding |
| `demo_campaign.yaml` | 3 | MIS-FDIR-001/002/003 | Safe mode recovery three-act scenario |
| `dhs_campaign.yaml` | 3 | MIS-FDIR-001/002, OBC-001 | OBC boot, mode transition, watchdog |
| `platform_campaign.yaml` | 2 | MIS-PLAT-* | Platform health, bus routing |

**To add your own OBSW campaign:**

1. Write `Procedure` subclasses in `your_mission/procedures/your_procedures.py`
2. Reference them in a campaign YAML
3. Run `svf campaign your_mission/campaigns/your_campaign.yaml --report`

Each procedure must reference at least one requirement ID. Campaigns that
do not trace to requirements are not validation — they are exploration.

---

## What is NOT validation

The following are engineering tools and do not appear in the validation
pyramid:

- **Monte Carlo runs** — parameter sensitivity analysis, not requirement
  verification. Use `MonteCarloRunner` directly in scripts.
- **Realtime experiments** — wall-clock timing benchmarks. Not a
  functional requirement.
- **Example campaigns** — demonstration artefacts with no requirement
  traceability.

---

## Running the full validation suite

```bash
# Level 1 + 2 (no external dependencies)
testosvf && checkcov

# Level 1 + 2 + type checking
checkosvf && testosvf && checkcov

# Level 3 (requires obsw_sim in bin/)
pytest tests/system/ -v --ignore=tests/system/test_renode_zynqmp.py \
       --ignore=tests/system/test_aarch64_obsw.py

# Level 4
svf campaign mission_mysat1/campaigns/aocs_campaign.yaml --report
svf campaign mission_mysat1/campaigns/demo_campaign.yaml --report
svf campaign mission_mysat1/campaigns/dhs_campaign.yaml --report
svf campaign mission_mysat1/campaigns/platform_campaign.yaml --report

# SRDB cross-repo consistency (requires openobsw gitingest snapshot)
checkcons --obsw lipofefeyt-openobsw-*.txt
```

---

## Traceability

After `testosvf`, `results/traceability.txt` is generated automatically
by the SVF pytest plugin. `checkcov` reads this file and cross-references
it against BASELINED requirements in `REQUIREMENTS.md`.

```bash
checkcov    # shows covered / uncovered / known gaps
```

The `KNOWN_GAPS` dict in `tools/check_coverage.py` documents requirements
that are verified by means other than `@pytest.mark.requirement` markers
(CI pipeline, hardware tests, script verification). Every entry requires
an explicit justification string.