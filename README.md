# OpenSVF

**Open-core spacecraft Software Validation Facility**

OpenSVF is a Python-based platform for validating spacecraft software and systems. It connects simulation models, test procedures, and requirements traceability into a single workflow — from a simple pytest run to a full ECSS-aligned campaign report.

---

## Why SVF?

Spacecraft validation typically requires:
- A simulation infrastructure to run models in lockstep
- A way to inject telecommands and observe telemetry
- Test procedures that produce ECSS-compatible verdicts
- A traceability matrix linking tests to requirements
- A campaign manager to run ordered test sequences

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

Output:

```
Campaign: EPS-VAL-001
Baseline: eps_integrated_v1
Duration: 1.4s

ID               Verdict          Duration
--------------------------------------------
TC-PWR-001       PASS                 0.3s
TC-PWR-002       PASS                 0.2s
TC-PWR-003       PASS                 0.2s
TC-PWR-004       PASS                 0.3s
TC-PWR-005       PASS                 0.3s
--------------------------------------------
Overall: PASS
```

A self-contained HTML report is generated at `results/EPS-VAL-001/report.html`.

---

## How It Works

### Equipment models

Every spacecraft subsystem is an `Equipment` — a Python class with named IN/OUT ports:

```python
class ReactionWheel(Equipment):
    def _declare_ports(self) -> list[PortDefinition]:
        return [
            PortDefinition("power_enable", PortDirection.IN),
            PortDefinition("torque_cmd",   PortDirection.IN,  unit="Nm"),
            PortDefinition("speed",        PortDirection.OUT, unit="rpm"),
        ]

    def do_step(self, t: float, dt: float) -> None:
        if self.read_port("power_enable") > 0.5:
            speed = self.read_port("speed") + self.read_port("torque_cmd") * dt * 100
            self.write_port("speed", speed)
```

FMU models (FMI 3.0, authored with pythonfmu) are wrapped as `FmuEquipment` with a parameter map translating FMU variable names to SRDB canonical names.

### Wiring

Equipment is connected via a human-readable YAML file:

```yaml
# srdb/wiring/eps_wiring.yaml
connections:
  - from: solar_array.eps.solar_array.generated_power
    to:   pcdu.eps.solar_input
    description: Solar array power to PCDU

  - from: pcdu.eps.pcdu.charge_current
    to:   battery.eps.battery.charge_current_in
    description: PCDU charge current to battery
```

### Test procedures

Test procedures use the `svf_session` pytest fixture:

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

Every test is linked to a requirement via `@pytest.mark.requirement()`. After every run:

```
SVF Requirements Traceability Matrix
============================================================
Requirement          Verdict      Test Case
------------------------------------------------------------
EPS-011              PASS         test_tc_pwr_001_battery_charges_in_sunlight
EPS-012              PASS         test_tc_pwr_002_battery_discharges_in_eclipse
EQP-001              PASS         test_equipment_construction
SVF-DEV-004          PASS         test_wiring_propagates_values
...
------------------------------------------------------------
Total requirements covered: 47
```

### Campaigns

A campaign is a YAML file that defines an ordered set of test procedures:

```yaml
campaign_id: EPS-VAL-001
description: Integrated EPS FMU validation campaign
svf_version: "0.1"
model_baseline: eps_integrated_v1

requirements:
  - EPS-011
  - EPS-012
  - EPS-013

test_cases:
  - id: TC-PWR-001
    test: tests/spacecraft/test_eps.py::test_tc_pwr_001_battery_charges_in_sunlight
    timeout: 60
```

Run with `svf run campaigns/eps_validation.yaml`.

---

## Reference Models

### Integrated EPS FMU

A spacecraft Electrical Power System model combining Solar Array, Battery (Li-Ion, non-linear SoC/voltage curve), and PCDU:

| Parameter | Direction | Unit | Range |
|---|---|---|---|
| eps.solar_array.illumination | IN (TC) | — | 0–1 |
| eps.load.power | IN (TC) | W | 0–200 |
| eps.battery.soc | OUT (TM) | — | 0.05–1.0 |
| eps.battery.voltage | OUT (TM) | V | 3.0–4.2 |
| eps.bus.voltage | OUT (TM) | V | 3.0–4.2 |
| eps.solar_array.generated_power | OUT (TM) | W | 0–120 |
| eps.battery.charge_current | OUT (TM) | A | -20–20 |

### Decomposed EPS

Three separate FMUs (SolarArray, Battery, PCDU) connected via `srdb/wiring/eps_wiring.yaml`.

---

## Project Structure

```
src/svf/
├── abstractions.py      TickSource, SyncProtocol, ModelAdapter ABCs
├── equipment.py         Equipment ABC with port interface
├── fmu_equipment.py     FmuEquipment wrapping FMI 3.0 FMUs
├── native_equipment.py  NativeEquipment wrapping Python step functions
├── wiring.py            WiringLoader and WiringMap
├── simulation.py        SimulationMaster
├── parameter_store.py   Thread-safe TM store
├── command_store.py     Thread-safe TC store
├── campaign/            Campaign schema, loader, executor, reporter
├── plugin/              pytest plugin (svf_session, observables, verdicts)
└── srdb/                Spacecraft Reference Database

tests/
├── unit/                SVF platform classes in isolation
├── equipment/           Generic Equipment contract (EQP-xxx)
├── integration/         SVF infrastructure mechanics
└── spacecraft/          Specific model behaviour (EPS-xxx)

srdb/
├── baseline/            EPS, AOCS, TTC, OBDH, Thermal parameter definitions
├── missions/            Mission-level overrides
└── wiring/              Equipment wiring YAML files

campaigns/               Campaign YAML definitions
models/                  FMU source and binaries
```

---

## Requirements & Traceability

Requirements are defined in `REQUIREMENTS.md` across functional areas:

| Area | Tag | Count |
|---|---|---|
| Simulation Core | [SIM] | 8 |
| Abstraction Layer | [ABS] | 8 |
| Communication Bus | [BUS] | 12 |
| SRDB | [SDB] | 6 |
| Equipment Contract | [EQP] | 12 |
| EPS Models | [EPS] | 16 |
| Test Orchestration | [ORC] | 8 |
| Campaign Manager | [CAM] | 5 |
| Reporting | [REP] | 6 |
| System & Infrastructure | [SYS] | 6 |

Check coverage at any time:

```bash
checkcov
```

---

## Technology Stack

| Concern | Choice |
|---|---|
| Simulation standard | FMI 3.0 |
| Model authoring | pythonfmu |
| Communication bus | Eclipse Cyclone DDS |
| Test runner | pytest + SVF plugin |
| Parameter database | SRDB (YAML + Python) |
| Equipment wiring | WiringMap + YAML |
| Reporting | Self-contained HTML + JUnit XML |

---

## Roadmap

| Milestone | Status |
|---|---|
| M1–M5 (core platform) | ✅ Complete |
| M6 - Bus Protocols (1553, SpW, CAN) | Planned |
| M7 - ICD Integration | Planned |
| M8 - Real-Time & HIL | Planned |
| M9 - Ground Segment (CCSDS/PUS, YAMCS) | Planned |

---

## License

Apache 2.0 — see LICENSE. Core platform open source, enterprise features commercial.

---

*Built by lipofefeyt*