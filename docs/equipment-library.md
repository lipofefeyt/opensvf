# SVF Equipment Library

> **Status:** v0.2
> **Last updated:** 2026-03
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
| TTC | `TtcEquipment` | TTC | software | M7 |
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
from svf.pus.services import HkReportDefinition

config = ObcConfig(
    apid=0x101,
    param_id_map={
        0x2021: "aocs.rw1.torque_cmd",
        0x2022: "aocs.rw1.speed",
    },
    essential_hk=[
        HkReportDefinition(
            report_id=1,
            parameter_names=["aocs.rw1.speed", "eps.battery.soc"],
            period_s=1.0,
        )
    ],
    watchdog_period_s=30.0,
    initial_mode=MODE_SAFE,
)
obc = ObcEquipment(config, sync, store, cmd_store)
```

### Ports

| Port | Direction | Description |
|---|---|---|
| `obc.tc_input` | IN | TC arrival signal |
| `dhs.obc.mode_cmd` | IN | Mode command (0=SAFE, 1=NOMINAL, 2=PAYLOAD) — consumed |
| `dhs.obc.watchdog_kick` | IN | Watchdog kick (write 1) — consumed |
| `dhs.obc.memory_dump_cmd` | IN | Memory dump (write 1) — consumed |
| `dhs.obc.mode` | OUT | Current mode |
| `dhs.obc.obt` | OUT (s) | On-board time |
| `dhs.obc.watchdog_status` | OUT | 0=nominal, 1=warning, 2=reset |
| `dhs.obc.memory_used_pct` | OUT (%) | Mass memory fill |
| `dhs.obc.health` | OUT | 0=nominal, 1=degraded, 2=failed |
| `dhs.obc.reset_count` | OUT | Reset counter since boot |
| `dhs.obc.cpu_load` | OUT (%) | CPU load |
| `obc.tm_output` | OUT | Latest TM sequence count |

### Mode Constants

```python
MODE_SAFE    = 0   # Low power, minimal services
MODE_NOMINAL = 1   # Full platform services
MODE_PAYLOAD = 2   # Payload ops, 5× memory fill rate
```

### Physics

**Mode transitions:** `dhs.obc.mode_cmd` → mode change → TM(5,1) event. Command consumed after processing.

**OBT:** Incremented by `dt` each tick.

**Watchdog:** After `watchdog_period_s` without kick → TM(5,2) WARNING. After 2× period → TM(5,4) RESET + mode forced to SAFE.

**Memory:** Fills at 0.01%/s (SAFE/NOMINAL) or 0.05%/s (PAYLOAD). Health → DEGRADED at >90%.

### PUS TC Routing

| Service | Action |
|---|---|
| S1 | TM(1,1) acceptance + TM(1,7) completion for all TCs; TM(1,2) on bad CRC |
| S3 | TM(3,25) HK each tick for enabled reports |
| S5 | Events on mode transition, watchdog warning/reset |
| S17 | TC(17,1) → TM(17,2) are-you-alive |
| S20/1 | param_id → canonical name → CommandStore.inject() |
| S20/3 | ParameterStore.read() → TM(20,4) |

### Test Interface

```python
responses = obc.receive_tc(raw_bytes, t=0.0)
tm_list   = obc.get_tm_queue()
tm_s3     = obc.get_tm_by_service(3, 25)

assert obc.mode == MODE_NOMINAL
assert obc.watchdog_status == WDG_NOMINAL
assert obc.memory_used_pct < 90.0
```

---

## 2. TTC Equipment

**File:** `src/svf/models/ttc.py`  
**Class:** `TtcEquipment(Equipment)`  
**Subsystem:** TTC

### Purpose

Software bridge between test procedures and OBC. Forwards PUS TC bytes to OBC and exposes TM for assertions.

### Instantiation

```python
ttc = TtcEquipment(obc, sync, store, cmd_store)
```

### Ports

| Port | Direction | Description |
|---|---|---|
| `ttc.uplink_active` | OUT | 1 when forwarding TC |
| `ttc.downlink_active` | OUT | 1 when OBC has TM(3,25) |

### Test Interface

```python
ttc.send_tc(PusTcPacket(service=17, subservice=1, ...))
ttc.do_step(t=0.0, dt=0.1)
responses = ttc.get_tm_responses(service=17, subservice=2)
```

---

## 3. Reaction Wheel

**File:** `src/svf/models/reaction_wheel.py`  
**Factory:** `make_reaction_wheel()`  
**Subsystem:** AOCS  
**Bus interface:** MIL-STD-1553 RT (RT5 in reference wiring)

### Instantiation

```python
rw = make_reaction_wheel(sync, store, cmd_store)
```

### Ports

| Port | Direction | Unit | Range | Description |
|---|---|---|---|---|
| `aocs.rw1.torque_cmd` | IN | Nm | ±0.2 | Torque command via 1553 SA1 |
| `aocs.rw1.speed` | OUT | rpm | ±6000 | Wheel speed |
| `aocs.rw1.temperature` | OUT | °C | -40…85 | Bearing temperature |
| `aocs.rw1.status` | OUT | — | 0/1 | 1=nominal, 0=over-temp |

### Physics

```
acceleration = torque × 100 rpm/s/Nm
coulomb_friction = ±0.5 rpm/s (opposing)
viscous_friction = -0.002 × speed rpm/s
new_speed = clamp(speed + (accel + friction) × dt, ±6000)

temp_rise = 0.001 × speed² × dt
temp_cool = 0.05 × (temp - ambient) × dt

over-temp (>80°C): status=0, effective_torque × 0.5
status evaluated on INPUT temperature (before cooling)
```

### 1553 Subaddress Mapping

| SA | Direction | Parameter |
|---|---|---|
| 1 | BC→RT | `aocs.rw1.torque_cmd` |
| 2 | RT→BC | `aocs.rw1.speed` |

---

## 4. Star Tracker

**File:** `src/svf/models/star_tracker.py`  
**Factory:** `make_star_tracker()`  
**Subsystem:** AOCS  
**Bus interface:** SpaceWire (primary), MIL-STD-1553 RT (secondary)

### Instantiation

```python
st = make_star_tracker(
    sync, store, cmd_store,
    initial_quaternion=(1.0, 0.0, 0.0, 0.0),
    body_rate_rad_s=(0.0, 0.001, 0.0),
    seed=42,
)
```

### Ports

| Port | Direction | Unit | Description |
|---|---|---|---|
| `aocs.str1.power_enable` | IN | — | Power on/off |
| `aocs.str1.sun_angle` | IN | deg | Sun angle for blinding |
| `aocs.str1.quaternion_w/x/y/z` | OUT | — | Attitude quaternion |
| `aocs.str1.validity` | OUT | — | 1=valid, 0=invalid |
| `aocs.str1.mode` | OUT | — | 0=off, 1=acquiring, 2=tracking |
| `aocs.str1.temperature` | OUT | °C | Detector temperature |
| `aocs.str1.acquisition_progress` | OUT | — | 0.0→1.0 |

### Mode State Machine

```
OFF ──power_on──► ACQUIRING ──10s──► TRACKING
                      ▲                  │
                      └── sun_angle<30° ◄┘
                      └── power_off → OFF
```

### Physics

- First-order quaternion kinematics with constant body rate
- Acquisition: 10s from cold start
- Sun blinding: validity=0 when sun_angle < 30°, re-acquires when cleared
- Noise: Gaussian per component, increases with temperature
- Output when invalid: all quaternion components = 0.0

---

## 5. S-Band Transponder

**File:** `src/svf/models/sbt.py`  
**Factory:** `make_sbt()`  
**Subsystem:** TTC  
**Bus interface:** UART / discrete

### Instantiation

```python
sbt = make_sbt(sync, store, cmd_store)
```

### Ports

| Port | Direction | Unit | Description |
|---|---|---|---|
| `ttc.sbt.power_enable` | IN | — | Power on/off |
| `ttc.sbt.uplink_signal_level` | IN | dBm | Received signal level |
| `ttc.sbt.mode_cmd` | IN | — | Mode command — consumed |
| `ttc.sbt.uplink_lock` | OUT | — | 1=locked |
| `ttc.sbt.downlink_active` | OUT | — | 1=transmitting |
| `ttc.sbt.mode` | OUT | — | 0=idle, 1=ranging, 2=tc_rx, 3=tm_tx |
| `ttc.sbt.rx_bitrate` | OUT | bps | Uplink bit rate |
| `ttc.sbt.tx_bitrate` | OUT | bps | Downlink bit rate |
| `ttc.sbt.temperature` | OUT | °C | Unit temperature |

### Physics

- Lock acquired after 2s above -110 dBm threshold
- Lock lost immediately when signal drops below threshold
- RX: 4000 bps when locked in TC_RX or RANGING
- TX: 64000 bps in TM_TX mode only
- All outputs zero when unpowered

---

## 6. PCDU

**File:** `src/svf/models/pcdu.py`  
**Factory:** `make_pcdu()`  
**Subsystem:** EPS

### Instantiation

```python
pcdu = make_pcdu(sync, store, cmd_store)
```

### Ports

| Port | Direction | Unit | Description |
|---|---|---|---|
| `eps.solar_array.generated_power` | IN | W | Solar power input |
| `eps.battery.voltage` | IN | V | Battery voltage for UVLO |
| `eps.solar_array.illumination` | IN | — | Solar illumination for MPPT |
| `eps.pcdu.lcl{1-8}.enable` | IN | — | Per-LCL enable command — consumed |
| `eps.pcdu.total_load` | OUT | W | Total load power |
| `eps.pcdu.charge_current` | OUT | A | Battery charge current |
| `eps.pcdu.mppt_efficiency` | OUT | — | MPPT efficiency (0-1) |
| `eps.pcdu.uvlo_active` | OUT | — | 1=UVLO active |
| `eps.pcdu.lcl{1-8}.status` | OUT | — | Per-LCL status |

### Physics

**LCL switching:** 8 channels, all on by default. Enable command consumed after processing. Total load = sum of enabled LCL loads (5W each).

**MPPT efficiency:** Peaks at 0.92 at illumination=0.7, degrades at extremes, zero in eclipse.

**UVLO:** All loads disconnected when battery voltage < 3.1V. Clears when voltage recovers.

**Power balance:**
```
effective_solar = solar_power × mppt_efficiency
charge_current  = (effective_solar - total_load) / battery_voltage
charge_current  = clamp(charge_current, -20, +20)
```

---

## 7. EPS FMU

**File:** `models/EpsFmu.fmu`  
**Type:** FmuEquipment wrapping FMI 3.0 FMU  
**Subsystem:** EPS

### Instantiation

```python
from svf.fmu_equipment import FmuEquipment

EPS_MAP = {
    "battery_soc":        "eps.battery.soc",
    "battery_voltage":    "eps.battery.voltage",
    "bus_voltage":        "eps.bus.voltage",
    "generated_power":    "eps.solar_array.generated_power",
    "charge_current":     "eps.battery.charge_current",
    "solar_illumination": "eps.solar_array.illumination",
    "load_power":         "eps.load.power",
}

eps = FmuEquipment(
    fmu_path="models/EpsFmu.fmu",
    equipment_id="eps",
    sync_protocol=sync,
    store=store,
    command_store=cmd_store,
    parameter_map=EPS_MAP,
)
```

### Ports

| Port | Direction | Unit | Range |
|---|---|---|---|
| `eps.solar_array.illumination` | IN (TC) | — | 0–1 |
| `eps.load.power` | IN (TC) | W | 0–200 |
| `eps.battery.soc` | OUT (TM) | — | 0.05–1.0 |
| `eps.battery.voltage` | OUT (TM) | V | 3.0–4.2 |
| `eps.bus.voltage` | OUT (TM) | V | 3.0–4.2 |
| `eps.solar_array.generated_power` | OUT (TM) | W | 0–120 |
| `eps.battery.charge_current` | OUT (TM) | A | -20–20 |

### Physics

- Solar array: power proportional to illumination (90W peak at full sun)
- Battery: non-linear Li-Ion SoC/voltage curve (3.0V at 5%, 4.2V at 100%)
- PCDU: power balance → charge current, bus voltage = battery voltage

---

## Adding a New Equipment Model

### 1. Define SRDB entries

```yaml
# srdb/baseline/{domain}.yaml
  aocs.myeq.speed:
    description: My equipment speed
    unit: rpm
    dtype: float
    classification: TM
    domain: AOCS
    model_id: myeq
    valid_range: [0.0, 1000.0]
    pus:
      apid: 0x101
      service: 3
      subservice: 25
      parameter_id: 0x20FF
```

### 2. Define requirements

```
**MYEQ-001** `[MYEQ]` `BASELINED`
MyEquipment speed shall increase when power_enable=1 and rate_cmd > 0.
```

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

### 4. Write tests — both nominal and failure

```python
@pytest.mark.requirement("MYEQ-001")
def test_speed_increases_when_commanded(my_eq):
    my_eq.receive("aocs.myeq.rate_cmd", 10.0)
    my_eq.do_step(t=0.0, dt=1.0)
    assert my_eq.read_port("aocs.myeq.speed") > 0.0

@pytest.mark.requirement("MYEQ-002")
def test_speed_stays_zero_when_not_powered(my_eq):
    my_eq.do_step(t=0.0, dt=1.0)
    assert my_eq.read_port("aocs.myeq.speed") == pytest.approx(0.0)
```

### Scalability contract

- **SRDB canonical names are stable.** Replace the model → only wiring YAML changes.
- **InterfaceType validates connections.** Type mismatch caught at load time.
- **Port commands are consumed.** One-shot commands don't persist across ticks.
- **Physics is replaceable.** `step_fn` is a plain Python function.