# OpenSVF

Standards-based Software Validation Facility for spacecraft applications.

Simulation, test orchestration, and requirements traceability in one open-core toolchain.

## What's new in v0.2

<<<<<<< HEAD
**OBCEmulatorAdapter** (`src/svf/models/obc_emulator.py`) — closes the loop between OpenSVF and [openobsw](https://github.com/lipofefeyt/openobsw). The real OBSW binary runs as a subprocess, driven by the simulation master via a binary pipe protocol. Drop-in replacement for `ObcStub` at the composition root.

```python
# Before — simulated OBC:
obc = ObcStub(config=ObcConfig(...), rules=[...], ...)

# After — real OBSW under test:
from svf.models.obc_emulator import OBCEmulatorAdapter
obc = OBCEmulatorAdapter(sim_path="path/to/obsw_sim", ...)
```
=======
## What is an SVF?

From ECSS-E-TM-10-21A:

> *System modelling and simulation is a support activity to OBSW validation, including Data Handling, AOCS and GNC and Payload software. The ability to inject failures in the models enables the user to trigger the OBSW monitoring processes as well as to exercise the FDIR mechanisms. Sometimes a less representative approach may be adopted — for example when validating the flight software against its specification: in this case, simpler so-called "model responders" (or test stubs representing equipment) may be sufficient to test the open-loop behaviour of the OBSW. The SVF is used repeatedly during the programme for each version of the onboard software and each version of the spacecraft database associated with it.*

OpenSVF implements this definition:

- **Equipment models** — realistic simplified physics for OBC, EPS, AOCS, TTC subsystems
- **Fault injection** — bus-level (1553 NO_RESPONSE, BUS_ERROR) and model-level failure modes
- **PUS TC/TM** — standards-compliant commanding chain (ECSS-E-ST-70-41C)
- **OBSW stub** — configurable behaviour simulator until real OBSW is available
- **HIL adapter** — plug-in point for OBC emulator when ready
- **SRDB** — spacecraft parameter database versioned alongside each OBSW release
>>>>>>> 8842d692dd3c7747c9e3706822cd65f154f1e33a

Protocol (stdin/stdout binary pipe):
- **stdin**: `[uint16 BE length][TC frame bytes]`
- **stdout**: `[uint16 BE length][TM packet bytes]` + `[0xFF]` sync byte per cycle

The `0xFF` sync byte drives SimulationMaster lockstep — one OBC control cycle per simulation tick.

## Quick start

```bash
git clone https://github.com/lipofefeyt/opensvf
cd opensvf
pip install -e ".[dev]"
pytest
```

<<<<<<< HEAD
## Running the OBC emulator tests

Build `obsw_sim` from [openobsw](https://github.com/lipofefeyt/openobsw), copy the binary to the OpenSVF workspace, then:

```bash
OBSW_SIM=/path/to/obsw_sim pytest tests/test_obc_emulator_adapter.py -v
```

## Architecture
=======
### Run a campaign

```bash
# EPS power system validation
svf run campaigns/eps_validation.yaml

# MIL-STD-1553 bus and FDIR validation
svf run campaigns/mil1553_validation.yaml

# Full PUS commanding chain validation
svf run campaigns/pus_validation.yaml

# Platform integration (all models together)
svf run campaigns/platform_validation.yaml
```

Example output:
>>>>>>> 8842d692dd3c7747c9e3706822cd65f154f1e33a

```
SimulationMaster
    ├── ReactionWheelEquipment   (FMU physics)
    ├── StarTrackerEquipment     (FMU physics)
    ├── PCDUEquipment            (FMU physics)
    ├── SBandTransponderEquipment(FMU physics)
    └── OBCEmulatorAdapter  ←── openobsw obsw_sim subprocess
            │  stdin: TC frames
            │  stdout: TM packets + 0xFF sync
            └── obsw_sim (real OBSW binary)
```

<<<<<<< HEAD
## Standards

ECSS-E-TM-10-21A system-level validation. Equipment models implement FMI 3.0.
=======
A self-contained HTML report is generated at `results/{campaign_id}/report.html`.

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

Equipment ports carry an `InterfaceType` — the wiring loader validates compatibility at load time, before simulation starts:

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
Test procedure / Ground
    ↓ PusTcPacket(service=20, subservice=1, app_data=pack(param_id, value))
TtcEquipment.send_tc()
    ↓ serialise with CRC-16
ObcEquipment.receive_tc()
    ↓ parse → route S20/1 → CommandStore.inject(canonical_name, value)
Mil1553Bus
    ↓ BC_to_RT subaddress routing
ReactionWheel
    ↓ torque_cmd → integrate → speed
ObcEquipment
    ↓ TM(3,25) HK report + TM(1,7) completion
```

### Fault injection for FDIR testing

```python
# Inject NO_RESPONSE fault — RT silent for 5 seconds
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
def test_obc_detects_rw_timeout(svf_session) -> None:
    svf_session.observe("dhs.obc.watchdog_status").exceeds(0.5).within(5.0)
    svf_session.stop()
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
OBC-005              PASS         test_obc_watchdog_reset_on_double_timeout
...
------------------------------------------------------------
```

---

## Reference Equipment Library

| Equipment | Subsystem | Interface | Key Physics |
|---|---|---|---|
| `ObcEquipment` | DHS | 1553 BC | Mode FSM, OBT, watchdog, PUS routing |
| `TtcEquipment` | TTC | software | TC/TM byte pipe to/from OBC |
| `make_reaction_wheel()` | AOCS | 1553 RT | Torque integration, friction, temperature |
| `make_star_tracker()` | AOCS | SpW/1553 | Quaternion propagation, noise, sun blinding |
| `make_sbt()` | TTC | UART | Carrier lock, mode FSM, bit rates |
| `EpsFmu` | EPS | FMI 3.0 | Solar array, Li-Ion battery, PCDU |

Full interface contracts: [`docs/equipment_library.md`](docs/equipment_library.md)

---

## Validated Campaigns

| Campaign | Test Procedures | Status |
|---|---|---|
| `campaigns/eps_validation.yaml` | TC-PWR-001 through TC-PWR-005 | ✅ PASS |
| `campaigns/mil1553_validation.yaml` | TC-1553-001 through TC-1553-005 | ✅ PASS |
| `campaigns/pus_validation.yaml` | TC-PUS-001 through TC-PUS-005 | ✅ PASS |
| `campaigns/platform_validation.yaml` | TC-PLAT-001 through TC-PLAT-006 | ✅ PASS |

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
│   ├── tc.py            PusTcPacket, parser, builder, CRC-16
│   ├── tm.py            PusTmPacket, parser, builder
│   └── services.py      S1, S3, S5, S17, S20
├── models/              Reference equipment models
│   ├── obc.py           OBC — PUS router + DHS state machine
│   ├── ttc.py           TTC — ground/OBC interface
│   ├── reaction_wheel.py RW — torque, friction, temperature
│   ├── star_tracker.py  ST — quaternion, noise, sun blinding
│   └── sbt.py           SBT — carrier lock, mode, bit rates
├── campaign/            Campaign schema, loader, executor, reporter
├── plugin/              pytest plugin (svf_session, observables, verdicts)
└── srdb/                Spacecraft Reference Database

tests/
├── unit/pus/            PUS TC/TM tests
├── unit/campaign/       Campaign manager tests
├── equipment/           Equipment contract and bus tests
├── integration/         SVF infrastructure tests
└── spacecraft/          End-to-end model behaviour tests

srdb/baseline/           EPS, AOCS, TTC, OBDH, Thermal, DHS
campaigns/               Validation campaigns
docs/                    Architecture, equipment library
```

---

## Requirements Coverage

```bash
checkcov   # verify all BASELINED requirements have passing tests
```

Requirements are defined in `REQUIREMENTS.md` across 16 functional areas:
`[SIM]` `[ABS]` `[BUS]` `[SDB]` `[EQP]` `[EPS]` `[1553]` `[PUS]`
`[OBC]` `[ST]` `[SBT]` `[RW]` `[PCDU]` `[ORC]` `[CAM]` `[REP]` `[SYS]`

---

## Roadmap

| Milestone | Objective | Status |
|---|---|---|
| M1–M8 | Core platform, PUS TM/TC, equipment library | ✅ Done |
| M9 - Model & Interface Validation | Failure coverage, PCDU, full fault matrix | In progress |
| M10 - Integration & System Validation | Full scenarios, FDIR chains, OBC stub | Planned |
| M11 - Real-Time & HIL | RT_PREEMPT, HIL adapter for OBC emulator | Planned |
| M12 - Ground Segment | YAMCS, XTCE, MIB, SpW, CAN | Planned |

---

## Technology Stack

| Concern | Choice |
|---|---|
| Simulation standard | FMI 3.0 |
| Model abstraction | Equipment + InterfaceType ports |
| Bus protocols | Bus extends Equipment (1553 done, SpW/CAN M12) |
| PUS TM/TC | ECSS-E-ST-70-41C, CRC-16/CCITT |
| Communication bus | Eclipse Cyclone DDS |
| Parameter database | SRDB (YAML + Python) |
| Test runner | pytest + SVF plugin |
| Traceability | @pytest.mark.requirement() + auto matrix |
| Campaign manager | YAML + CLI (`svf run`) |
| Reporting | Self-contained HTML + JUnit XML |
| Packaging | pyproject.toml (Apache 2.0) |

---

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for how to add equipment models, write test procedures, and contribute to the platform.

---
>>>>>>> 8842d692dd3c7747c9e3706822cd65f154f1e33a

## License

Apache 2.0