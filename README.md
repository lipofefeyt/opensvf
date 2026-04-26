# OpenSVF

**Open-core spacecraft Software Validation Facility**

OpenSVF is a Python-based platform for validating spacecraft flight software against a 6-DOF physics engine and a real PUS ground station. It is aimed at small satellite teams who write flight software in C and need a structured, traceable way to test it before hardware integration.

The core idea: your flight software binary runs inside the SVF. The SVF feeds it sensor data from a physics simulation, receives its actuator commands, closes the loop, and records everything. You write test procedures in Python that send telecommands and assert on telemetry. At the end you get an HTML campaign report with a requirement traceability matrix.

---

## What it looks like

```
opensvf-kde (C++/Eigen3)        openobsw (C11)
  6-DOF rigid body dynamics        PUS S1/3/5/6/8/17/20
  Euler equations                  b-dot detumbling
  IGRF magnetic field model        ADCS PD controller
        │                          FDIR + watchdog
        │  FMI 3.0 Co-Simulation         │
        ▼                                ▼
              OpenSVF (Python)
         ┌────────────────────────────┐
         │  Sensor models             │  magnetometer, gyroscope,
         │  (noise, bias, FDIR faults)│  star tracker, CSS, GPS, RW
         │                            │
         │  Bus adapters              │  MIL-STD-1553B, SpaceWire,
         │                            │  CAN 2.0B (ECSS)
         │                            │
         │  PUS TM/TC stack           │  ECSS-E-ST-70-41C
         │                            │
         │  Campaign runner           │  Procedure → verdict → HTML
         └────────────────────────────┘
                    │ PUS TM/TC
                    ▼
             YAMCS 5.12.6
         (optional ground station)
```

---

## Prerequisites

- Linux (Ubuntu 22.04+) or a Firebase IDX / GitHub Codespaces workspace
- Python 3.11+
- Eclipse Cyclone DDS (`pip install cyclonedds`)
- Java 11+ (for YAMCS, optional)

The setup script handles the rest.

---

## Quick start

```bash
git clone https://github.com/lipofefeyt/opensvf
cd opensvf
source scripts/setup-workspace.sh   # installs venv, YAMCS, activates aliases

testosvf                            # ~377 unit + integration tests
checkcov                            # requirement coverage report
svf profiles                        # list bundled hardware profiles
svf check mission_mysat1/spacecraft.yaml
svf campaign mission_mysat1/campaigns/aocs_campaign.yaml --report
```

The campaign produces `results/report.html` — open it in a browser.

---

## Three modes of operation

### 1. Stub mode (unit testing, no binary)

```yaml
# spacecraft.yaml
obsw:
  type: stub
```

The OBC is replaced by a rule-based stub. All sensors and actuators run. Use this for rapid iteration on test procedures before you have a flight binary.

### 2. Pipe mode (host simulation, CI)

```yaml
obsw:
  type: pipe
  binary: ./bin/obsw_sim        # x86_64 or aarch64 via QEMU
```

The real flight software binary runs as a subprocess. SVF feeds it sensor frames over stdin/stdout using wire protocol v3. This is the primary SIL validation mode and runs in CI with no special hardware.

### 3. Socket mode (Renode ZynqMP emulation)

```yaml
obsw:
  type: socket
  host: localhost
  port: 3456
```

The flight software runs inside Renode emulating a ZynqMP Cortex-A53. SVF connects to the Renode UART terminal over TCP. Same wire protocol — the flight binary never knows the difference.

---

## Writing a test procedure

```python
from svf.campaign.procedure import Procedure, ProcedureContext

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

```yaml
# campaign.yaml
campaign: MySat-1 AOCS Validation
spacecraft: mission_mysat1/spacecraft.yaml
procedures:
  - procedures/test_bdot.py
```

```bash
svf campaign campaign.yaml --report
```

---

## Fault injection

```python
# Star tracker stuck fault for 10 seconds
ctx.inject_equipment_fault(
    "str1", "aocs.str1.quaternion_w",
    fault_type="stuck", value=0.0, duration_s=10.0
)

# Magnetometer bias
ctx.inject_equipment_fault(
    "mag1", "aocs.mag.field_x",
    fault_type="bias", value=1e-5, duration_s=30.0
)
```

Fault types: `stuck` | `noise` | `bias` | `scale` | `fail`

---

## Temporal assertions

```python
# "Angular rate shall never exceed 0.1 rad/s during detumbling"
monitor = ctx.monitor("aocs.truth.rate_magnitude", less_than=0.1)
ctx.wait(60.0)
monitor.assert_no_violations()

result = monitor.summary()
# result.compliant, result.violations, result.min_value, result.max_value
```

---

## Hardware profiles

Ten bundled profiles cover common small satellite components:

| Profile | Component |
|---|---|
| `mag_default` | Generic 3-axis magnetometer |
| `gyro_default` | Generic MEMS gyroscope |
| `rw_default` | Generic reaction wheel |
| `rw_sinclair_rw003` | Sinclair RW-003 |
| `mtq_default` | Generic magnetorquer |
| `gps_default` | Generic GPS receiver |
| `gps_novatel_oem7` | NovAtel OEM7 |
| `thr_default` | Generic thruster |
| `thr_moog_monarc_1` | Moog Monarc-1 |
| `thermal_default` | Generic thermal model |

```bash
svf profiles          # list all available
```

---

## Bus adapters

| Bus | Fault injection |
|---|---|
| MIL-STD-1553B | `BUS_ERROR`, `NO_RESPONSE`, `LATE_RESPONSE`, `BAD_PARITY` |
| SpaceWire + RMAP | link error, invalid address, RMAP error codes |
| CAN 2.0B (ECSS) | bus-off, node error, bad parity |

---

## Developer tools

```bash
testosvf        # full test suite (~377 tests)
checkosvf       # mypy strict type check
checkcov        # requirement coverage (REQUIREMENTS.md → traceability.txt)
checkcons       # SRDB cross-repo consistency (wire protocol, orphan requirements)
checkcons-full lipofefeyt-openobsw-*.txt   # + C struct field cross-check
regen-xtce      # regenerate YAMCS XTCE database
```

---

## Repository layout

```
src/svf/
├── campaign/       CampaignRunner, Procedure, HTML reporter
├── models/
│   ├── aocs/       magnetometer, gyroscope, star_tracker, magnetorquer,
│   │               reaction_wheel, css, bdot_controller, thruster, gps
│   ├── dynamics/   KDE FMU wrapper (6-DOF physics)
│   ├── eps/        PCDU, battery, solar array FMUs
│   ├── dhs/        OBCStub, OBCEmulatorAdapter (pipe + socket)
│   └── ttc/        TTC, S-band transponder
├── bus/            MIL-STD-1553B, SpaceWire, CAN
├── pus/            PUS-C TM/TC packet builder/parser
├── stores/         ParameterStore, CommandStore
└── config/         SpacecraftLoader, HardwareProfile, SRDB

mission_mysat1/     Reference mission configuration
tools/              check_coverage.py, srdb_consistency_check.py, generate_xtce.py
```

---

## Related projects

| Project | What it is |
|---|---|
| [openobsw](https://github.com/lipofefeyt/openobsw) | C11 flight software: PUS stack, b-dot, ADCS PD, FDIR, ZynqMP + MSP430 targets |
| [opensvf-kde](https://github.com/lipofefeyt/opensvf-kde) | C++ 6-DOF kinematics and dynamics engine (FMI 3.0 FMU) |

---

## Roadmap

| Milestone | Status |
|---|---|
| M1–M18 — Core platform, FMI 3.0, DDS sync, PUS stack, equipment models | ✅ Done |
| M19 — Spacecraft configuration DSL (YAML zero-Python entry point) | ✅ Done |
| M20 — Structured test procedure API | ✅ Done |
| M21 — Mission-level HTML reporting | ✅ Done |
| M22 — OBSW integration guide | ✅ Done |
| M23 — Temporal assertions + equipment fault engine | ✅ Done |
| M24 — ZynqMP SIL (aarch64 QEMU + Renode socket transport) | ✅ Done |
| M25 — YAMCS ground segment integration | 🔄 In progress |

---

## License

Apache 2.0

*Built by [lipofefeyt](https://github.com/lipofefeyt)*
