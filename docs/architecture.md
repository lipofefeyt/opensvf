# SVF Architecture

> **Status:** v2.2
> **Last updated:** 2026-04
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
├── dynamics/   kde_equipment
│   └── fmu/    DynamicsFmu.py (Python wrapper)
├── eps/        pcdu
│   └── fmu/    EpsFmu.py, BatteryFmu.py, SolarArrayFmu.py, PcduFmu.py
├── dhs/        obc, obc_stub, obc_emulator
├── ttc/        ttc, sbt
└── thermal/    thermal

models/fmu/     FMU binaries (data, not code)
├── SpacecraftDynamics.fmu
├── EpsFmu.fmu
├── BatteryFmu.fmu
├── SolarArrayFmu.fmu
└── PcduFmu.fmu
```

The `.fmu` files are binary data committed at `models/fmu/`. The Python wrappers in `src/svf/models/*/fmu/` load them at runtime. This separation keeps code and data in different locations. Use `scripts/download_fmu.sh` to download updated FMU binaries from opensvf-kde releases.

---

## 7. Hardware Profile System

Hardware profiles are YAML files that override equipment physics constants. They live in `srdb/hardware/` inside opensvf and are bundled — no extra packages needed.

```
srdb/hardware/                        bundled profiles (opensvf)
├── mag_default.yaml          Generic MAG (1e-7 T noise)
├── gyro_default.yaml         Generic GYRO (ARW 1e-4 rad/s/sqrthz)
├── mtq_default.yaml          Generic MTQ (10 Am^2)
├── rw_default.yaml           Generic RW (6000 rpm, 0.2 Nm)
├── rw_sinclair_rw003.yaml    Sinclair RW-0.03 (5000 rpm, 30 mNm)
├── thr_default.yaml          Cold gas (1 N, Isp=70s)
├── thr_moog_monarc_1.yaml    Hydrazine (1 N, Isp=220s)
├── gps_default.yaml          Generic GPS (5 m noise)
├── gps_novatel_oem7.yaml     NovAtel OEM7 (1.5 m noise)
└── thermal_default.yaml      3-node (panels + internal)
```

Profile search order in `svf.hardware_profile.load_hardware_profile()`:

1. Explicit `hardware_dir` argument (if provided)
2. `srdb/hardware/` in opensvf (bundled, always available)
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

## 12. Milestones

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