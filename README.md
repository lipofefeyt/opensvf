# OpenSVF

**Open-core spacecraft Software Validation Facility**

OpenSVF is a Python-based platform for validating spacecraft flight software against a 6-DOF physics engine and a real PUS ground station. It is aimed at small satellite teams who write flight software in C and need a structured, traceable way to test it before hardware integration.

The core idea: your flight software binary runs inside the SVF. The SVF feeds it sensor data from a physics simulation, receives its actuator commands, closes the loop, and records everything. You write test procedures in Python that send telecommands and assert on telemetry. At the end you get an HTML campaign report with a requirement traceability matrix.

---

## What it looks like

```
opensvf-kde (C++/Eigen3)        openobsw (C11)
  6-DOF rigid body dynamics        PUS S1/3/5/6/8/9/11/12/17/19/20
  Euler equations                  b-dot detumbling
  Magnetic field model             ADCS PD controller
        │                          FDIR + watchdog
        │  FMI 2.0 Co-Simulation         │
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
          (ground station)
```

---

## Compatibility

| Package | Version | Notes |
|---|---|---|
| opensvf | v1.1.0 | Python 3.12 |
| openobsw | v0.11+ | C11 |
| opensvf-kde | v0.1.0+ (SGP4 + RK4 build, Aug 2026) | C++ / Eigen3 |
| YAMCS | 5.12.6 | Java 21+ |

---

## Prerequisites

- Linux (Ubuntu 22.04+), WSL2 (Ubuntu 24.04), or GitHub Codespaces
- Python 3.11+
- Eclipse Cyclone DDS (`pip install cyclonedds`)
- Java 21+ (for YAMCS ground station)
- Docker Desktop + VS Code Dev Containers extension (for local development)

The setup script handles the rest.

---

## Quick start

```bash
git clone https://github.com/lipofefeyt/opensvf
cd opensvf
pip install -e ".[dev]"                                           # install SVF and dev dependencies

testosvf                                                          # 800+ unit + integration tests
checkcov                                                          # requirement coverage report
svf profiles                                                      # list bundled hardware profiles
svf check mission_mysat1/spacecraft.yaml
svf campaign mission_mysat1/campaigns/quickstart_campaign.yaml --report
```

The campaign produces `results/report.html`  -  open it in a browser.

To start the YAMCS ground station:

```bash
bash scripts/start-yamcs.sh     # downloads YAMCS 5.12.6 if not present, starts on port 8090
```

---

## Validation pyramid

OpenSVF is structured around a four-level validation pyramid:

| Level | Name | Requires | What it covers |
|---|---|---|---|
| L1 | Unit | No FMU binaries | Equipment physics, bus logic, stores, PUS packets |
| L2 | Integration | SimpleCounter.fmu | Closed-loop wiring, FmuEquipment adapter, simulation master |
| L3 | System | SpacecraftDynamics.fmu + OBSW binary | Full SIL: flight software in the loop, dynamics, PUS over YAMCS |
| L4 | Campaign | Mission spacecraft.yaml | Operator-level test procedures with HTML verdict reports |

CI runs L1 + L2 (no compiled flight software needed). L3 and L4 require the `openobsw` binary and `opensvf-kde` FMU.

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

The flight software runs inside Renode emulating a ZynqMP Cortex-A53. SVF connects to the Renode UART terminal over TCP. Same wire protocol  -  the flight binary never knows the difference.

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
| `str_default` | Generic star tracker |
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

## YAMCS ground station

OpenSVF integrates with [YAMCS 5.12.6](https://yamcs.org) as an optional ground station. The XTCE mission database is generated automatically from the SRDB.

```bash
bash scripts/start-yamcs.sh     # start YAMCS on port 8090
python3 scripts/demo_yamcs.py   # run a demo TC/TM exchange
bash scripts/stop-yamcs.sh      # stop YAMCS
```

The YAMCS UI is available at `http://localhost:8090` (default credentials: `admin` / `password`).

TC pipeline: YAMCS UI → UDP port 10025 → SVF → obsw_sim
TM pipeline: obsw_sim → SVF → TCP port 10015 → YAMCS packet viewer

---

## Developer tools

```bash
testosvf                              # full test suite (800+ tests, L1+L2)
checkosvf                             # mypy strict type check
svf validate spacecraft.yaml          # fast pre-flight config check (no DDS, no FMU)
checkcov                              # requirement coverage + equipment fidelity report
checkcons                             # SRDB consistency: 7 checks including namespace lint
regen-xtce                            # regenerate YAMCS XTCE database from SRDB
checksmp                              # SMP-aligned catalogue vs SRDB consistency
```

---

## Local development (WSL2 + Dev Containers)

```bash
# Windows (PowerShell admin)
wsl --install -d Ubuntu-24.04
winget install -e --id Docker.DockerDesktop --source winget
winget install -e --id dorssel.usbipd-win --source winget

# WSL2
git clone https://github.com/lipofefeyt/opensvf ~/workspace/opensvf
git clone https://github.com/lipofefeyt/openobsw ~/workspace/openobsw
git clone https://github.com/lipofefeyt/opensvf-kde ~/workspace/opensvf-kde
code ~/workspace/opensvf   # VS Code detects .devcontainer/ → Reopen in Container
```

The dev container mounts `openobsw` and `opensvf-kde` as sibling workspaces at `/workspace/`.

---

## Repository layout

```
src/svf/
├── campaign/       CampaignRunner, Procedure, HTML reporter
├── models/
│   ├── aocs/       magnetometer, gyroscope, star_tracker, magnetorquer,
│   │               reaction_wheel, css, bdot_controller, thruster, gps
│   ├── dynamics/   KDE FMU wrapper (6-DOF physics, external C++ project)
│   ├── eps/        solar_array, battery, pcdu  (NativeEquipment factories)
│   ├── dhs/        OBCStub, OBCEmulatorAdapter (pipe + socket)
│   └── ttc/        TTC, S-band transponder
├── bus/            MIL-STD-1553B, SpaceWire, CAN
├── pus/            PUS-C TM/TC stack: tc, tm, services/ (S1/3/5/6/8/9/11/12/15/17/19/20/23)
├── stores/         ParameterStore, CommandStore
└── config/         SpacecraftLoader, HardwareProfile, SRDB

mission_mysat1/     Reference mission configuration
tools/              check_coverage.py, srdb_consistency_check.py, generate_xtce.py
yamcs/              YAMCS config, XTCE MDB, processor config
scripts/            start-yamcs.sh, stop-yamcs.sh, activate.sh
```

---

## Related projects

| Project | What it is |
|---|---|
| [openobsw](https://github.com/lipofefeyt/openobsw) | C11 flight software: PUS stack, b-dot, ADCS PD, FDIR. Runs on MSP430, STM32H750, ZynqMP, x86_64 |
| [opensvf-kde](https://github.com/lipofefeyt/opensvf-kde) | C++ 6-DOF kinematics and dynamics engine (FMI 2.0 FMU) |

---

## Roadmap

### Done

| Milestone | Scope |
|---|---|
| M1-M18 | Core platform, FMI, DDS sync, PUS stack, equipment models |
| M19-M22 | Spacecraft YAML DSL, procedure API, HTML reporting, OBSW integration guide |
| M23 | Temporal assertions + equipment fault engine |
| M24-M25 | ZynqMP SIL (aarch64 QEMU + Renode socket); YAMCS TM/TC pipeline and XTCE MDB |
| M26 | EPS/AOCS/thermal native models + test pyramid restructure |
| M27-M28 | Dual-OBC topology (ZynqMP + MSP430 lockstep); UART wire protocol transport |
| M29-M31 | OBT-format init file; CAN 2.0B + SpaceWire RMAP; fidelity levels + calibration curves |
| M32-M36 | `svf validate`, SRDB namespace lint, fidelity coverage, EquipmentTickError, INCONCLUSIVE verdict |
| M37-M40 | PUS S9, S11, S12, S19 |
| M41-M42 | Shared-memory sync for RT HIL; orbital environment (SGP4, eclipse, solar) |
| M43-M45 | FreeRTOS HIL support, validation and integration campaigns |
| M46-M47 | F3 sensor fidelity (Allan variance, I-V); S20 tunable AOCS gains + FDIR thresholds |
| M48-M49 | YAMCS end-to-end B-dot demo; closed-loop detumbling convergence |
| M50 | SMP-aligned model interface (ISmpModel, SmpEquipmentMixin, catalogue + checksmp) |
| M51-M52 | PUS S15 + S23; PUS S6 + S8, wire-compatible with openobsw |
| M63 | SMP lifecycle aligned with ECSS-E-ST-40-07C; SMP claims corrected |

### Planned

Grouped into release trains. M53-M62 come from a 2026-07 gap analysis against a real ESA EUCLID CDMU/AOCS/HGACL SVF validation campaign (see `REQUIREMENTS.md` SVF-DEV-188 to 201). Dates assume one part-time maintainer.

| Release | Theme | Milestones |
|---|---|---|
| v1.1 (Oct 2026) | Ship what is built | M50-M52, M63; M69 published Docker image |
| v1.2 (Q1 2027) | Second reference mission | M65 QUBIK (LSF PocketQube) feasibility spike; M66 QUBIK mission pack; M67 SatNOGS telemetry replay + model-vs-flight report; M56 post-hoc analysis tools |
| v1.3 (Q2 2027) | Operations preparation | M70 SCOS-2000 MIB import/export (revives SVF-DEV-098); M64 PLUTO (ECSS-E-ST-70-32C) procedure subset; M58 live YAMCS dashboards; M53 PUS S2 + S14 |
| v1.4 (Q3 2027) | Verification depth | M57 FDIR supervisor; M55 soak + worst-case harness; M54 bus utilisation + WCET; M61 wire protocol fault injection; M62 DiscreteLine hard-line model |
| v2.0 (2028) | Interoperability | M68 real SMP runtime bridge; M60 orbital environment into opensvf-kde; M59 multi-spacecraft |

---

## License

Apache 2.0

*Built by [lipofefeyt](https://github.com/lipofefeyt)*