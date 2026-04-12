# SVF Equipment Library

> **Status:** v0.4
> **Last updated:** 2026-04
> **Author:** lipofefeyt

---

## Overview

Every spacecraft model in SVF is an `Equipment` — a Python class with named IN/OUT ports, a `do_step()` physics implementation, and SRDB-canonical parameter names. This document defines the **interface contract** for each reference model.

The contract is stable. If you replace a reference model with a higher-fidelity implementation or a hardware-in-the-loop adapter, only the wiring YAML changes — nothing else.

All `make_*` factories accept an optional `hardware_profile=` parameter to load physics constants from a SRDB hardware YAML profile rather than using built-in defaults.

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
| Thruster | `make_thruster()` | AOCS/Prop | discrete | M17 |
| GPS Receiver | `make_gps()` | NAV | UART/SPI | M17 |
| Thermal Model | `make_thermal()` | THM | — | M17 |
| S-Band Transponder | `make_sbt()` | TTC | UART | M8 |
| PCDU | `make_pcdu()` | EPS | 1553/CAN | M9 |
| EPS FMU | `FmuEquipment(EpsFmu)` | EPS | FMI 3.0 | M4 |

---

## Hardware Profile Support

All `make_*` factories accept an optional `hardware_profile=` parameter:

```python
# Use built-in defaults
rw = make_reaction_wheel(sync, store, cmd_store)

# Load from SRDB hardware profile
rw = make_reaction_wheel(sync, store, cmd_store,
                         hardware_profile="rw_sinclair_rw003")
```

Profiles live in `srdb/data/hardware/*.yaml`. Falls back to defaults if `obsw-srdb` package not installed.

Available profiles:

| Profile | Type | Key Parameters |
|---|---|---|
| `rw_default` | reaction_wheel | 6000 rpm, 0.2 Nm |
| `rw_sinclair_rw003` | reaction_wheel | 5000 rpm, 30 mNm |
| `mtq_default` | magnetorquer | 10 Am², 5 Ω |
| `mag_default` | magnetometer | 1×10⁻⁷ T noise |
| `gyro_default` | gyroscope | ARW 1×10⁻⁴ rad/s/√Hz |
| `thr_default` | thruster | 1 N, Isp=70s (cold gas) |
| `thr_moog_monarc_1` | thruster | 1 N, Isp=220s (hydrazine) |
| `gps_default` | gps | 5 m position noise |
| `gps_novatel_oem7` | gps | 1.5 m position noise |
| `thermal_default` | thermal_node | 3-node (panels + internal) |

---

## 1. OBC Equipment

**File:** `src/svf/models/obc.py` / `obc_stub.py` / `obc_emulator.py`

Three drop-in implementations via `ObcInterface`:

```python
# Simulated OBC
obc = ObcEquipment(config, sync, store, cmd_store)

# Rule-based OBSW simulator
obc = ObcStub(config, sync, store, cmd_store, rules=[...])

# Real OBSW binary under test
obc = OBCEmulatorAdapter(sim_path="obsw_sim", ...)
```

SRDB version handshake: `OBCEmulatorAdapter` reads SRDB version from `obsw_sim` stderr at startup and compares against installed `obsw-srdb` package. Logs WARNING on mismatch.

### Ports

| Port | Direction | Description |
|---|---|---|
| `dhs.obc.mode_cmd` | IN | Mode command (0=SAFE, 1=NOMINAL) |
| `dhs.obc.mode` | OUT | Current FSM mode |
| `dhs.obc.obt` | OUT (s) | On-board time |
| `dhs.obc.watchdog_status` | OUT | 0=nominal, 1=warning, 2=reset |
| `dhs.obc.health` | OUT | 0=nominal, 1=degraded, 2=failed |

---

## 2. TTC Equipment + YAMCS Bridge

**File:** `src/svf/models/ttc.py`, `src/svf/yamcs_bridge.py`

```python
# Without YAMCS
ttc = TtcEquipment(obc, sync, store, cmd_store)

# With YAMCS ground station
bridge = YamcsBridge(store)
bridge.start()
ttc = TtcEquipment(obc, sync, store, cmd_store, yamcs_bridge=bridge)
```

---

## 3. KDE Dynamics

**File:** `src/svf/models/kde_equipment.py`

6-DOF spacecraft physics via FMI 2.0 FMU. Provides truth state to all sensor models.

| Port | Direction | Unit | Description |
|---|---|---|---|
| `aocs.mtq.torque_x/y/z` | IN | Nm | MTQ torques |
| `aocs.truth.rate_x/y/z` | OUT | rad/s | True angular velocity → GYRO |
| `aocs.mag.true_x/y/z` | OUT | T | True B-field → MAG |
| `aocs.attitude.quaternion_w/x/y/z` | OUT | — | True attitude → ST |

---

## 4. AOCS Sensor Models

### Magnetometer
`make_magnetometer(sync, store, cmd_store, seed=None, hardware_profile=None)`

| Port | Direction | Unit |
|---|---|---|
| `aocs.mag.true_x/y/z` | IN | T |
| `aocs.mag.field_x/y/z` | OUT | T |
| `aocs.mag.status` | OUT | — |

### Gyroscope
`make_gyroscope(sync, store, cmd_store, seed=None, hardware_profile=None)`

| Port | Direction | Unit |
|---|---|---|
| `aocs.truth.rate_x/y/z` | IN | rad/s |
| `aocs.gyro.rate_x/y/z` | OUT | rad/s |
| `aocs.gyro.status` | OUT | — |

### CSS
`make_css(sync, store, cmd_store, seed=None)`

| Port | Direction | Description |
|---|---|---|
| `aocs.truth.rate_x/y/z` | IN | True rates |
| `aocs.css.sun_x/y/z` | OUT | Sun vector |
| `aocs.css.eclipse` | OUT | 1=eclipse |

### B-dot Controller (validation oracle)
`make_bdot_controller(sync, store, cmd_store)`

**Note:** This is a Python validation oracle — not flight code. The flight b-dot runs in `openobsw`.

| Port | Direction | Unit |
|---|---|---|
| `aocs.mag.field_x/y/z` | IN | T |
| `aocs.mtq.dipole_x/y/z` | OUT | Am² |

---

## 5. Magnetorquer

`make_magnetorquer(sync, store, cmd_store, hardware_profile=None)`

| Port | Direction | Unit | Description |
|---|---|---|---|
| `aocs.mtq.dipole_x/y/z` | IN | Am² | Dipole commands |
| `aocs.mtq.b_field_x/y/z` | IN | T | Local B-field |
| `aocs.mtq.torque_x/y/z` | OUT | Nm | Torque = m × B |

---

## 6. Reaction Wheel

`make_reaction_wheel(sync, store, cmd_store, hardware_profile=None)`

| Port | Direction | Unit | Description |
|---|---|---|---|
| `aocs.rw1.torque_cmd` | IN | Nm | Torque command |
| `aocs.rw1.speed` | OUT | rpm | Wheel speed |
| `aocs.rw1.temperature` | OUT | °C | Bearing temperature |
| `aocs.rw1.status` | OUT | — | 1=nominal, 0=over-temp |

---

## 7. Star Tracker

`make_star_tracker(sync, store, cmd_store, seed=None)`

| Port | Direction | Description |
|---|---|---|
| `aocs.str1.power_enable` | IN | Power on/off |
| `aocs.str1.sun_angle` | IN | Sun angle for blinding |
| `aocs.str1.quaternion_w/x/y/z` | OUT | Attitude quaternion |
| `aocs.str1.validity` | OUT | 1=valid |
| `aocs.str1.mode` | OUT | 0=off, 1=acquiring, 2=tracking |

---

## 8. Thruster

`make_thruster(sync, store, cmd_store, hardware_profile=None)`

Physics: propellant consumption via Tsiolkovsky equation.

| Port | Direction | Unit | Description |
|---|---|---|---|
| `aocs.thr1.enable` | IN | — | Fire command |
| `aocs.thr1.thrust_cmd` | IN | N | Commanded thrust |
| `aocs.thr1.thrust` | OUT | N | Actual thrust |
| `aocs.thr1.temperature` | OUT | °C | Thruster temperature |
| `aocs.thr1.propellant` | OUT | kg | Remaining propellant |
| `aocs.thr1.status` | OUT | — | 0=off 1=nominal 2=low_prop 3=empty 4=over_temp |

---

## 9. GPS Receiver

`make_gps(sync, store, cmd_store, seed=None, hardware_profile=None)`

Truth state from KDE (position/velocity). Gaussian noise added per axis.

| Port | Direction | Unit | Description |
|---|---|---|---|
| `gps.power_enable` | IN | — | Power on/off |
| `gps.truth.pos_x/y/z` | IN | m | True ECI position from KDE |
| `gps.truth.vel_x/y/z` | IN | m/s | True ECI velocity from KDE |
| `gps.eclipse` | IN | — | Eclipse flag from CSS |
| `gps.position_x/y/z` | OUT | m | Measured ECI position |
| `gps.velocity_x/y/z` | OUT | m/s | Measured ECI velocity |
| `gps.fix` | OUT | — | 1=valid fix |
| `gps.altitude_km` | OUT | km | Altitude above sphere |
| `gps.status` | OUT | — | 0=off 1=acquiring 2=fix 3=eclipse_outage |

---

## 10. Thermal Model

`make_thermal(sync, store, cmd_store, hardware_profile=None)`

N-node configurable thermal network. Node count and properties from hardware profile.

| Port | Direction | Unit | Description |
|---|---|---|---|
| `thermal.solar_illumination` | IN | — | 0=eclipse, 1=sun |
| `thermal.equipment_power_w` | IN | W | Equipment dissipation |
| `thermal.{node_id}.temp_degc` | OUT | °C | Per-node temperature |
| `thermal.cavity.temp_degc` | OUT | °C | Internal cavity temperature |
| `thermal.min_temp_degc` | OUT | °C | Coldest node |
| `thermal.max_temp_degc` | OUT | °C | Hottest node |

Default 3 nodes: `panel_plus_x`, `panel_minus_x`, `internal`.

---

## 11. S-Band Transponder

`make_sbt(sync, store, cmd_store)`

| Port | Direction | Unit | Description |
|---|---|---|---|
| `ttc.sbt.uplink_signal_level` | IN | dBm | Signal level |
| `ttc.sbt.uplink_lock` | OUT | — | 1=locked |
| `ttc.sbt.rx_bitrate` | OUT | bps | Uplink bit rate |
| `ttc.sbt.tx_bitrate` | OUT | bps | Downlink bit rate |

---

## 12. PCDU

`make_pcdu(sync, store, cmd_store)`

| Port | Direction | Unit | Description |
|---|---|---|---|
| `eps.solar_array.generated_power` | IN | W | Solar power |
| `eps.pcdu.lcl{1-8}.enable` | IN | — | Per-LCL enable |
| `eps.pcdu.total_load` | OUT | W | Total load |
| `eps.pcdu.uvlo_active` | OUT | — | 1=UVLO active |

---

## 13. EPS FMU

`FmuEquipment(EpsFmu)` — FMI 3.0 FMU

| Port | Direction | Unit |
|---|---|---|
| `eps.solar_array.illumination` | IN | 0–1 |
| `eps.battery.soc` | OUT | 0.05–1.0 |
| `eps.battery.voltage` | OUT | V |
| `eps.solar_array.generated_power` | OUT | W |

---

## Adding a New Equipment Model

```python
def make_my_equipment(sync, store, cmd_store, hardware_profile=None):
    def _step(eq, t, dt):
        val = eq.read_port("myeq.input")
        eq.write_port("myeq.output", val * 2.0)

    return NativeEquipment(
        equipment_id="myeq",
        ports=[
            PortDefinition("myeq.input",  PortDirection.IN),
            PortDefinition("myeq.output", PortDirection.OUT),
        ],
        step_fn=_step,
        sync_protocol=sync, store=store, command_store=cmd_store,
    )
```

Add a hardware profile in `srdb/data/hardware/myeq_default.yaml` and pass `hardware_profile="myeq_default"` to load parameters from it.