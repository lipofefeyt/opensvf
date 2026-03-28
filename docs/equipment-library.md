# SVF Equipment Library

> **Status:** v0.1
> **Last updated:** 2026-03
> **Author:** lipofefeyt

---

## Overview

Every spacecraft model in SVF is an `Equipment` — a Python class with named IN/OUT ports, a `do_step()` physics implementation, and SRDB-canonical parameter names. This document defines the **interface contract** for each reference model: what ports it offers, what physics it implements, and how to instantiate it.

The contract is stable. If you replace a reference model with a higher-fidelity implementation or a hardware-in-the-loop adapter, only the wiring YAML changes — nothing else.

---

## Equipment Contract Summary

| Equipment | Class / Factory | Subsystem | Bus Interface | Status |
|---|---|---|---|---|
| OBC | `ObcEquipment` | DHS | 1553 BC | M7/M8 |
| TTC | `TtcEquipment` | TTC | — (software pipe) | M7 |
| Reaction Wheel | `make_reaction_wheel()` | AOCS | 1553 RT | M6/M8 |
| Star Tracker | `make_star_tracker()` | AOCS | SpW / 1553 RT | M8 |
| S-Band Transponder | `make_sbt()` | TTC | UART / discrete | M8 |

---

## 1. OBC Equipment

**File:** `src/svf/models/obc.py`
**Class:** `ObcEquipment(Equipment)`
**Subsystem:** DHS (Data Handling System)

### Purpose

The On-Board Computer model serves two roles:

1. **PUS TC Router (M7):** Receives raw PUS-C TC bytes, parses them, routes commands to equipment via CommandStore, and generates PUS TM responses.
2. **DHS State Machine (M8):** Manages spacecraft mode, on-board time, watchdog, and mass memory.

### Configuration

```python
from svf.models.obc import ObcEquipment, ObcConfig
from svf.pus.services import HkReportDefinition

config = ObcConfig(
    apid=0x101,                    # TM APID for generated packets
    param_id_map={                  # PUS param_id -> SRDB canonical name
        0x2021: "aocs.rw1.torque_cmd",
        0x2022: "aocs.rw1.speed",
    },
    essential_hk=[                  # Auto-activated at boot
        HkReportDefinition(
            report_id=1,
            parameter_names=["aocs.rw1.speed", "eps.battery.soc"],
            period_s=1.0,
        )
    ],
    watchdog_period_s=30.0,         # Watchdog timeout
    initial_mode=MODE_SAFE,         # Starting mode
)
obc = ObcEquipment(config, sync, store, cmd_store)
```

### Ports

| Port | Direction | Unit | Description |
|---|---|---|---|
| `obc.tc_input` | IN | — | TC arrival signal |
| `dhs.obc.mode_cmd` | IN | — | Mode command (0=SAFE, 1=NOMINAL, 2=PAYLOAD) |
| `dhs.obc.watchdog_kick` | IN | — | Watchdog kick (write 1, auto-consumed) |
| `dhs.obc.memory_dump_cmd` | IN | — | Memory dump command (write 1, auto-consumed) |
| `dhs.obc.mode` | OUT | — | Current mode |
| `dhs.obc.obt` | OUT | s | On-board time |
| `dhs.obc.watchdog_status` | OUT | — | 0=nominal, 1=warning, 2=reset |
| `dhs.obc.memory_used_pct` | OUT | % | Mass memory fill percentage |
| `dhs.obc.health` | OUT | — | 0=nominal, 1=degraded, 2=failed |
| `dhs.obc.reset_count` | OUT | — | Reset counter since boot |
| `dhs.obc.cpu_load` | OUT | % | CPU load estimate |
| `obc.tm_output` | OUT | — | Latest TM sequence count |

### Mode Constants

```python
MODE_SAFE    = 0   # Low power, CSS active, minimal services
MODE_NOMINAL = 1   # Full platform services
MODE_PAYLOAD = 2   # Payload operations, higher memory fill rate
```

### Physics

**Mode transitions:** Triggered by `dhs.obc.mode_cmd`. Each transition generates a `TM(5,1)` informative event with old and new mode in auxiliary data.

**OBT:** Monotonic counter incremented by `dt` each tick.

**Watchdog:** If not kicked within `watchdog_period_s`:
- After 1× period → `WDG_WARNING` + `TM(5,2)` low severity event
- After 2× period → `WDG_RESET` + `TM(5,4)` high severity event + mode forced to SAFE

**Memory:** Fills at `0.01 %/s` in SAFE/NOMINAL, `0.05 %/s` in PAYLOAD. Cleared by `dhs.obc.memory_dump_cmd`.

**Health:** Set to `DEGRADED` when memory > 90% or CPU > 90%.

### PUS TC Routing

| Service | TC | Action |
|---|---|---|
| S1 | — | TM(1,1) acceptance + TM(1,7) completion for all TCs |
| S3 | — | TM(3,25) HK reports each tick (essential reports always active) |
| S5 | — | Events on mode transition, watchdog warning/reset |
| S17 | TC(17,1) | TM(17,2) are-you-alive response |
| S20 | TC(20,1) | Set parameter: lookup param_id → CommandStore.inject() |
| S20 | TC(20,3) | Get parameter: ParameterStore.read() → TM(20,4) |

### Test Interface

```python
# Inject TC directly (bypassing TTC)
responses = obc.receive_tc(raw_bytes, t=0.0)

# Check TM queue
tm_list = obc.get_tm_queue()           # returns and clears queue
tm_s3   = obc.get_tm_by_service(3, 25) # filter without clearing

# Direct state access for assertions
assert obc.mode == MODE_NOMINAL
assert obc.obt > 0.0
assert obc.watchdog_status == WDG_NOMINAL
```

---

## 2. TTC Equipment

**File:** `src/svf/models/ttc.py`
**Class:** `TtcEquipment(Equipment)`
**Subsystem:** TTC

### Purpose

Software bridge between test procedures (or ground segment tools) and the OBC. Forwards PUS TC bytes to the OBC and exposes TM responses for observable assertions.

In a real spacecraft, TTC handles RF uplink/downlink, carrier modulation, and frame synchronisation. This model abstracts all of that to a byte pipe.

### Instantiation

```python
from svf.models.ttc import TtcEquipment

ttc = TtcEquipment(obc, sync, store, cmd_store)
```

### Ports

| Port | Direction | Description |
|---|---|---|
| `ttc.uplink_active` | OUT | 1 when forwarding TC to OBC |
| `ttc.downlink_active` | OUT | 1 when OBC has pending TM(3,25) |

### Test Interface

```python
from svf.pus.tc import PusTcPacket

# Queue a TC for forwarding on the next tick
ttc.send_tc(PusTcPacket(
    apid=0x100, sequence_count=1,
    service=17, subservice=1,
))

# Retrieve TM responses after simulation tick
responses = ttc.get_tm_responses(service=17, subservice=2)
```

---

## 3. Reaction Wheel

**File:** `src/svf/models/reaction_wheel.py`
**Factory:** `make_reaction_wheel()`
**Subsystem:** AOCS
**Bus interface:** MIL-STD-1553 RT (RT5 in reference wiring)

### Purpose

Angular momentum actuator. Integrates torque command to produce wheel speed, with realistic bearing friction and temperature modelling.

### Instantiation

```python
from svf.models.reaction_wheel import make_reaction_wheel

rw = make_reaction_wheel(sync, store, cmd_store)
```

### Ports

| Port | Direction | Unit | Range | Description |
|---|---|---|---|---|
| `aocs.rw1.torque_cmd` | IN | Nm | ±0.2 | Torque command from 1553 bus SA1 |
| `aocs.rw1.speed` | OUT | rpm | ±6000 | Wheel speed |
| `aocs.rw1.temperature` | OUT | °C | -40…85 | Bearing temperature |
| `aocs.rw1.status` | OUT | — | 0/1 | 1=nominal, 0=over-temperature |

### Physics

**Speed integration:**
```
acceleration = torque × 100 rpm/s/Nm
coulomb_friction = ±0.5 rpm/s (direction-opposing)
viscous_friction = -0.002 × speed rpm/s
new_speed = speed + (acceleration + friction) × dt
new_speed = clamp(new_speed, -6000, +6000)
```

**Temperature:**
```
temp_rise = 0.001 × speed² × dt   (bearing losses)
temp_cool = 0.05 × (temp - ambient) × dt
```

**Over-temperature protection (>80°C):**
- Status flag = 0
- Effective torque halved (`TEMP_DERATING_FACTOR = 0.5`)
- Status evaluated on input temperature (before cooling)

### 1553 Subaddress Mapping (reference wiring)

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

### Purpose

Attitude sensor. Propagates an internal quaternion attitude model and outputs noisy quaternion measurements. Models sun blinding and acquisition time from cold start.

### Instantiation

```python
from svf.models.star_tracker import make_star_tracker

st = make_star_tracker(
    sync, store, cmd_store,
    initial_quaternion=(1.0, 0.0, 0.0, 0.0),  # identity
    body_rate_rad_s=(0.0, 0.001, 0.0),          # slow pitch rate
    seed=42,                                     # reproducible noise
)
```

### Ports

| Port | Direction | Unit | Description |
|---|---|---|---|
| `aocs.str1.power_enable` | IN | — | Power on/off |
| `aocs.str1.sun_angle` | IN | deg | Sun angle for blinding detection |
| `aocs.str1.quaternion_w` | OUT | — | Attitude quaternion W |
| `aocs.str1.quaternion_x` | OUT | — | Attitude quaternion X |
| `aocs.str1.quaternion_y` | OUT | — | Attitude quaternion Y |
| `aocs.str1.quaternion_z` | OUT | — | Attitude quaternion Z |
| `aocs.str1.validity` | OUT | — | 1=valid, 0=invalid |
| `aocs.str1.mode` | OUT | — | 0=off, 1=acquiring, 2=tracking |
| `aocs.str1.temperature` | OUT | °C | Detector temperature |
| `aocs.str1.acquisition_progress` | OUT | — | 0.0→1.0 during acquisition |

### Mode State Machine

```
OFF ──power_enable=1──► ACQUIRING ──10s elapsed──► TRACKING
                              ▲                        │
                              └──── sun blinding ◄─────┘
                              └──── power_enable=0 → OFF
```

### Physics

**Attitude propagation:** First-order quaternion kinematics using constant body rate.

**Acquisition:** `ACQUISITION_TIME_S = 10.0s` from cold start. Progress reported on `acquisition_progress` port.

**Sun blinding:** If `sun_angle < SUN_EXCLUSION_DEG (30°)`:
- Validity → 0
- Mode → ACQUIRING (re-acquires when sun clears)

**Measurement noise:**
```
noise_std = BASE_NOISE_STD + TEMP_NOISE_COEFF × (temp - nominal_temp)
```
White Gaussian noise added to each quaternion component when valid. Quaternion renormalised after noise injection.

**Output when invalid:** All quaternion components = 0.0.

**Temperature:** Rises towards `NOMINAL_TEMP_C (35°C)` when powered, cools towards ambient when off.

---

## 5. S-Band Transponder

**File:** `src/svf/models/sbt.py`
**Factory:** `make_sbt()`
**Subsystem:** TTC
**Bus interface:** UART / discrete signals

### Purpose

S-Band RF link model. Simulates carrier lock acquisition, mode transitions, and bit rate reporting for both uplink TC and downlink TM paths.

### Instantiation

```python
from svf.models.sbt import make_sbt

sbt = make_sbt(sync, store, cmd_store)
```

### Ports

| Port | Direction | Unit | Description |
|---|---|---|---|
| `ttc.sbt.power_enable` | IN | — | Power on/off |
| `ttc.sbt.uplink_signal_level` | IN | dBm | Received signal level |
| `ttc.sbt.mode_cmd` | IN | — | Mode command (consumed after use) |
| `ttc.sbt.uplink_lock` | OUT | — | 1=carrier locked |
| `ttc.sbt.downlink_active` | OUT | — | 1=transmitting TM |
| `ttc.sbt.mode` | OUT | — | Current mode |
| `ttc.sbt.rx_bitrate` | OUT | bps | Uplink bit rate |
| `ttc.sbt.tx_bitrate` | OUT | bps | Downlink bit rate |
| `ttc.sbt.temperature` | OUT | °C | Unit temperature |

### Mode Constants

```python
MODE_IDLE    = 0   # Powered but inactive
MODE_RANGING = 1   # Ranging mode (two-way Doppler)
MODE_TC_RX   = 2   # Receiving telecommands
MODE_TM_TX   = 3   # Transmitting telemetry
```

### Physics

**Carrier lock:**
- Signal must exceed `LOCK_THRESHOLD_DBM (-110 dBm)` for `LOCK_TIME_S (2.0s)`
- Lock lost immediately when signal drops below threshold

**Bit rates:**
- RX: `TC_BITRATE_BPS (4000 bps)` when locked in TC_RX or RANGING
- TX: `TM_BITRATE_BPS (64000 bps)` when in TM_TX mode

**Mode commands:** Consumed after processing (no sticky state).

**Temperature:** Rises towards `OPERATING_TEMP (35°C)` when powered.

---

## Adding a New Equipment Model

### 1. Define SRDB entries

Add parameters to the appropriate domain baseline in `srdb/baseline/`:

```yaml
# srdb/baseline/aocs.yaml
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

Add requirements to `REQUIREMENTS.md` under a new functional area:

```
**MYEQ-001** `[MYEQ]` `BASELINED`
MyEquipment speed shall increase when power_enable=1 and rate_cmd > 0.
```

### 3. Implement the model

```python
from svf.equipment import PortDefinition, PortDirection
from svf.native_equipment import NativeEquipment

def _my_step(eq: NativeEquipment, t: float, dt: float) -> None:
    rate = eq.read_port("aocs.myeq.rate_cmd")
    speed = eq.read_port("aocs.myeq.speed")
    eq.write_port("aocs.myeq.speed", speed + rate * dt)

def make_my_equipment(sync, store, cmd_store):
    return NativeEquipment(
        equipment_id="myeq",
        ports=[
            PortDefinition("aocs.myeq.rate_cmd", PortDirection.IN,  unit="rpm/s"),
            PortDefinition("aocs.myeq.speed",    PortDirection.OUT, unit="rpm"),
        ],
        step_fn=_my_step,
        sync_protocol=sync,
        store=store,
        command_store=cmd_store,
    )
```

### 4. Write tests

```python
@pytest.mark.requirement("MYEQ-001")
def test_speed_increases_when_commanded(my_eq):
    my_eq.receive("aocs.myeq.rate_cmd", 10.0)
    my_eq.do_step(t=0.0, dt=1.0)
    assert my_eq.read_port("aocs.myeq.speed") > 0.0
```

### 5. Add to wiring YAML

```yaml
connections:
  - from: platform_bus.rt6_out
    to:   myeq.m1553_rt_in
    interface: MIL1553_RT
    rt_address: 6
    subaddress_map:
      - sa: 1
        parameter: aocs.myeq.rate_cmd
```

### Scalability contract

- **SRDB canonical names are stable.** If you replace this model with a higher-fidelity version, the canonical names do not change — only the FMU `parameter_map` or `NativeEquipment` port definitions.
- **InterfaceType validates connections.** The wiring loader rejects incompatible interface types at load time — before the simulation runs.
- **Port commands are consumed.** One-shot commands (mode_cmd, kick, dump_cmd) are consumed after processing so they don't persist across ticks.
- **Physics is replaceable.** The `step_fn` is a plain Python function — swap it for any implementation without touching the port layer.