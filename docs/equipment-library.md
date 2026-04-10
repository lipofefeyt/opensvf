# SVF Equipment Library

> **Status:** v0.3
> **Last updated:** 2026-04
> **Author:** lipofefeyt

---

## Overview

Every spacecraft model in SVF is an `Equipment` — a Python class with named IN/OUT ports, a `do_step()` physics implementation, and SRDB-canonical parameter names. This document defines the **interface contract** for each reference model.

The contract is stable. If you replace a reference model with a higher-fidelity implementation or a hardware-in-the-loop adapter, only the wiring YAML changes — nothing else.

---

## Equipment Contract Summary

| Equipment | Factory / Class | Subsystem | Bus Interface | Milestone |
|---|---|---|---|---|
| OBC | `ObcEquipment` | DHS | 1553 BC | M7/M8 |
| OBC Stub | `ObcStub` | DHS | — | M10 |
| OBC Emulator | `OBCEmulatorAdapter` | DHS | binary pipe | M11 |
| TTC | `TtcEquipment` | TTC | software | M7 |
| YAMCS Bridge | `YamcsBridge` | GND | TCP | M12 |
| KDE Dynamics | `make_kde_equipment()` | Dynamics | FMI 2.0 | M11.5 |
| Magnetometer | `make_magnetometer()` | AOCS | — | M11.5 |
| Magnetorquer | `make_magnetorquer()` | AOCS | — | M11.5 |
| Gyroscope | `make_gyroscope()` | AOCS | — | M11.5 |
| CSS | `make_css()` | AOCS | — | M11.5 |
| B-dot Controller | `make_bdot_controller()` | AOCS | — | M11.5 |
| Reaction Wheel | `make_reaction_wheel()` | AOCS | 1553 RT | M6/M8 |
| Star Tracker | `make_star_tracker()` | AOCS | SpW/1553 | M8 |
| S-Band Transponder | `make_sbt()` | TTC | UART | M8 |
| PCDU | `make_pcdu()` | EPS | 1553/CAN | M9 |
| EPS FMU | `FmuEquipment(EpsFmu)` | EPS | FMI 3.0 | M4 |

---

## 1. OBC Equipment

**File:** `src/svf/models/obc.py`
**Class:** `ObcEquipment(Equipment)`
**Subsystem:** DHS

### Purpose

Dual role:
1. **PUS TC Router (M7):** Parses PUS-C TC bytes, routes to equipment via CommandStore, generates TM responses.
2. **DHS State Machine (M8):** Mode management, OBT, watchdog, mass memory.

### Configuration

```python
from svf.models.obc import ObcEquipment, ObcConfig, MODE_SAFE

config = ObcConfig(
    apid=0x101,
    param_id_map={
        0x2021: "aocs.rw1.torque_cmd",
        0x2022: "aocs.rw1.speed",
    },
    watchdog_period_s=30.0,
    initial_mode=MODE_SAFE,
)
obc = ObcEquipment(config, sync, store, cmd_store)
```

### Three OBC Implementations

```python
# Level 3 — simulated OBC
obc = ObcEquipment(config, sync, store, cmd_store)

# Level 3/4 — rule-based OBSW simulator
obc = ObcStub(config, sync, store, cmd_store, rules=[
    Rule(
        name="low_battery_safe",
        watch="eps.battery.soc",
        condition=lambda e: e is not None and e.value < 0.3,
        action=lambda cs, t: cs.inject("dhs.obc.mode_cmd", 0.0, t=t),
    ),
])

# Level 4 — real OBSW binary under test
obc = OBCEmulatorAdapter(
    sim_path="obsw_sim",
    sync_protocol=sync,
    store=store,
    command_store=cmd_store,
)
```

All three satisfy `ObcInterface` and are accepted by `TtcEquipment`.

### Ports

| Port | Direction | Description |
|---|---|---|
| `obc.tc_input` | IN | TC arrival signal |
| `dhs.obc.mode_cmd` | IN | Mode command (0=SAFE, 1=NOMINAL, 2=PAYLOAD) |
| `dhs.obc.watchdog_kick` | IN | Watchdog kick |
| `dhs.obc.memory_dump_cmd` | IN | Memory dump trigger |
| `dhs.obc.mode` | OUT | Current mode |
| `dhs.obc.obt` | OUT (s) | On-board time |
| `dhs.obc.watchdog_status` | OUT | 0=nominal, 1=warning, 2=reset |
| `dhs.obc.memory_used_pct` | OUT (%) | Mass memory fill |
| `dhs.obc.health` | OUT | 0=nominal, 1=degraded, 2=failed |
| `dhs.obc.reset_count` | OUT | Reset counter since boot |
| `dhs.obc.cpu_load` | OUT (%) | CPU load |
| `obc.tm_output` | OUT | Latest TM sequence count |

### PUS TC Routing

| Service | Action |
|---|---|
| S1 | TM(1,1) acceptance + TM(1,7) completion; TM(1,2) on bad CRC |
| S3 | TM(3,25) HK each tick for enabled reports |
| S5 | Events on mode transition, watchdog warning/reset |
| S17 | TC(17,1) → TM(17,2) are-you-alive |
| S20/1 | param_id → canonical name → CommandStore.inject() |
| S20/3 | ParameterStore.read() → TM(20,4) |

---

## 2. TTC Equipment

**File:** `src/svf/models/ttc.py`
**Class:** `TtcEquipment(Equipment)`
**Subsystem:** TTC

### Purpose

Software bridge between test procedures, OBC, and optionally YAMCS. Forwards PUS TC bytes to OBC and exposes TM for assertions. With a `YamcsBridge`, TM flows to YAMCS each tick and TC from the YAMCS operator is forwarded to the OBC.

### Instantiation

```python
# Without YAMCS
ttc = TtcEquipment(obc, sync, store, cmd_store)

# With YAMCS ground station
bridge = YamcsBridge(store, tm_port=10015, tc_port=10025)
bridge.start()
ttc = TtcEquipment(obc, sync, store, cmd_store, yamcs_bridge=bridge)
```

### Ports

| Port | Direction | Description |
|---|---|---|
| `ttc.uplink_active` | OUT | 1 when forwarding TC |
| `ttc.downlink_active` | OUT | 1 when OBC has TM(3,25) |

---

## 3. YAMCS Bridge

**File:** `src/svf/yamcs_bridge.py`
**Class:** `YamcsBridge`
**Subsystem:** Ground Segment

### Purpose

TCP bridge between SVF and a YAMCS 5.12.6 ground station. SVF acts as the TCP server; YAMCS connects as a client. Enables an operator to send TC from the YAMCS UI and view live TM parameters.

### Instantiation

```python
from svf.yamcs_bridge import YamcsBridge

bridge = YamcsBridge(store, tm_port=10015, tc_port=10025)
bridge.start()   # blocks waiting for YAMCS to connect
# ... run simulation ...
bridge.stop()
```

### Protocol

```
SVF (TCP server)              YAMCS (TCP client)
  port 10015  ←connects—  TM data link  (SVF pushes PUS TM bytes)
  port 10025  ←connects—  TC data link  (YAMCS sends PUS TC bytes)
```

### API

```python
bridge.send_tm(raw_bytes)   # push PUS TM packet to YAMCS
tc = bridge.get_tc()        # get next TC from YAMCS operator (or None)
```

### XTCE Mission Database

Generated from SRDB automatically on YAMCS start:

```bash
python3 tools/generate_xtce.py > yamcs/mdb/opensvf.xml
```

Contents: 78 parameters, 2 TM containers (`TM_17_2`, `TM_3_25`), 2 commands (`TC_17_1_AreYouAlive`, `TC_20_1_SetParameter`).

---

## 4. KDE Dynamics

**File:** `src/svf/models/kde_equipment.py`
**Factory:** `make_kde_equipment()`
**Subsystem:** Dynamics / AOCS

### Purpose

Wraps the C++ `SpacecraftDynamics` FMU as a `NativeEquipment`. Provides high-fidelity 6-DOF spacecraft dynamics: Euler's equations, quaternion kinematics, Earth B-field model.

### Instantiation

```python
kde = make_kde_equipment(sync, store, cmd_store)
```

Requires `models/fmu/SpacecraftDynamics.fmu`.

### Ports

| Port | Direction | Unit | Description |
|---|---|---|---|
| `aocs.mtq.torque_x/y/z` | IN | Nm | Mechanical torques from MTQ model |
| `aocs.truth.rate_x/y/z` | OUT | rad/s | True angular velocity (→ GYRO) |
| `aocs.mag.true_x/y/z` | OUT | T | True magnetic field (→ MAG) |
| `aocs.attitude.quaternion_w/x/y/z` | OUT | — | True attitude quaternion (→ ST) |

---

## 5. AOCS Sensor Models

### Magnetometer

**Factory:** `make_magnetometer(sync, store, cmd_store, seed=None)`

| Port | Direction | Unit | Description |
|---|---|---|---|
| `aocs.mag.true_x/y/z` | IN | T | True B field from KDE |
| `aocs.mag.field_x/y/z` | OUT | T | Measured B field (with noise) |
| `aocs.mag.status` | OUT | — | 1=nominal |

Physics: Gaussian noise + bias drift random walk.

### Gyroscope

**Factory:** `make_gyroscope(sync, store, cmd_store, seed=None)`

| Port | Direction | Unit | Description |
|---|---|---|---|
| `aocs.truth.rate_x/y/z` | IN | rad/s | True rates from KDE |
| `aocs.gyro.rate_x/y/z` | OUT | rad/s | Measured rates (with noise) |
| `aocs.gyro.status` | OUT | — | 1=nominal |

Physics: Angle random walk (ARW) noise + bias drift.

### CSS

**Factory:** `make_css(sync, store, cmd_store, seed=None)`

| Port | Direction | Unit | Description |
|---|---|---|---|
| `aocs.truth.rate_x/y/z` | IN | rad/s | True rates |
| `aocs.css.sun_x/y/z` | OUT | — | Sun vector estimate |
| `aocs.css.eclipse` | OUT | — | 1=eclipse |

### B-dot Controller

**Factory:** `make_bdot_controller(sync, store, cmd_store)`

| Port | Direction | Unit | Description |
|---|---|---|---|
| `aocs.mag.field_x/y/z` | IN | T | MAG measurement |
| `aocs.mtq.dipole_x/y/z` | OUT | Am² | Dipole commands |

Physics: `m = -k · dB/dt` finite difference.

---

## 6. Magnetorquer

**Factory:** `make_magnetorquer(sync, store, cmd_store)`

| Port | Direction | Unit | Description |
|---|---|---|---|
| `aocs.mtq.dipole_x/y/z` | IN | Am² | Dipole commands |
| `aocs.mtq.b_field_x/y/z` | IN | T | Local B field |
| `aocs.mtq.torque_x/y/z` | OUT | Nm | Torque = m × B |

Physics: Cross product `τ = m × B`. Dipole saturation at ±10 Am².

---

## 7. Reaction Wheel

**Factory:** `make_reaction_wheel()`
**Bus interface:** MIL-STD-1553 RT

| Port | Direction | Unit | Description |
|---|---|---|---|
| `aocs.rw1.torque_cmd` | IN | Nm | Torque command via 1553 SA1 |
| `aocs.rw1.speed` | OUT | rpm | Wheel speed |
| `aocs.rw1.temperature` | OUT | °C | Bearing temperature |
| `aocs.rw1.status` | OUT | — | 1=nominal, 0=over-temp |

---

## 8. Star Tracker

**Factory:** `make_star_tracker()`

| Port | Direction | Unit | Description |
|---|---|---|---|
| `aocs.str1.power_enable` | IN | — | Power on/off |
| `aocs.str1.sun_angle` | IN | deg | Sun angle for blinding |
| `aocs.str1.quaternion_w/x/y/z` | OUT | — | Attitude quaternion |
| `aocs.str1.validity` | OUT | — | 1=valid |
| `aocs.str1.mode` | OUT | — | 0=off, 1=acquiring, 2=tracking |

---

## 9. S-Band Transponder

**Factory:** `make_sbt()`

| Port | Direction | Unit | Description |
|---|---|---|---|
| `ttc.sbt.uplink_signal_level` | IN | dBm | Signal level |
| `ttc.sbt.uplink_lock` | OUT | — | 1=locked |
| `ttc.sbt.rx_bitrate` | OUT | bps | Uplink bit rate |
| `ttc.sbt.tx_bitrate` | OUT | bps | Downlink bit rate |

---

## 10. PCDU

**Factory:** `make_pcdu()`

| Port | Direction | Unit | Description |
|---|---|---|---|
| `eps.solar_array.generated_power` | IN | W | Solar power input |
| `eps.pcdu.lcl{1-8}.enable` | IN | — | Per-LCL enable |
| `eps.pcdu.total_load` | OUT | W | Total load |
| `eps.pcdu.uvlo_active` | OUT | — | 1=UVLO active |

---

## 11. EPS FMU

**File:** `models/EpsFmu.fmu` — FMI 3.0 FMU

| Port | Direction | Unit |
|---|---|---|
| `eps.solar_array.illumination` | IN | 0–1 |
| `eps.battery.soc` | OUT | 0.05–1.0 |
| `eps.battery.voltage` | OUT | V |
| `eps.solar_array.generated_power` | OUT | W |

---

## Adding a New Equipment Model

### 1. Define SRDB entries
### 2. Define requirements
### 3. Implement

```python
def make_my_equipment(sync, store, cmd_store):
    def _step(eq, t, dt):
        rate = eq.read_port("aocs.myeq.rate_cmd")
        speed = eq.read_port("aocs.myeq.speed")
        eq.write_port("aocs.myeq.speed", speed + rate * dt)

    return NativeEquipment(
        equipment_id="myeq",
        ports=[
            PortDefinition("aocs.myeq.rate_cmd", PortDirection.IN,  unit="rpm/s"),
            PortDefinition("aocs.myeq.speed",    PortDirection.OUT, unit="rpm"),
        ],
        step_fn=_step,
        sync_protocol=sync, store=store, command_store=cmd_store,
    )
```

### Scalability contract

- **SRDB canonical names are stable.** Replace the model → only wiring YAML changes.
- **InterfaceType validates connections.** Type mismatch caught at load time.
- **Port commands are consumed.** One-shot commands don't persist across ticks.