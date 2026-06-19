# SVF Equipment Library

> **Status:** v0.5
> **Last updated:** 2026-05
> **Author:** lipofefeyt

---

## Overview

Every spacecraft model in SVF is an `Equipment`  -  a Python class with named IN/OUT ports, a `do_step()` physics implementation, and SRDB-canonical parameter names. This document defines the **interface contract** for each reference model.

The contract is stable. If you replace a reference model with a higher-fidelity implementation or a hardware-in-the-loop adapter, only the wiring YAML changes  -  nothing else.

---

## Fidelity Levels

All SVF equipment models declare a fidelity level. The level determines what the model is validated against and what test plan is appropriate.

| Level | Name | Definition | Validated Against |
|---|---|---|---|
| **F1** | Functional | Correct port names and directions; trivial or stub physics (fixed values, pass-through). Used for wiring tests and OBC integration. | Port contract only |
| **F2** | Behavioural | Correct dynamics structure  -  noise, bias, saturation, parametric hardware profiles. Sufficient for OBSW algorithm testing. | Domain physics knowledge |
| **F3** | High-fidelity | Detailed physical modelling  -  nonlinear effects, thermal coupling, dynamic power budgets. Appropriate for mission performance analysis. | Flight heritage data or simulation benchmark |
| **F4** | Validated | Parameters derived from acceptance test measurements or hardware-in-the-loop runs. Suitable for qualification evidence. | Hardware test data |

All reference models currently ship at **F2**. F3/F4 models are supplied by the mission team or via HIL adapters.

---

## Equipment Contract Summary

| Equipment | Factory / Class | Subsystem | Bus Interface | Fidelity | Milestone |
|---|---|---|---|---|---|
| OBC | `ObcEquipment` | DHS | 1553 BC | F2 | M7/M8 |
| OBC Stub | `ObcStub` | DHS |  -  | F1 | M10 |
| OBC Emulator | `OBCEmulatorAdapter` | DHS | binary pipe | F4 | M11 |
| TTC | `TtcEquipment` | TTC | software | F2 | M7 |
| YAMCS Bridge | `YamcsBridge` | GND | TCP | F2 | M12 |
| KDE Dynamics | `make_kde_equipment()` | Dynamics | FMI 2.0 | F3 | M11.5 |
| Magnetometer | `make_magnetometer()` | AOCS |  -  | F2 | M11.5 |
| Magnetorquer | `make_magnetorquer()` | AOCS |  -  | F2 | M11.5 |
| Gyroscope | `make_gyroscope()` | AOCS |  -  | F2 | M11.5 |
| CSS | `make_css()` | AOCS |  -  | F2 | M11.5 |
| B-dot Controller | `make_bdot_controller()` | AOCS |  -  | F2 | M11.5 |
| Reaction Wheel | `make_reaction_wheel()` | AOCS | 1553 RT | F2 | M6/M8 |
| Star Tracker | `make_star_tracker()` | AOCS | SpW/1553 | F2 | M8 |
| Thruster | `make_thruster()` | AOCS/Prop | discrete | F2 | M17 |
| GPS Receiver | `make_gps()` | NAV | UART/SPI | F2 | M17 |
| Thermal Model | `make_thermal()` | THM |  -  | F2 | M17 |
| Solar Array | `make_solar_array()` | EPS |  -  | F2 | M26 |
| Battery | `make_battery()` | EPS |  -  | F2 | M26 |
| PCDU | `make_pcdu()` | EPS | 1553/CAN | F2 | M9 |

> **EPS FMU** (`FmuEquipment(EpsFmu)`) was removed in M26. EPS is now fully covered by `make_solar_array()`, `make_battery()`, and `make_pcdu()`.

### F3/F4 upgrade paths

| Equipment | What F3 needs | What F4 needs |
|---|---|---|
| KDE Dynamics | Already F3 via FMI (6-DOF rigid body) | IMU mounting misalignment + flex modes from modal test |
| Reaction Wheel | Speed-dependent friction model | Measured friction curve from bearing test |
| Battery | Electro-chemical (e.g. SPKF) model | Discharge curves from acceptance test |
| Thermal Model | Multi-node radiative coupling (Gebhart) | MLI effective emittance from thermal vacuum test |
| GPS Receiver | Ionospheric/tropospheric delay model | Measured position noise from sky test |

### Promoting a model from F2 to F3 with CalibrationCurve (M31)

The SRDB supports polynomial and piecewise-linear calibration curves on TM
parameters. Adding a `CalibrationCurve` to a parameter signals that raw ADC
counts are converted to engineering units before being written to
`ParameterStore`.

```yaml
# srdb/baseline/aocs_sensors.yaml
parameters:
  mag.field_x:
    description: "Magnetometer X field"
    unit: T
    dtype: float
    classification: TM
    domain: AOCS
    model_id: mag
    calibration:
      type: polynomial
      coefficients: [0.0, 4.882813e-7]   # raw counts → Tesla (16-bit ADC, ±16 Gauss)
```

`checkcov` detects inconsistencies: if a model is listed as F2 in
`EQUIPMENT_FIDELITY` but its SRDB parameters have `CalibrationCurve` entries,
the tool reports an `INCONSISTENCY` error and exits 1. Update the fidelity
level in `tools/check_coverage.py` when you add calibration data.

---

## Port Name Convention

All AOCS sensor and actuator ports follow the pattern:

```
aocs.<equipment_id>.<signal>
```

The `equipment_id` is the instance name passed to the factory (e.g. `"rw1"`, `"rw2"`, `"str_front"`). This lets you instantiate the same model type multiple times without port collisions.

**Exception  -  shared truth ports:** `aocs.truth.rate_x/y/z` are written by the KDE dynamics model and shared by all sensors. They use a fixed prefix because there is only one dynamics model per simulation.

**Exception  -  GPS:** GPS ports use `<equipment_id>.<signal>` (no `aocs.` prefix) to match the NAV subsystem naming convention.

---

## Hardware Profile Support

All `make_*` AOCS factories accept `equipment_id`, `hardware_profile`, and `hardware_dir` parameters:

```python
# Use built-in defaults, default id
rw = make_reaction_wheel(sync, store, cmd_store)

# Named instance  -  ports become aocs.rw_pitch.*
rw = make_reaction_wheel(sync, store, cmd_store,
                         equipment_id="rw_pitch")

# Load physics constants from a hardware profile
rw = make_reaction_wheel(sync, store, cmd_store,
                         equipment_id="rw_pitch",
                         hardware_profile="rw_sinclair_rw003",
                         hardware_dir="mission_mysat1/hardware_profiles")
```

Profiles live in `mission_mysat1/hardware_profiles/`. If `hardware_dir` is omitted, the loader searches the built-in profile path.

Available profiles:

| Profile | Type | Key Parameters |
|---|---|---|
| `rw_default` | reaction_wheel | 6000 rpm, 0.2 Nm |
| `rw_sinclair_rw003` | reaction_wheel | 5000 rpm, 30 mNm |
| `mtq_default` | magnetorquer | 10 Am², 5 Ω |
| `mag_default` | magnetometer | 1×10⁻⁷ T noise |
| `gyro_default` | gyroscope | ARW 1×10⁻⁴ rad/s/√Hz |
| `str_default` | star_tracker | 30° sun exclusion, 10 s acquisition |
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
| `aocs.truth.rate_x/y/z` | OUT | rad/s | True angular velocity → GYRO, CSS |
| `aocs.mag.true_x/y/z` | OUT | T | True B-field → MAG |
| `aocs.attitude.quaternion_w/x/y/z` | OUT |  -  | True attitude → ST |

---

## 4. AOCS Sensor Models

### Magnetometer

```python
make_magnetometer(sync, store, cmd_store,
                  equipment_id="mag", seed=None,
                  hardware_profile=None, hardware_dir=None)
```

| Port | Direction | Unit | Description |
|---|---|---|---|
| `aocs.<id>.power_enable` | IN |  -  | Power on/off |
| `aocs.<id>.true_x/y/z` | IN | T | True B-field from truth model |
| `aocs.<id>.field_x/y/z` | OUT | T | Measured field (noise + bias drift) |
| `aocs.<id>.status` | OUT |  -  | 0=off, 1=nominal |

### Gyroscope

```python
make_gyroscope(sync, store, cmd_store,
               equipment_id="gyro", seed=None,
               hardware_profile=None, hardware_dir=None)
```

| Port | Direction | Unit | Description |
|---|---|---|---|
| `aocs.<id>.power_enable` | IN |  -  | Power on/off |
| `aocs.truth.rate_x/y/z` | IN | rad/s | True angular rate (shared truth port) |
| `aocs.<id>.rate_x/y/z` | OUT | rad/s | Measured rate (noise + ARW + bias) |
| `aocs.<id>.status` | OUT |  -  | 0=off, 1=nominal |

### Coarse Sun Sensor (CSS)

```python
make_css(sync, store, cmd_store,
         equipment_id="css", seed=None,
         hardware_profile=None, hardware_dir=None)
```

| Port | Direction | Unit | Description |
|---|---|---|---|
| `aocs.<id>.power_enable` | IN |  -  | Power on/off |
| `aocs.truth.rate_x/y/z` | IN | rad/s | True angular rate (shared truth port) |
| `aocs.<id>.sun_x/y/z` | OUT |  -  | Estimated sun unit vector |
| `aocs.<id>.eclipse` | OUT |  -  | 1=eclipse |
| `aocs.<id>.status` | OUT |  -  | 0=off, 1=nominal, 2=eclipse |

### B-dot Controller (validation oracle)

```python
make_bdot_controller(sync, store, cmd_store,
                     equipment_id="bdot",
                     gain=1e4, max_dipole=10.0,
                     mag_id="mag", mtq_id="mtq")
```

**Note:** This is a Python validation oracle  -  not flight code. The flight b-dot runs in `openobsw`.

`mag_id` and `mtq_id` select which magnetometer and magnetorquer instance to read/command. Port prefixes resolve to `aocs.<mag_id>.field_*` and `aocs.<mtq_id>.dipole_*`.

| Port | Direction | Unit | Description |
|---|---|---|---|
| `aocs.<id>.enable` | IN |  -  | Enable control (0=off, 1=on) |
| `aocs.<mag_id>.field_x/y/z` | IN | T | MAG measurement |
| `aocs.<mtq_id>.dipole_x/y/z` | OUT | Am² | MTQ dipole commands |
| `aocs.<id>.bdot_x/y/z` | OUT | T/s | Estimated B-dot (telemetry) |
| `aocs.<id>.active` | OUT |  -  | 1=controller active |

---

## 5. Magnetorquer

```python
make_magnetorquer(sync, store, cmd_store,
                  equipment_id="mtq",
                  hardware_profile=None, hardware_dir=None)
```

| Port | Direction | Unit | Description |
|---|---|---|---|
| `aocs.<id>.power_enable` | IN |  -  | Power on/off |
| `aocs.<id>.dipole_x/y/z` | IN | Am² | Dipole commands |
| `aocs.<id>.b_field_x/y/z` | IN | T | Local B-field for torque calculation |
| `aocs.<id>.torque_x/y/z` | OUT | Nm | Torque = m × B |
| `aocs.<id>.status` | OUT |  -  | 0=off, 1=nominal |
| `aocs.<id>.power_w` | OUT | W | Power consumption |

---

## 6. Reaction Wheel

```python
make_reaction_wheel(sync, store, cmd_store,
                    equipment_id="rw1",
                    hardware_profile=None, hardware_dir=None)
```

| Port | Direction | Unit | Description |
|---|---|---|---|
| `aocs.<id>.torque_cmd` | IN | Nm | Torque command |
| `aocs.<id>.speed` | OUT | rpm | Wheel speed |
| `aocs.<id>.temperature` | OUT | °C | Bearing temperature |
| `aocs.<id>.status` | OUT |  -  | 0=off, 1=nominal, 2=over-temp |

Multiple wheels: pass different `equipment_id` values (`"rw_x"`, `"rw_y"`, `"rw_z"`, `"rw_skew"`).

---

## 7. Star Tracker

```python
make_star_tracker(sync, store, cmd_store,
                  equipment_id="str1", seed=None,
                  hardware_profile=None, hardware_dir=None)
```

| Port | Direction | Unit | Description |
|---|---|---|---|
| `aocs.<id>.power_enable` | IN |  -  | Power on/off |
| `aocs.<id>.sun_angle` | IN | deg | Sun angle for blinding check |
| `aocs.<id>.quaternion_w/x/y/z` | OUT |  -  | Attitude quaternion (noise added) |
| `aocs.<id>.validity` | OUT |  -  | 1=valid measurement |
| `aocs.<id>.mode` | OUT |  -  | 0=off, 1=acquiring, 2=tracking |

---

## 8. Thruster

```python
make_thruster(sync, store, cmd_store,
              equipment_id="thr1",
              hardware_profile=None, hardware_dir=None)
```

Physics: propellant consumption via rocket equation (Δm = F / (Isp × g₀) × dt).

| Port | Direction | Unit | Description |
|---|---|---|---|
| `aocs.<id>.enable` | IN |  -  | Fire command (1=fire) |
| `aocs.<id>.thrust_cmd` | IN | N | Commanded thrust |
| `aocs.<id>.thrust` | OUT | N | Actual thrust |
| `aocs.<id>.temperature` | OUT | °C | Thruster temperature |
| `aocs.<id>.propellant` | OUT | kg | Remaining propellant mass |
| `aocs.<id>.status` | OUT |  -  | 0=off 1=nominal 2=low_prop 3=empty 4=over_temp |

Status codes are exported as `STATUS_OFF`, `STATUS_NOMINAL`, `STATUS_LOW_PROP`, `STATUS_EMPTY`, `STATUS_OVER_TEMP` from `svf.models.aocs.thruster`.

---

## 9. GPS Receiver

```python
make_gps(sync, store, cmd_store,
         equipment_id="gps", seed=None,
         hardware_profile=None, hardware_dir=None)
```

Truth state from KDE (position/velocity). Gaussian noise added per axis. GPS ports use `<equipment_id>.<signal>` (no `aocs.` prefix).

| Port | Direction | Unit | Description |
|---|---|---|---|
| `<id>.power_enable` | IN |  -  | Power on/off |
| `<id>.truth.pos_x/y/z` | IN | m | True ECI position from KDE |
| `<id>.truth.vel_x/y/z` | IN | m/s | True ECI velocity from KDE |
| `<id>.eclipse` | IN |  -  | Eclipse flag from CSS |
| `<id>.position_x/y/z` | OUT | m | Measured ECI position |
| `<id>.velocity_x/y/z` | OUT | m/s | Measured ECI velocity |
| `<id>.fix` | OUT |  -  | 1=valid fix |
| `<id>.altitude_km` | OUT | km | Altitude above sphere |
| `<id>.status` | OUT |  -  | 0=off 1=acquiring 2=fix 3=eclipse_outage |

Status codes exported as `STATUS_OFF`, `STATUS_ACQUIRING`, `STATUS_FIX`, `STATUS_ECLIPSE_OUTAGE` from `svf.models.aocs.gps`.

---

## 10. Thermal Model

`make_thermal(sync, store, cmd_store, hardware_profile=None)`

N-node configurable thermal network. Node count and properties from hardware profile.

| Port | Direction | Unit | Description |
|---|---|---|---|
| `thermal.solar_illumination` | IN |  -  | 0=eclipse, 1=sun |
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
| `ttc.sbt.uplink_lock` | OUT |  -  | 1=locked |
| `ttc.sbt.rx_bitrate` | OUT | bps | Uplink bit rate |
| `ttc.sbt.tx_bitrate` | OUT | bps | Downlink bit rate |

---

## 12. PCDU

`make_pcdu(sync, store, cmd_store)`

| Port | Direction | Unit | Description |
|---|---|---|---|
| `eps.solar_array.generated_power` | IN | W | Solar power |
| `eps.pcdu.lcl{1-8}.enable` | IN |  -  | Per-LCL enable |
| `eps.pcdu.total_load` | OUT | W | Total load |
| `eps.pcdu.uvlo_active` | OUT |  -  | 1=UVLO active |

---

## Adding a New Equipment Model

```python
def make_my_sensor(sync, store, cmd_store,
                   equipment_id="mysensor",
                   hardware_profile=None, hardware_dir=None):
    # Physics constants as factory locals (not module globals)
    noise_std = 0.01

    if hardware_profile is not None:
        from svf.config.hardware_profile import load_hardware_profile
        p = load_hardware_profile(hardware_profile, hardware_dir)
        noise_std = p.get("noise_std", noise_std)

    _pfx = f"aocs.{equipment_id}"

    def _step(eq, t, dt):
        val = eq.read_port(f"{_pfx}.input")
        eq.write_port(f"{_pfx}.output", val + rng.gauss(0, noise_std))

    return NativeEquipment(
        equipment_id=equipment_id,
        ports=[
            PortDefinition(f"{_pfx}.input",  PortDirection.IN),
            PortDefinition(f"{_pfx}.output", PortDirection.OUT),
        ],
        step_fn=_step,
        sync_protocol=sync, store=store, command_store=cmd_store,
    )
```

Key rules:
- Define `_step` **inside** the factory so physics constants are captured as closure variables. Module-level step functions break multi-instance support.
- Use `_pfx = f"aocs.{equipment_id}"` for all port names. Hard-coding equipment names in port strings prevents running two instances simultaneously.
- Load profile values with `p.get("key", local_default)` and assign back to the local constant. Calling `load_hardware_profile` without using the result is a silent no-op bug.

Add a hardware profile in `mission_mysat1/hardware_profiles/mysensor_default.yaml` and declare the equipment in `spacecraft.yaml`.
