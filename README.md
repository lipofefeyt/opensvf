# OpenSVF

**Open-core spacecraft Software Validation Facility**

OpenSVF is a Python-based platform for validating spacecraft software and systems — from individual subsystem models to closed-loop integration scenarios with a real OBSW binary running inside.

---

## What is an SVF?

From ECSS-E-TM-10-21A:

> *System modelling and simulation is a support activity to OBSW validation. The ability to inject failures in the models enables the user to trigger the OBSW monitoring processes as well as to exercise the FDIR mechanisms. Sometimes simpler so-called "model responders" may be sufficient to test the open-loop behaviour of the OBSW. The SVF is used repeatedly during the programme for each version of the onboard software and each version of the spacecraft database associated with it.*

OpenSVF implements this across four validation levels:

| Level | Description | Status |
|---|---|---|
| 1 — Model validation | Each subsystem verified in isolation | ✅ Complete |
| 2 — Interface validation | Bus interfaces + full fault matrix | ✅ Complete |
| 3 — Integration validation | Models + interfaces + PUS chain | ✅ Complete |
| 4 — System validation | Real OBSW binary under test | ✅ Complete |

---

## Quick Start

```bash
git clone https://github.com/lipofefeyt/opensvf
cd opensvf
pip install -e ".[dev]"

# Run all tests
pytest

# Run a campaign
svf run campaigns/fdir_chain.yaml

# Run with real OBSW (requires obsw_sim binary)
pytest tests/hardware/ -v
```

---

## Key Features
- **KDE (Kinematics & Dynamics Engine):** High-fidelity 6-DOF rigid body physics integrated via FMI 2.0.
- **Full Traceability:** 100% requirement coverage tracked via `checkcov` and `traceability.txt`.
- **Hybrid Modeling:** Support for FMI 2.0/3.0 (C++/Python) and native Python models.
- **Deterministic Sync:** Lockstep execution over Eclipse Cyclone DDS.

---

## The OBC Stack

Three drop-in implementations — swap with one line at the composition root:

```python
# Level 3 — simulated OBC with rule-based OBSW behaviour
obc = ObcStub(config, sync, store, cmd_store, rules=[
    Rule(
        name="low_battery_safe",
        watch="eps.battery.soc",
        condition=lambda e: e is not None and e.value < 0.3,
        action=lambda cs, t: cs.inject("dhs.obc.mode_cmd", 0.0, t=t),
    ),
])

# Level 4 — real OBSW binary under test (one line change)
obc = OBCEmulatorAdapter(
    sim_path="obsw_sim",
    sync_protocol=sync,
    store=store,
    command_store=cmd_store,
)

# TtcEquipment accepts both via ObcInterface protocol
ttc = TtcEquipment(obc, sync, store, cmd_store)
```

The `OBCEmulatorAdapter` wraps any OBSW binary that speaks the pipe protocol:

```
SVF → stdin:  [uint16 BE length][TC frame bytes]
stdin → SVF:  [uint16 BE length][TM packet bytes] ... [0xFF sync]
```

One SVF tick = one OBC control cycle.

---

## How It Works

### PUS commanding chain

```
Test procedure / Ground
    ↓ PusTcPacket(service=20, subservice=1, app_data=pack(param_id, value))
TtcEquipment.send_tc()
    ↓ serialise with CRC-16 → ObcInterface.receive_tc()
ObcEquipment / ObcStub / OBCEmulatorAdapter
    ↓ route S20/1 → CommandStore.inject(canonical_name, value)
Mil1553Bus
    ↓ BC_to_RT subaddress routing
ReactionWheel
    ↓ torque_cmd → integrate → speed
OBC
    ↓ TM(3,25) HK report + TM(1,7) completion
```

### Fault injection for FDIR testing

```python
# Bus-level fault via svf_command_schedule
@pytest.mark.svf_command_schedule([
    (10.0, "bus.platform_1553.fault.rt5.no_response", 5.0),
])

# OBC stub detects fault via rule
Rule(
    name="rw_fault_detect",
    watch="aocs.rw1.speed",
    condition=lambda e: e is not None and abs(e.value) < 1.0,
    action=lambda cs, t: cs.inject("dhs.obc.mode_cmd", 0.0, t=t),
)
```

---

## Reference Equipment Library

| Equipment | Subsystem | Interface | Key Physics |
|---|---|---|---|
| `DynamicsFmu` | KDE | FMI 2.0 | 6-DOF Kinematics, B-Field, Quaternions |
| `ObcEquipment` | DHS | 1553 BC | Mode FSM, OBT, watchdog, PUS routing |
| `ObcStub` | DHS | — | Rule engine, closed-loop FDIR |
| `OBCEmulatorAdapter` | DHS | binary pipe | Real OBSW under test |
| `TtcEquipment` | TTC | ObcInterface | TC/TM byte pipe |
| `make_reaction_wheel()` | AOCS | 1553 RT | Torque, friction, temperature |
| `make_star_tracker()` | AOCS | SpW/1553 | Quaternion, noise, sun blinding |
| `make_sbt()` | TTC | UART | Carrier lock, mode FSM, bit rates |
| `make_pcdu()` | EPS | 1553/CAN | LCL switching, MPPT, UVLO |
| `EpsFmu` | EPS | FMI 3.0 | Solar array, Li-Ion battery, PCDU |

Full contracts: [`docs/equipment-library.md`](docs/equipment-library.md)

---

## Validated Campaigns

| Campaign | Scenario | Level |
|---|---|---|
| `eps_validation.yaml` | EPS power system | 1 |
| `mil1553_validation.yaml` | 1553 bus + FDIR | 2 |
| `pus_validation.yaml` | PUS commanding chain | 3 |
| `platform_validation.yaml` | Full platform | 3 |
| `safe_mode_recovery.yaml` | Closed-loop recovery (OBC stub) | 3/4 |
| `nominal_ops.yaml` | Nominal operations (OBC stub) | 3/4 |
| `contact_pass.yaml` | Ground contact pass (OBC stub) | 3/4 |
| `fdir_chain.yaml` | FDIR chain end-to-end (OBC stub) | 3/4 |

---

## Project Structure

```
src/svf/
├── models/
│   ├── obc.py              ObcEquipment — simulated OBC
│   ├── obc_stub.py         ObcStub — rule-based OBSW simulator
│   ├── obc_emulator.py     OBCEmulatorAdapter — real OBSW via pipe
│   ├── ttc.py              TtcEquipment (accepts ObcInterface)
│   ├── reaction_wheel.py   RW with friction + temperature
│   ├── star_tracker.py     ST with quaternion + blinding
│   ├── sbt.py              SBT with carrier lock + modes
│   └── pcdu.py             PCDU with LCL + MPPT + UVLO
├── pus/                    PUS-C TC/TM (S1/3/5/17/20)
├── campaign/               YAML campaigns + HTML reports
├── plugin/                 pytest plugin (svf_session, observables)
└── srdb/                   Spacecraft Reference Database

tests/
├── spacecraft/             Model + integration + system tests
├── hardware/               HIL tests (require obsw_sim)
│                           Run: pytest tests/hardware/ -v
└── unit/ equipment/        Unit + contract tests
```

---

## Roadmap

| Milestone | Status |
|---|---|
| M1–M10 (core platform through closed-loop validation) | ✅ Done |
| M11 - OBC Emulator Integration | ✅ Done |
| M12 - Ground Segment (YAMCS, SpW, CAN) | Planned |

---

## License

Apache 2.0 — see [`LICENSE`](LICENSE).

---

*Built by lipofefeyt*