# OpenSVF

**Open-core spacecraft Software Validation Facility**

OpenSVF is a Python-based platform for validating spacecraft software and systems. From a single YAML file, configure your spacecraft, load your OBSW binary, run test campaigns, and get results — without writing boilerplate Python.

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

testosvf                             # ~400 tests
bash scripts/demo.sh                 # SVF + YAMCS

docker build -t opensvf .
docker run --rm opensvf testosvf
```

---

## Zero-Python Entry Point

Configure your spacecraft in YAML and run:

```yaml
# spacecraft.yaml
spacecraft: MySat-1

obsw:
  type: pipe
  binary: ./obsw_sim       # your OBSW binary

equipment:
  - id: kde
    model: dynamics
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

buses:
  - id: aocs_bus
    type: mil1553
    rt_count: 8
    mappings:
      - rt: 5  sa: 1  parameter: aocs.rw1.torque_cmd  direction: BC_to_RT
      - rt: 5  sa: 2  parameter: aocs.rw1.speed        direction: RT_to_BC

wiring:
  auto: true   # auto-connects matching port names

simulation:
  dt: 0.1
  stop_time: 300.0
  seed: 42
```

```python
from svf.spacecraft import SpacecraftLoader
master = SpacecraftLoader.load("spacecraft.yaml")
master.run()
```

---

## The Closed Loop

```
opensvf-kde (C++ / Eigen3)          Your OBSW (C11)
  6-DOF physics engine                 Real flight algorithms
  Euler's equations                    FSM: SAFE → b-dot
  Quaternion kinematics                FSM: NOMINAL → ADCS PD
  Earth B-field model                  PUS service stack
         │                                    │
         │  true ω, B  via FMI 2.0           │ 0x02 sensor frames
         ▼                                    │ 0x03 actuator frames
              opensvf (Python)        ◄───────►
              SVF tick loop
              Sensor + actuator models
                    │
                    │  PUS TM/TC via TCP
                    ▼
               YAMCS 5.12.6
               Ground station UI
```

---

## OBSW Transport Modes

| Mode | Description | Use Case |
|---|---|---|
| `pipe` | stdin/stdout, x86_64 or aarch64 QEMU | Development, CI |
| `socket` | TCP to Renode ZynqMP uart0 | Peripheral-level SIL |
| `stub` | Rule-based ObcStub | Unit testing without binary |

```yaml
# Pipe mode (default)
obsw:
  type: pipe
  binary: ./obsw_sim

# Socket mode (Renode)
obsw:
  type: socket
  host: localhost
  port: 3456

# Stub mode (no binary needed)
obsw:
  type: stub
```

---

## Target Architectures

| Binary | Architecture | Transport | Status |
|---|---|---|---|
| `obsw_sim` | x86_64 | stdin/stdout pipe | ✅ Production |
| `obsw_sim_aarch64` | aarch64 (ZynqMP PS) | stdin/stdout pipe via QEMU | ✅ Validated |
| `obsw_zynqmp` | aarch64 bare-metal | Cadence UART → Renode socket | ✅ Validated |

---

## Bus Adapters

Three bus protocols supported, all configurable from YAML:

| Bus | Type | Fault Injection |
|---|---|---|
| MIL-STD-1553B | `mil1553` | BUS_ERROR, NO_RESPONSE, BAD_PARITY |
| SpaceWire + RMAP | `spacewire` | Link error, invalid address |
| CAN 2.0B (ECSS) | `can` | Bus-off, node error, bad parity |

---

## Hardware Profiles

Equipment physics constants loaded from YAML profiles:

```yaml
equipment:
  - id: rw1
    model: reaction_wheel
    hardware_profile: rw_sinclair_rw003   # 5000 rpm, 30 mNm, J=0.00011 kg·m²
```

10 profiles across 6 equipment types in `srdb/data/hardware/`.

---

## Monte Carlo

```bash
python3 scripts/mc_bdot_detumbling.py --runs 20

# Result: 100% convergence, final rate 0.0001 rad/s
# Initial rates: 0.12–4.63 rad/s, all converge in 60s
```

---

## Model Organisation

```
src/svf/models/
├── aocs/       reaction_wheel, magnetometer, magnetorquer, gyroscope,
│               star_tracker, css, bdot_controller, thruster, gps
├── dynamics/   kde_equipment + fmu/DynamicsFmu
├── eps/        pcdu + fmu/{EpsFmu, BatteryFmu, SolarArrayFmu, PcduFmu}
├── dhs/        obc, obc_stub, obc_emulator
├── ttc/        ttc, sbt
└── thermal/    thermal
```

---

## YAMCS Ground Station

```bash
yamcs-start && yamcs-log-follow
svf-campaign campaigns/realtime_detumbling.yaml
```

Open `http://localhost:8090` — live TM parameters, TC commanding.

---

## SRDB

```bash
obsw-srdb-export --data-dir srdb/data --output-dir srdb/export
```

Hardware profiles in `srdb/data/hardware/`. SRDB version handshake at startup.

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
| M1–M12 — Core platform through ground segment | ✅ Done |
| M13 — SIL Attitude Loop Closure | ✅ Done |
| M14 — Real-Time & HIL + Renode socket + variable timestep | ✅ Done |
| M15 — Extended Bus Protocols (SpW, CAN) | ✅ Done |
| M16 — SRDB Maturity | ✅ Done |
| M17 — Equipment Configurability | ✅ Done |
| M18 — Architecture Refactor | ✅ Done |
| M19 — Spacecraft Configuration DSL | ✅ Done |
| M20 — Structured Test Procedure API | 🔄 In progress |
| M21 — Mission-Level Results Reporting | 📋 Planned |
| M22 — OBSW Integration Guide | 📋 Planned |

---

## License

Apache 2.0

---

*Built by lipofefeyt · [opensvf-kde](https://github.com/lipofefeyt/opensvf-kde) · [openobsw](https://github.com/lipofefeyt/openobsw)*