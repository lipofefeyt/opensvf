# SVF Architecture

> **Status:** v2.3
> **Last updated:** 2026-05
> **Author:** lipofefeyt

---

## 1. Overview

The Software Validation Facility (SVF) is an open-core platform for the validation of spacecraft software and systems. It connects four independent components into a single closed-loop simulation:

- **opensvf** — Python orchestration layer (this repo)
- **opensvf-kde** — C++ 6-DOF physics engine, compiled to FMI 2.0 FMU
- **openobsw** — C11 OBSW: PUS services, b-dot, ADCS PD, FDIR
- **YAMCS 5.12.6** — Ground station: TC uplink, TM display, XTCE MDB

---

## 2. Entry Points

### Zero-Python (M19)

```bash
python3 -c "
from svf.spacecraft import SpacecraftLoader
SpacecraftLoader.load('spacecraft.yaml').run()
"
```

### Python API

```python
from svf.spacecraft import SpacecraftLoader
master = SpacecraftLoader.load("spacecraft.yaml")
master.run()
```

### Campaign runner

```python
from svf.campaign_runner import CampaignRunner
from svf.report import generate_html_report
from pathlib import Path

runner = CampaignRunner.from_yaml("campaign.yaml")
report = runner.run()
generate_html_report(report, Path("results/report.html"))
```

### Low-level (full control)

```python
participant = DomainParticipant()
sync      = DdsSyncProtocol(participant)
store     = ParameterStore()
cmd_store = CommandStore()
# instantiate equipment manually
master = SimulationMaster(...)
master.run()
```

---

## 3. Spacecraft Configuration (M19)

```yaml
spacecraft: MySat-1

obsw:
  type: pipe | socket | stub
  binary: ./obsw_sim        # pipe mode
  host: localhost            # socket mode
  port: 3456                 # socket mode

equipment:
  - id: mag1
    model: magnetometer
    hardware_profile: mag_default
    seed: 42

buses:
  - id: aocs_bus
    type: mil1553 | spacewire | can
    # ... bus-specific config

wiring:
  auto: true
  overrides:
    - from: mag1.aocs.mag.field_x
      to:   obc.aocs.mag1.field_x

simulation:
  dt: 0.1
  stop_time: 300.0
  seed: 42
  realtime: false
```

**Auto-wiring:** SVF connects OUT to IN port pairs automatically when they share the same canonical name. Explicit overrides handle non-standard connections.

---

## 4. Full System Architecture

```
┌──────────────────────────────────────────────────────────┐
│  YAMCS 5.12.6  http://localhost:8090                     │
│  XTCE MDB: parameters, containers, commands              │
└──────────────────────┬───────────────────────────────────┘
                       │ PUS TM/TC via TCP
┌──────────────────────▼───────────────────────────────────┐
│  YamcsBridge + TtcEquipment                              │
└──────────────────────┬───────────────────────────────────┘
                       │ PUS bytes
┌──────────────────────▼───────────────────────────────────┐
│  OBCEmulatorAdapter                                      │
│  PIPE:   obsw_sim (x86_64) or obsw_sim_aarch64 (QEMU)   │
│  SOCKET: Renode ZynqMP uart0 TCP:3456                    │
│  STUB:   ObcStub rule engine                             │
└──────────────────────┬───────────────────────────────────┘
                       │ wire protocol v3
┌──────────────────────▼───────────────────────────────────┐
│  openobsw C11 OBSW                                       │
│  b-dot → MTQ dipoles | ADCS PD → RW torques             │
│  PUS S1/3/5/8/17/20  FDIR FSM                           │
└──────────────────────┬───────────────────────────────────┘
                       │ actuator frame → CommandStore
┌──────────────────────▼───────────────────────────────────┐
│  Bus Adapters (optional)                                 │
│  MIL-STD-1553B | SpaceWire+RMAP | CAN 2.0B (ECSS)      │
│  Fault injection: BUS_ERROR, NO_RESPONSE, BAD_PARITY    │
└──────────────────────┬───────────────────────────────────┘
                       │ torques → KDE
┌──────────────────────▼───────────────────────────────────┐
│  opensvf-kde FMU (C++ / Eigen3)                         │
│  6-DOF physics, Euler equations, B-field model          │
│  OUT: true omega, true B, true q                        │
└──────────────────────┬───────────────────────────────────┘
                       │ true state → sensor models
┌──────────────────────▼───────────────────────────────────┐
│  Sensor Models: MAG GYRO ST CSS GPS                     │
│  Noisy measurements → type-0x02 frames → OBSW           │
└──────────────────────┬───────────────────────────────────┘
┌──────────────────────▼───────────────────────────────────┐
│  Thermal Model: N-node radiation/conduction network      │
└──────────────────────────────────────────────────────────┘
```

---

## 5. Wire Protocol v3

```
SVF → OBSW (stdin or TCP):
  [0x01][uint16 BE len][TC frame]          TC uplink
  [0x02][uint16 BE len][sensor_frame_t]    Sensor injection

OBSW → SVF (stdout or TCP):
  [0x04][uint16 BE len][TM packet]         PUS TM
  [0x03][uint16 BE len][actuator_frame_t]  Actuator commands
  [0xFF]                                   End of tick
```

The C reference implementation lives in `contrib/svf_protocol/` in the openobsw repository.

---

## 6. Model Organisation

```
src/svf/models/
├── aocs/       reaction_wheel, magnetometer, magnetorquer, gyroscope,
│               star_tracker, css, bdot_controller, thruster, gps
├── dynamics/   kde_equipment (FmuEquipment adapter for SpacecraftDynamics.fmu)
├── eps/        solar_array, battery, pcdu  (all NativeEquipment factories)
├── dhs/        obc, obc_stub, obc_emulator
├── ttc/        ttc, sbt
└── thermal/    thermal

models/         FMU binaries (data, not code — external models only)
├── SpacecraftDynamics.fmu   (from opensvf-kde C++ project)
└── SimpleCounter.fmu        (test double for FmuEquipment infrastructure tests)
```

All SVF reference models are implemented as `NativeEquipment` factories — pure Python closures with no compiled binaries. `FmuEquipment` is an adapter reserved for operator-supplied external physics (Modelica, Simulink, C++) and the `SpacecraftDynamics.fmu` from `opensvf-kde`. Use `scripts/download_fmu.sh` to download updated FMU binaries from opensvf-kde releases.

---

## 7. Hardware Profile System

Hardware profiles are YAML files that override equipment physics constants. Bundled profiles live in `mission_mysat1/hardware_profiles/` — no extra packages needed.

```
mission_mysat1/hardware_profiles/     bundled profiles
├── mag_default.yaml          Generic MAG (1e-7 T noise)
├── gyro_default.yaml         Generic GYRO (ARW 1e-4 rad/s/sqrthz)
├── mtq_default.yaml          Generic MTQ (10 Am^2)
├── rw_default.yaml           Generic RW (6000 rpm, 0.2 Nm)
├── rw_sinclair_rw003.yaml    Sinclair RW-0.03 (5000 rpm, 30 mNm)
├── str_default.yaml          Generic ST (30° sun exclusion, 10s acq)
├── thr_default.yaml          Cold gas (1 N, Isp=70s)
├── thr_moog_monarc_1.yaml    Hydrazine (1 N, Isp=220s)
├── gps_default.yaml          Generic GPS (5 m noise)
├── gps_novatel_oem7.yaml     NovAtel OEM7 (1.5 m noise)
└── thermal_default.yaml      3-node (panels + internal)
```

Profile search order in `svf.config.hardware_profile.load_hardware_profile()`:

1. Explicit `hardware_dir` argument (if provided)
2. Bundled `mission_mysat1/hardware_profiles/` in opensvf (always available)
3. `obsw-srdb` Python package (if installed)

**Note:** `srdb/data/hardware/` in the openobsw repository contains the same profile data used to generate the OBSW SRDB C header — this is a separate concern from SVF.

---

## 8. Test Procedure API (M20)

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

Verdicts: PASS / FAIL / INCONCLUSIVE / ERROR. Steps captured with names. Results traced to requirements in HTML report.

---

## 9. Campaign and Reporting (M20/M21)

```yaml
# campaign.yaml
campaign: MySat-1 AOCS Validation
spacecraft: spacecraft.yaml
procedures:
  - tests/procedures/test_aocs.py
  - tests/procedures/test_fdir.py
```

```python
from svf.campaign_runner import CampaignRunner
from svf.report import generate_html_report
from pathlib import Path

runner = CampaignRunner.from_yaml("campaign.yaml")
report = runner.run()
generate_html_report(report, Path("results/report.html"))
```

The HTML report is fully self-contained (no CDN), includes summary cards, per-procedure verdicts, and a requirement coverage table.

---

## 10. Tick Sources

| Tick Source | Behaviour | Use Case |
|---|---|---|
| `SoftwareTickSource` | Fast as possible | CI, Monte Carlo |
| `RealtimeTickSource` | Wall-clock aligned | YAMCS demos, HIL |

Variable timestep: `Equipment.suggested_dt()` returns an optional smaller step size. `SimulationMaster._effective_dt()` uses the minimum across all models.

---

## 11. Deterministic Replay

```python
master = SimulationMaster(..., seed=42)
master.run()
# Seed manifest saved to results/seed.json
```

Per-model seeds derived deterministically from master seed via SHA-256.

---

## 12. Equipment Tick Error Handling (M35)

When an equipment model raises during a simulation tick, `SimulationMaster`
wraps the exception in an `EquipmentTickError` and dispatches it to the
configured handler.

```python
from svf.sim.simulation import EquipmentTickError, SimulationMaster

# Default behaviour: re-raise as SimulationError (abort the run)
master = SimulationMaster(..., models=[...])

# Record-and-continue: collect errors, let other models keep ticking
errors: list[EquipmentTickError] = []
master = SimulationMaster(..., on_tick_error=errors.append)
master.run()
for e in errors:
    print(e.equipment_id, e.obt, e.cause)

# Strict custom handler: abort with a domain-specific message
def strict(err: EquipmentTickError) -> None:
    if err.equipment_id == "mag":
        raise SimulationError(f"Critical sensor failure: {err}")
    # otherwise swallow and continue
master = SimulationMaster(..., on_tick_error=strict)
```

`EquipmentTickError` fields:

| Field | Type | Description |
|---|---|---|
| `equipment_id` | `str` | The failing model's ID |
| `obt` | `float` | On-board time when the fault occurred (seconds) |
| `cause` | `Exception` | The original exception raised by the model |
| `context` | `dict` | Structured dict with `equipment_id`, `obt`, `cause_type`, `cause_message` |

## 13. Checks

### Pre-flight validation

```bash
svf validate spacecraft.yaml   # fast config check — no DDS, no FMU, no model imports
```

`SpacecraftValidator` (`src/svf/config/validator.py`) runs before any simulation
infrastructure is instantiated and catches:

- Duplicate equipment IDs
- Bus address conflicts (CAN node-id, SpaceWire logical address, 1553 RT address)
- Wiring overrides referencing non-existent equipment IDs or ports
- OBT parameter file missing on disk or containing malformed YAML

Exits 0 if clean; lists all issues (not just the first) on failure.

### Coverage check

```bash
checkcov   # BASELINED requirement coverage + equipment fidelity report (F1–F4)
```

`checkcov` (`tools/check_coverage.py`) cross-references `REQUIREMENTS.md`
against `results/traceability.txt` and also prints a per-model fidelity table:

```
  Equipment fidelity coverage
  ─────────────────────────────────────────────────────────────────────────
  Model                Level  TM params  Calibrated  Note
  Magnetometer         F2             3           0  → F3: Add polynomial calibration ...
  Gyroscope            F2             4           0  → F3: Add Allan-variance noise model ...
  KDE Dynamics (FMI)   F3             0           0  Add flex modes from modal test data for F4
  ...
```

An inconsistency error (F2 model with CalibrationCurve entries) causes exit 1.

### Cross-repository consistency check

```bash
# Python-side checks only (struct sizes, port mapping, orphan requirements):
checkcons

# Full check including C struct field names (pass openobsw gitingest snapshot):
checkcons-full lipofefeyt-openobsw-*.txt
```

`checkcons` (`tools/srdb_consistency_check.py`) runs 7 checks:

| Check | What it catches |
|---|---|
| [1/7] Struct sizes | `_SENSOR_FMT` / `_ACTUATOR_FMT` drift from C struct layout |
| [2/7] Python-side mapping | `obc_emulator.py` store keys diverging from mapping table |
| [3/7] C struct fields | Field renames in openobsw not propagated to SVF packer |
| [4/7] Producer/consumer | Sensor model port renames that produce silent zeros in the OBSW |
| [5/7] Requirement orphans | `@pytest.mark.requirement` IDs absent from `REQUIREMENTS.md` |
| [6/7] Profile symmetry | Mission hardware profiles missing from bundled directory |
| [7/7] SRDB namespace | OUT ports declared by equipment models but absent from SRDB baseline |

The C struct check accepts either a real openobsw checkout (directory) or a
gitingest snapshot (`.txt` file), which is the correct approach in
single-workspace environments (Firebase IDX, GitHub Codespaces) where both
repos cannot coexist on the same filesystem.

## 13. Milestones

| Milestone | Status |
|---|---|
| M1-M12 — Core platform through ground segment | Done |
| M13 — SIL Attitude Loop Closure | Done |
| M14 — Real-Time and HIL + Renode socket + variable timestep | Done |
| M15 — Extended Bus Protocols (SpaceWire, CAN) | Done |
| M16 — SRDB Maturity | Done |
| M17 — Equipment Configurability | Done |
| M18 — Architecture Refactor | Done |
| M19 — Spacecraft Configuration DSL | Done |
| M20 — Structured Test Procedure API | Done |
| M21 — Mission-Level Results Reporting | Done |
| M22 — OBSW Integration Guide | Done |
| M23 — Temporal assertions + equipment fault engine | Done |
| M24 — ZynqMP SIL (aarch64 QEMU + Renode socket transport) | Done |
| M25 — YAMCS ground segment integration (TM/TC pipeline, XTCE MDB) | Done |
| M26 — EPS/AOCS/thermal native models + full test pyramid restructure | Done |
| M29 — Time-tagged parameter init file (OBT-format startup state) | Done |
| M30 — CAN 2.0B full validation + SpaceWire RMAP completion | Done |
| M31 — Equipment fidelity levels + SRDB calibration curves | Done |
| M32 — SpacecraftValidator: pre-flight config check (`svf validate`) | Done |
| M33 — SRDB namespace linting (checkcons check [7/7]) | Done |
| M34 — Equipment fidelity coverage in checkcov | Done |
| M35 — EquipmentTickError + on_tick_error callback | Done |
| M36 — Campaign L4 scaffolding: INCONCLUSIVE verdict + declared requirements | Done |
| M37 — S9 Time Management: OBT sync via TC | Done |
| M38 — S11 Time-Based Scheduling: time-tagged command sequences | Done |
| M39 — S12 On-Board Monitoring: parameter OOL events | Done |
| M40 — S19 Event-Action Service: FDIR reaction chains | Done |
| M41 — SharedMemorySyncProtocol: sub-ms tick sync | Done |
| M27 — Dual-OBC topology (DualObcAdapter: primary/secondary + auto-failover) | Done |
| M28 — UART/serial wire protocol transport (MSP430, STM32H750 HIL) | Planned |
| M42 — Orbital environment (SGP4 + eclipse + solar) | Backlog |
| M43 — F3 sensor fidelity | Backlog |
| M44 — SRDB control layer (AOCS gains, FDIR thresholds) | Backlog |
| M45 — FDIR supervisor model | Backlog |
| M46 — Live YAMCS dashboards | Backlog |
| M47 — Multi-spacecraft / constellation | Backlog |