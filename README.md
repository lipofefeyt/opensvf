# OpenSVF

**Open-core spacecraft Software Validation Facility**

OpenSVF is a Python-based platform for validating spacecraft software and systems — from individual subsystem models to full closed-loop co-simulation with a C++ physics engine and a real OBSW binary running inside.

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
| 4 — System validation | Real OBSW + C++ physics co-simulation | ✅ Complete |

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

# Run closed-loop detumbling test (requires KDE FMU)
pytest tests/integration/test_closed_loop_detumbling.py -v

# Run with real OBSW (requires obsw_sim binary)
pytest tests/hardware/ -v
```

---

## Closed-Loop Co-Simulation

The full simulation loop connects three independent projects:

```
opensvf-kde (C++ / Eigen3)          openobsw (C11 / bare metal)
  6-DOF physics engine                 Real OBSW binary
  Euler's equations                    b-dot algorithm
  Quaternion kinematics                PUS S1/3/5/8/17/20
  Earth B-field model                  FDIR state machine
         │                                     │
         │  true ω, B (via FMI 2.0)           │  TC/TM (via pipe protocol)
         ▼                                     ▼
              opensvf (Python / pytest)
                SVF tick loop (DDS lockstep)
                Sensor models (MAG, GYRO, ST, CSS)
                Actuator models (MTQ, RW)
                OBC models (stub / emulator)
                PUS commanding chain
                Campaign manager + reports
```

One SVF tick = one physics step + one OBC control cycle + all sensor/actuator updates.

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

---

## The Physics Engine (opensvf-kde)

The KDE FMU provides high-fidelity 6-DOF spacecraft dynamics:

```python
# KDE as a NativeEquipment — participates in SVF tick loop
kde = make_kde_equipment(sync, store, cmd_store)

# Wiring closes the loop: MTQ torques → KDE → true state → sensors
wiring = WiringLoader({"kde": kde, "mag": mag, "mtq": mtq, ...}).load(
    Path("srdb/wiring/kde_wiring.yaml")
)
```

**KDE ports:**

| Port | Direction | Unit | Description |
|---|---|---|---|
| `aocs.mtq.torque_x/y/z` | IN | Nm | Mechanical torques from MTQ |
| `aocs.truth.rate_x/y/z` | OUT | rad/s | True angular velocity |
| `aocs.mag.true_x/y/z` | OUT | T | True magnetic field |
| `aocs.attitude.quaternion_w/x/y/z` | OUT | — | True attitude quaternion |

---

## Reference Equipment Library

| Equipment | Factory | Subsystem | Interface | Key Physics |
|---|---|---|---|---|
| `ObcEquipment` | class | DHS | 1553 BC | Mode FSM, OBT, watchdog, PUS routing |
| `ObcStub` | class | DHS | — | Rule engine, closed-loop FDIR |
| `OBCEmulatorAdapter` | class | DHS | binary pipe | Real OBSW under test |
| `TtcEquipment` | class | TTC | ObcInterface | TC/TM byte pipe |
| `make_kde_equipment()` | factory | Dynamics | FMI 2.0 | 6-DOF physics, B-field model |
| `make_reaction_wheel()` | factory | AOCS | 1553 RT | Torque, friction, temperature |
| `make_star_tracker()` | factory | AOCS | SpW/1553 | Quaternion, noise, sun blinding |
| `make_magnetometer()` | factory | AOCS | — | B-field measurement + noise |
| `make_magnetorquer()` | factory | AOCS | — | Torque = m × B |
| `make_gyroscope()` | factory | AOCS | — | Rate measurement + ARW noise |
| `make_css()` | factory | AOCS | — | Sun vector + eclipse detection |
| `make_bdot_controller()` | factory | AOCS | — | m = −k·Ḃ detumbling law |
| `make_sbt()` | factory | TTC | UART | Carrier lock, mode FSM |
| `make_pcdu()` | factory | EPS | — | LCL switching, MPPT, UVLO |
| `EpsFmu` | FmuEquipment | EPS | FMI 3.0 | Solar array, Li-Ion battery |

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

## Related Projects

| Project | Role |
|---|---|
| [opensvf-kde](https://github.com/lipofefeyt/opensvf-kde) | C++ 6-DOF physics engine (FMI 2.0 FMU) |
| [openobsw](https://github.com/lipofefeyt/openobsw) | C11 OBSW: PUS services, b-dot, FDIR, validated on MSP430 |

---

## Project Structure

```
src/svf/
├── models/
│   ├── kde_equipment.py    KDE FMU wrapper (NativeEquipment)
│   ├── obc.py              ObcEquipment — simulated OBC
│   ├── obc_stub.py         ObcStub — rule-based OBSW simulator
│   ├── obc_emulator.py     OBCEmulatorAdapter — real OBSW via pipe
│   ├── ttc.py              TtcEquipment (accepts ObcInterface)
│   ├── reaction_wheel.py   RW with friction + temperature
│   ├── star_tracker.py     ST with quaternion + blinding
│   ├── magnetometer.py     MAG with noise + bias drift
│   ├── magnetorquer.py     MTQ torque = m × B
│   ├── gyroscope.py        GYRO with ARW noise + bias
│   ├── css.py              CSS sun vector + eclipse
│   ├── bdot_controller.py  B-dot reference controller
│   ├── sbt.py              SBT with carrier lock + modes
│   ├── pcdu.py             PCDU with LCL + MPPT + UVLO
│   └── fmu/
│       ├── DynamicsFmu.py  Raw FMI wrapper for KDE
│       ├── EpsFmu.py       EPS FMU source
│       └── ...
├── pus/                    PUS-C TC/TM (S1/3/5/8/17/20)
├── campaign/               YAML campaigns + HTML reports
├── plugin/                 pytest plugin (svf_session, observables)
└── srdb/                   Spacecraft Reference Database

srdb/wiring/
├── kde_wiring.yaml         Full closed-loop: KDE↔sensors↔actuators
└── bdot_wiring.yaml        Standalone b-dot: MAG→bdot→MTQ

tests/
├── integration/            Closed-loop and infrastructure tests
│   └── test_closed_loop_detumbling.py  Full co-simulation test
├── spacecraft/             Model + system tests
├── hardware/               HIL tests (require obsw_sim)
└── unit/ equipment/        Unit + contract tests
```

---

## Roadmap

| Milestone | Status |
|---|---|
| M1–M10 (core platform through closed-loop validation) | ✅ Done |
| M11 - OBC Emulator Integration | ✅ Done |
| M11.5 - KDE Co-Simulation Integration | ✅ Done |
| M12 - Ground Segment (YAMCS, SpW, CAN) | Planned |

---

## License

Apache 2.0 — see [`LICENSE`](LICENSE).

---

*Built by lipofefeyt · Sister projects: [opensvf-kde](https://github.com/lipofefeyt/opensvf-kde) · [openobsw](https://github.com/lipofefeyt/openobsw)* 