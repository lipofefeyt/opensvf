# OpenSVF

**Open-core spacecraft Software Validation Facility**

OpenSVF is a Python-based platform for validating spacecraft software and systems. It connects simulation models, test procedures, requirements traceability, and campaign reporting into a single workflow — from a simple pytest run to a full ECSS-aligned campaign report.

---

## Why SVF?

Spacecraft validation typically requires:
- A simulation infrastructure to run models in lockstep
- Realistic spacecraft equipment models with correct physical interfaces
- A way to inject PUS telecommands and observe telemetry
- Test procedures that produce ECSS-compatible verdicts
- A traceability matrix linking tests to requirements
- A campaign manager to run ordered test sequences and generate reports

OpenSVF provides all of this in Python, with no proprietary tools required.

---

## Quick Start

### Install

```bash
git clone https://github.com/lipofefeyt/opensvf
cd opensvf
pip install -e ".[dev]"
```

### Run the test suite

```bash
pytest
```

### Run the EPS validation campaign

```bash
svf run campaigns/eps_validation.yaml
```

### Run the full PUS commanding chain campaign

```bash
svf run campaigns/pus_validation.yaml
```

Output:

```
Campaign: PUS-VAL-001
Baseline: obc_ttc_1553_rw_v1
Duration: 3.2s

ID               Verdict          Duration
--------------------------------------------
TC-PUS-001       PASS                 0.4s
TC-PUS-002       PASS                 0.3s
TC-PUS-003       PASS                 0.3s
TC-PUS-004       PASS                 0.3s
TC-PUS-005       PASS                 1.9s
--------------------------------------------
Overall: PASS
```

A self-contained HTML report is generated at `results/PUS-VAL-001/report.html`.

---

## How It Works

### Equipment models

Every spacecraft subsystem is an `Equipment` — a Python class with named IN/OUT ports typed to their physical interface:

```python
from svf.models.reaction_wheel import make_reaction_wheel
from svf.models.star_tracker import make_star_tracker
from svf.models.obc import ObcEquipment, ObcConfig
from svf.models.sbt import make_sbt

rw  = make_reaction_wheel(sync, store, cmd_store)
st  = make_star_tracker(sync, store, cmd_store, seed=42)
sbt = make_sbt(sync, store, cmd_store)
obc = ObcEquipment(ObcConfig(apid=0x101, param_id_map={...}), sync, store, cmd_store)
```

### Interface-typed ports

Equipment ports carry an `InterfaceType` — the wiring loader validates compatibility before simulation starts:

```python
class InterfaceType(enum.Enum):
    FLOAT       = "float"       # plain engineering value
    MIL1553_BC  = "mil1553_bc"  # 1553 Bus Controller
    MIL1553_RT  = "mil1553_rt"  # 1553 Remote Terminal
    SPACEWIRE   = "spacewire"   # SpaceWire node
    CAN         = "can"         # CAN node
    ANALOG      = "analog"      # analog signal
    DIGITAL     = "digital"     # digital signal
```

### PUS commanding chain

Ground commands flow through standards-compliant PUS-C packets (ECSS-E-ST-70-41C):

```
Test procedure
    ↓ PusTcPacket(service=20, subservice=1, app_data=pack(param_id, value))
TtcEquipment.send_tc()
    ↓ serialise to bytes with CRC-16
ObcEquipment.receive_tc()
    ↓ parse → route S20/1 → CommandStore.inject(canonical_name, value)
Mil1553Bus
    ↓ BC_to_RT subaddress routing → RT5/SA1
ReactionWheel
    ↓ torque_cmd → integrate → speed
ObcEquipment
    ↓ TM(3,25) HK report → TM(1,7) completion
```

### Bus fault injection for FDIR testing

```python
# Inject NO_RESPONSE fault on RT5 for 5 seconds
bus.inject_fault(BusFault(
    fault_type=FaultType.NO_RESPONSE,
    target="rt5",
    duration_s=5.0,
    injected_at=t,
))

# Or via svf_command_schedule in test procedures
@pytest.mark.svf_command_schedule([
    (10.0, "bus.platform_1553.fault.rt5.no_response", 5.0),
])
```

### Test procedures

```python
@pytest.mark.svf_fmus([FmuConfig("models/EpsFmu.fmu", "eps", EPS_MAP)])
@pytest.mark.svf_stop_time(120.0)
@pytest.mark.svf_dt(1.0)
@pytest.mark.svf_initial_commands([("eps.solar_array.illumination", 1.0)])
@pytest.mark.svf_command_schedule([(60.0, "eps.solar_array.illumination", 0.0)])
@pytest.mark.requirement("EPS-011", "EPS-012")
def test_eclipse_transition(svf_session) -> None:
    """Battery charges in sunlight then discharges after eclipse at t=60s."""
    svf_session.observe("eps.battery.soc").exceeds(0.85).within(90.0)
    svf_session.observe("eps.battery.charge_current").drops_below(0.0).within(60.0)
    svf_session.stop()
```

### Requirements traceability

Every test is linked to a requirement. After every run:

```
SVF Requirements Traceability Matrix
============================================================
Requirement          Verdict      Test Case
------------------------------------------------------------
EPS-011              PASS         test_tc_pwr_001_battery_charges_in_sunlight
PUS-010              PASS         test_tc_pus_005_full_chain_ground_to_rw
ST-003               PASS         test_st_blinded_when_sun_angle_below_exclusion
...
------------------------------------------------------------
Total requirements covered: 95
```

### Campaigns

```yaml
campaign_id: PUS-VAL-001
description: PUS TM/TC end-to-end validation
svf_version: "0.1"
model_baseline: obc_ttc_1553_rw_v1

requirements:
  - SVF-DEV-037
  - PUS-010
  - PUS-011

test_cases:
  - id: TC-PUS-001
    test: tests/spacecraft/test_pus_procedures.py::test_tc_pus_001_are_you_alive
    timeout: 30
```

Run with `svf run campaigns/pus_validation.yaml`.

---

## Reference Equipment Library

| Equipment | Subsystem | Interface | Key Physics |
|---|---|---|---|
| `ObcEquipment` | DHS | 1553 BC | Mode FSM, OBT, watchdog, PUS routing |
| `TtcEquipment` | TTC | software | TC/TM byte pipe to/from OBC |
| `make_reaction_wheel()` | AOCS | 1553 RT | Torque integration, friction, temperature |
| `make_star_tracker()` | AOCS | SpW / 1553 | Quaternion propagation, noise, sun blinding |
| `make_sbt()` | TTC | UART | Carrier lock, mode FSM, bit rates |
| `EpsFmu` | EPS | FMI 3.0 | Solar array, Li-Ion battery, PCDU |

Full interface contracts in [`docs/equipment_library.md`](docs/equipment_library.md).

### EPS Parameters

| Parameter | Direction | Unit |
|---|---|---|
| eps.solar_array.illumination | IN (TC) | — |
| eps.load.power | IN (TC) | W |
| eps.battery.soc | OUT (TM) | — |
| eps.battery.voltage | OUT (TM) | V |
| eps.bus.voltage | OUT (TM) | V |
| eps.solar_array.generated_power | OUT (TM) | W |
| eps.battery.charge_current | OUT (TM) | A |

---

## Project Structure

```
src/svf/
├── abstractions.py      TickSource, SyncProtocol, ModelAdapter ABCs
├── equipment.py         Equipment ABC with InterfaceType port system
├── bus.py               Bus ABC with fault injection
├── mil1553.py           MIL-STD-1553 adapter
├── fmu_equipment.py     FMI 3.0 FMU wrapper
├── native_equipment.py  Python step function wrapper
├── wiring.py            WiringLoader with interface type validation
├── simulation.py        SimulationMaster
├── parameter_store.py   Thread-safe TM store
├── command_store.py     Thread-safe TC store
├── pus/                 PUS-C TC/TM packets and service catalogue
├── models/              Reference equipment models
│   ├── obc.py           OBC — PUS router + DHS state machine
│   ├── ttc.py           TTC — ground/OBC interface
│   ├── reaction_wheel.py RW — torque, friction, temperature
│   ├── star_tracker.py  ST — quaternion, noise, blinding
│   └── sbt.py           SBT — carrier lock, mode, bit rates
├── campaign/            Campaign schema, loader, executor, reporter
├── plugin/              pytest plugin
└── srdb/                Spacecraft Reference Database

tests/
├── unit/pus/            PUS TC/TM tests
├── unit/campaign/       Campaign manager tests
├── equipment/           Equipment contract and bus tests
├── integration/         SVF infrastructure tests
└── spacecraft/          End-to-end model behaviour tests

srdb/baseline/           EPS, AOCS, TTC, OBDH, Thermal, DHS parameters
campaigns/               EPS, 1553, PUS validation campaigns
docs/                    Architecture, equipment library
```

---

## Validated Campaigns

| Campaign | Procedures | Status |
|---|---|---|
| `campaigns/eps_validation.yaml` | TC-PWR-001 through TC-PWR-005 | ✅ PASS |
| `campaigns/mil1553_validation.yaml` | TC-1553-001 through TC-1553-005 | ✅ PASS |
| `campaigns/pus_validation.yaml` | TC-PUS-001 through TC-PUS-005 | ✅ PASS |

---

## Requirements Coverage

Requirements are defined in `REQUIREMENTS.md` across functional areas:

| Area | Tag | Status |
|---|---|---|
| Simulation Core | [SIM] | Implemented |
| Abstraction Layer | [ABS] | Implemented |
| Communication Bus | [BUS] | Implemented |
| SRDB | [SDB] | Implemented |
| Equipment Contract | [EQP] | Implemented |
| EPS Models | [EPS] | Implemented |
| MIL-STD-1553 | [1553] | Implemented |
| PUS TM/TC | [PUS] | Implemented |
| OBC DHS | [OBC] | Implemented |
| Star Tracker | [ST] | Implemented |
| S-Band Transponder | [SBT] | Implemented |
| Reaction Wheel | [RW] | Implemented |
| Test Orchestration | [ORC] | Implemented |
| Campaign Manager | [CAM] | Implemented |
| Reporting | [REP] | Implemented |
| System & Infrastructure | [SYS] | Implemented |

Check coverage at any time:

```bash
checkcov
```

---

## Technology Stack

| Concern | Choice |
|---|---|
| Simulation standard | FMI 3.0 |
| Model abstraction | Equipment + InterfaceType ports |
| Bus protocols | Bus extends Equipment (1553 done, SpW/CAN M10) |
| PUS TM/TC | ECSS-E-ST-70-41C, CRC-16/CCITT |
| Communication bus | Eclipse Cyclone DDS |
| Parameter database | SRDB (YAML + Python) |
| Test runner | pytest + SVF plugin |
| Traceability | @pytest.mark.requirement() + auto matrix |
| Campaign manager | YAML + CLI (`svf run`) |
| Reporting | Self-contained HTML + JUnit XML |
| Packaging | pyproject.toml (Apache 2.0) |

---

## Roadmap

| Milestone | Status |
|---|---|
| M1–M7 (core platform + PUS TM/TC) | ✅ Complete |
| M8 - Equipment Interface Library | ✅ Complete |
| M9 - Real-Time & HIL | Planned |
| M10 - Ground Segment (YAMCS, SpW, CAN) | Planned |

---

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for how to add equipment models, write test procedures, and contribute to the platform.

---

## License

Apache 2.0 — see [`LICENSE`](LICENSE). Core platform open source, enterprise features commercial.

---

*Built by lipofefeyt*