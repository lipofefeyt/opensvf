# OpenSVF

**Open-core spacecraft Software Validation Facility**

OpenSVF validates your flight software against a 6-DOF physics engine and a real ground station. Configure your spacecraft in YAML, write test procedures in Python, run a campaign, get an HTML report.

---

## Design Philosophy

OpenSVF is a **flight software validation platform** — not an AOCS design tool and not a Simulink replacement.

- `opensvf-kde` is the **spacecraft plant** (physics). No control algorithm.
- `openobsw` contains the **flight algorithms** (b-dot, ADCS PD, FDIR). Under test.
- Python reference controllers are **validation oracles** — not flight code.
- Monte Carlo runs against fixed C code — tests the actual flight software.

See [`docs/design-philosophy.md`](docs/design-philosophy.md).

---

## Quick Start

```bash
git clone https://github.com/lipofefeyt/opensvf
cd opensvf
source scripts/setup-workspace.sh

testosvf           # ~460 tests
svf profiles       # list available hardware profiles
svf check examples/spacecraft.yaml
svf campaign campaigns/example_campaign.yaml --report
```

---

## CLI

```bash
svf run spacecraft.yaml              # run simulation
svf campaign campaign.yaml           # run test campaign
svf campaign campaign.yaml --report  # run + HTML report
svf profiles                         # list hardware profiles
svf check spacecraft.yaml            # validate config
```

---

## Zero-Python Entry Point

```yaml
# spacecraft.yaml
version: 1
spacecraft: MySat-1

obsw:
  type: pipe        # pipe | socket | stub
  binary: ./obsw_sim

equipment:
  - id: mag1
    model: magnetometer
    hardware_profile: mag_default
  - id: gyro1
    model: gyroscope
    hardware_profile: gyro_default
  - id: mtq1
    model: magnetorquer
  - id: rw1
    model: reaction_wheel
    hardware_profile: rw_sinclair_rw003

wiring:
  auto: true

simulation:
  dt: 0.1
  stop_time: 3600.0
  seed: 42
  realtime: true
```

```yaml
# campaign.yaml
campaign: MySat-1 AOCS Validation
spacecraft: spacecraft.yaml
procedures:
  - procedures/test_aocs.py
```

```bash
svf campaign campaign.yaml --report
```

---

## Test Procedures

```python
from svf.procedure import Procedure, ProcedureContext

class BdotConvergence(Procedure):
    id          = "TC-AOCS-001"
    title       = "B-dot detumbling convergence"
    requirement = "MIS-AOCS-042"

    def run(self, ctx: ProcedureContext) -> None:
        self.step("Power on sensors")
        ctx.inject("aocs.mag.power_enable", 1.0)
        ctx.inject("aocs.gyro.power_enable", 1.0)

        self.step("Monitor angular rate for 60s")
        monitor = ctx.monitor("aocs.gyro.rate_x", less_than=0.5)
        ctx.wait(60.0)
        monitor.assert_no_violations()

        self.step("Verify convergence")
        ctx.assert_parameter("aocs.gyro.status", greater_than=0.5)
```

---

## Equipment Fault Injection

```python
# Inject star tracker stuck fault
ctx.inject_equipment_fault(
    "str1", "aocs.str1.quaternion_w",
    fault_type="stuck", value=0.0, duration_s=10.0
)

# Inject magnetometer bias
ctx.inject_equipment_fault(
    "mag1", "aocs.mag.field_x",
    fault_type="bias", value=1e-5, duration_s=30.0
)

# Clear all faults
ctx.clear_equipment_faults("str1")
```

Fault types: `stuck` | `noise` | `bias` | `scale` | `fail`

---

## Temporal Assertions (MTL-style)

```python
# "Rate shall NEVER exceed 0.1 rad/s for 60 seconds"
monitor = ctx.monitor("aocs.truth.rate_magnitude", less_than=0.1)
ctx.wait(60.0)
monitor.assert_no_violations()

# Full summary
result = monitor.summary()
# result.compliant, result.violations, result.max_value
```

---

## The Closed Loop

```
opensvf-kde (C++ / Eigen3)          Your OBSW (C11)
  6-DOF physics engine                 b-dot, ADCS PD, FDIR
  Euler equations, B-field             PUS S1/3/5/8/17/20
         │  true state via FMI 2.0           │ wire protocol v3
         ▼                                    ▼
              opensvf (Python)
              Sensor + actuator models
              Bus adapters (1553/SpW/CAN)
                    │ PUS TM/TC
                    ▼
               YAMCS 5.12.6
```

---

## OBSW Transport Modes

| Mode | Config | Use Case |
|---|---|---|
| `pipe` | `binary: ./obsw_sim` | CI, development |
| `socket` | `host/port` | Renode ZynqMP SIL |
| `stub` | (no binary) | Unit testing |

---

## Hardware Profiles

```yaml
equipment:
  - id: rw1
    model: reaction_wheel
    hardware_profile: rw_sinclair_rw003
```

10 bundled profiles in `srdb/hardware/`. No extra packages needed.

```bash
svf profiles   # list all available
```

---

## Bus Adapters

| Bus | Type | Fault Injection |
|---|---|---|
| MIL-STD-1553B | `mil1553` | BUS_ERROR, NO_RESPONSE, BAD_PARITY |
| SpaceWire + RMAP | `spacewire` | Link error, invalid address |
| CAN 2.0B (ECSS) | `can` | Bus-off, node error, bad parity |

---

## Model Organisation

```
src/svf/models/
├── aocs/       reaction_wheel, magnetometer, magnetorquer, gyroscope,
│               star_tracker, css, bdot_controller, thruster, gps
├── dynamics/   kde_equipment + fmu/DynamicsFmu
├── eps/        pcdu + fmu/{EpsFmu,BatteryFmu,SolarArrayFmu,PcduFmu}
├── dhs/        obc, obc_stub, obc_emulator
├── ttc/        ttc, sbt
└── thermal/    thermal

models/fmu/     FMU binaries (data — see scripts/download_fmu.sh)
srdb/hardware/  Bundled hardware profiles
```

---

## Related Projects

| Project | Role |
|---|---|
| [opensvf-kde](https://github.com/lipofefeyt/opensvf-kde) | C++ 6-DOF physics (FMI 2.0) |
| [openobsw](https://github.com/lipofefeyt/openobsw) | C11 OBSW: PUS, b-dot, ADCS, FDIR |

---

## Roadmap

| Milestone | Status |
|---|---|
| M1–M18 — Core platform through architecture refactor | ✅ Done |
| M19 — Spacecraft Configuration DSL | ✅ Done |
| M20 — Structured Test Procedure API | ✅ Done |
| M21 — Mission-Level Results Reporting | ✅ Done |
| M22 — OBSW Integration Guide | ✅ Done |
| M23 — Temporal Assertions + Equipment Fault Engine | ✅ Done |

---

## License

Apache 2.0

*Built by lipofefeyt · [opensvf-kde](https://github.com/lipofefeyt/opensvf-kde) · [openobsw](https://github.com/lipofefeyt/openobsw)*