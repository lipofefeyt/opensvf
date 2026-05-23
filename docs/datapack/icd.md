---
title: "OpenSVF — Interface Control Document"
subtitle: "SVF-ICD-001 | Issue 1.0"
author: "Gonçalo Graças"
date: "2026-05-23"
subject: "Interface Control Document"
keywords: [spacecraft, PUS-C, FMI, YAMCS, SRDB, wire protocol, XTCE]
lang: en
titlepage: true
titlepage-color: "1a1a2e"
titlepage-text-color: "EEEEEE"
titlepage-rule-color: "4a90d9"
titlepage-rule-height: 4
toc: true
toc-own-page: true
numbersections: true
colorlinks: true
linkcolor: "4a90d9"
fontsize: 11pt
geometry: "margin=2.5cm"
header-left: "SVF-ICD-001"
header-right: "OpenSVF Interface Control Document"
footer-left: "Issue 1.0 — 2026-05-23"
footer-right: "Page \\thepage"
classoption: oneside
---

# Introduction

## Purpose

This document specifies all external interfaces of **OpenSVF** (v0.7.1). It is
the authoritative reference for:

- flight software teams integrating an OBSW binary with the SVF framework
- physics engine teams providing an FMI 2.0 FMU plant model
- ground station engineers connecting YAMCS to the SVF TM/TC pipeline
- toolchain developers extending the SRDB parameter namespace

## Scope

Four interfaces are defined:

| ID | Interface | Counterpart |
|---|---|---|
| IF-1 | SVF Wire Protocol v3 | openobsw (C11 flight software) |
| IF-2 | FMI 2.0 Co-Simulation | opensvf-kde (C++ physics engine FMU) |
| IF-3 | YAMCS Data Exchange | YAMCS 5.12.6 ground station |
| IF-4 | SRDB Parameter Contract | All components |

## Applicable Documents

| Reference | Title |
|---|---|
| ECSS-E-ST-70-41C | Space Engineering — Telemetry and Telecommand Packet Utilisation |
| FMI 2.0 Specification | Functional Mock-up Interface for Model Exchange and Co-Simulation |
| OMG XTCE 1.2 | XML Telemetry and Command Exchange |
| SVF-ADD-001 | OpenSVF Architecture Description Document |
| SVF-SVS-001 | OpenSVF Software Validation Specification |

## Terms and Abbreviations

| Term | Definition |
|---|---|
| APID | Application Process Identifier (PUS-C primary header field) |
| FMI | Functional Mock-up Interface |
| FMU | Functional Mock-up Unit |
| HK | Housekeeping |
| ICD | Interface Control Document |
| MDB | Mission Database |
| OBSW | On-Board Software |
| PUS | Packet Utilisation Standard (ECSS-E-ST-70-41C) |
| SRDB | Spacecraft Reference Database |
| TC | Telecommand |
| TM | Telemetry |
| XTCE | XML Telemetry and Command Exchange |

---

# IF-1: SVF Wire Protocol v3

## Overview

The SVF Wire Protocol v3 is a binary framing protocol used for bidirectional
communication between `OBCEmulatorAdapter` (opensvf) and the openobsw binary
(`obsw_sim` or Renode UART terminal). Communication uses either:

- **Pipe mode** — the OBSW binary stdin/stdout stream
- **Socket mode** — a TCP connection to Renode UART terminal (default port 3456)

All data sent by opensvf is called *upstream* (SVF → OBSW). All data sent by
openobsw is called *downstream* (OBSW → SVF).

The C reference implementation of this protocol lives in
`contrib/svf_protocol/` of the openobsw repository.

## Frame Format

Every frame — upstream and downstream — uses the same envelope:

```
┌────────────┬──────────────────────┬──────────────────────┐
│ type_byte  │  length (uint16 BE)  │  body (length bytes) │
│  (1 byte)  │       (2 bytes)      │                      │
└────────────┴──────────────────────┴──────────────────────┘
```

- **`type_byte`** — identifies the frame content (see Table 1)
- **`length`** — number of body bytes, big-endian unsigned 16-bit integer
- **`body`** — frame payload; length is bounded to [1, 4096] bytes

## Frame Type Codes

*Table 1 — Frame type codes*

| Type | Hex | Direction | Body content |
|---|---|---|---|
| TC Uplink | `0x01` | SVF → OBSW | Raw PUS-C TC packet bytes |
| Sensor Injection | `0x02` | SVF → OBSW | `obsw_sensor_frame_t` (47 bytes) |
| Actuator Output | `0x03` | OBSW → SVF | `obsw_actuator_frame_t` (29 bytes) |
| TM Downlink | `0x04` | OBSW → SVF | Raw PUS-C TM packet bytes |

## End-of-Tick Synchronisation

Every simulation tick is terminated by a single synchronisation byte sent
downstream by the OBSW (OBSW → SVF):

```
0xFF   (1 byte, no length prefix, no body)
```

The `0xFF` byte is **not** a framed message — it is a bare byte that signals the
OBSW has finished processing the current tick and has emitted all frames for that
tick. `OBCEmulatorAdapter._collect_until_sync()` reads frames until `0xFF` is
received or the sync timeout expires.

**Desync handling:** If the `0xFF` byte is not received within `sync_timeout`
seconds (default 5.0 s), the desync counter increments. After `MAX_DESYNC = 3`
consecutive ticks without sync, `OBCEmulatorAdapter` raises `RuntimeError("Lost
sync")`. The counter resets to zero on any tick where sync is achieved.

## Tick Sequence

The following exchange occurs on every simulation tick:

```
SVF                                          OBSW
 │                                            │
 │──── [0x02][len][obsw_sensor_frame_t] ─────►│  (sensor data)
 │──── [0x01][len][PUS TC bytes]        ─────►│  (TC; heartbeat if none queued)
 │                                            │
 │◄─── [0x04][len][PUS TM bytes]        ──────│  (zero or more TM packets)
 │◄─── [0x03][len][obsw_actuator_frame_t] ────│  (zero or one actuator frame)
 │◄─── [0xFF]                           ──────│  (end-of-tick sync)
 │                                            │
```

opensvf always sends the sensor frame before TCs. If no TC is queued,
a TC(17,1) heartbeat ping is sent automatically.

## Sensor Frame — `obsw_sensor_frame_t`

**Size:** 47 bytes  
**Byte order:** Little-endian  
**Python struct format:** `<3fB4fB3fBf`

```c
/* obsw_sensor_frame_t — #pragma pack(1), little-endian */
typedef struct {
    float    mag_x,  mag_y,  mag_z;   /* [T]       magnetic field vector  */
    uint8_t  mag_valid;                /* 1=valid, 0=invalid               */
    float    st_q_w, st_q_x,
             st_q_y, st_q_z;          /* unit quaternion (scalar-first)    */
    uint8_t  st_valid;                 /* 1=valid, 0=invalid               */
    float    gyro_x, gyro_y, gyro_z;  /* [rad/s]   angular rate           */
    uint8_t  gyro_valid;               /* 1=valid, 0=invalid               */
    float    sim_time;                 /* [s]       simulation epoch time  */
} obsw_sensor_frame_t;                /* Total: 47 bytes                  */
```

*Table 2 — Sensor frame field layout*

| Offset | Size | Field | Unit | Notes |
|---|---|---|---|---|
| 0 | 4 | `mag_x` | T | Magnetometer X measurement |
| 4 | 4 | `mag_y` | T | Magnetometer Y measurement |
| 8 | 4 | `mag_z` | T | Magnetometer Z measurement |
| 12 | 1 | `mag_valid` | — | 1 if magnetometer output is valid |
| 13 | 4 | `st_q_w` | — | Star tracker quaternion scalar component |
| 17 | 4 | `st_q_x` | — | Star tracker quaternion X |
| 21 | 4 | `st_q_y` | — | Star tracker quaternion Y |
| 25 | 4 | `st_q_z` | — | Star tracker quaternion Z |
| 29 | 1 | `st_valid` | — | 1 if star tracker output is valid |
| 30 | 4 | `gyro_x` | rad/s | Gyroscope X angular rate |
| 34 | 4 | `gyro_y` | rad/s | Gyroscope Y angular rate |
| 38 | 4 | `gyro_z` | rad/s | Gyroscope Z angular rate |
| 42 | 1 | `gyro_valid` | — | 1 if gyroscope output is valid |
| 43 | 4 | `sim_time` | s | Simulation epoch time |

**Source mapping:** `OBCEmulatorAdapter._send_sensor_frame()` reads the sensor
fields from `ParameterStore` using the SRDB canonical names listed below.
The `*_valid` flags are set from status ports thresholded at 0.5.

| `obsw_sensor_frame_t` field | SRDB parameter | Notes |
|---|---|---|
| `mag_x/y/z` | `aocs.mag.field_x/y/z` | Noisy measurement from magnetometer model |
| `mag_valid` | `aocs.mag.status` | Thresholded: > 0.5 → valid |
| `st_q_w/x/y/z` | `aocs.str1.quaternion_w/x/y/z` | Star tracker attitude estimate |
| `st_valid` | `aocs.str1.validity` | Thresholded: > 0.5 → valid |
| `gyro_x/y/z` | `aocs.gyro.rate_x/y/z` | Noisy measurement from gyroscope model |
| `gyro_valid` | `aocs.gyro.status` | Thresholded: > 0.5 → valid |
| `sim_time` | — | Simulation time `t` passed to `do_step()` |

## Actuator Frame — `obsw_actuator_frame_t`

**Size:** 29 bytes  
**Byte order:** Little-endian  
**Python struct format:** `<6fBf`

```c
/* obsw_actuator_frame_t — #pragma pack(1), little-endian */
typedef struct {
    float    mtq_x,        mtq_y,        mtq_z;       /* [Am²] MTQ dipole  */
    float    rw_torque_x,  rw_torque_y,  rw_torque_z; /* [Nm]  RW torques  */
    uint8_t  controller_mode; /* 0=bdot, 1=adcs                            */
    float    sim_time;        /* [s]  simulation epoch time                */
} obsw_actuator_frame_t;      /* Total: 29 bytes                           */
```

*Table 3 — Actuator frame field layout*

| Offset | Size | Field | Unit | Notes |
|---|---|---|---|---|
| 0 | 4 | `mtq_x` | Am² | Magnetorquer X dipole moment |
| 4 | 4 | `mtq_y` | Am² | Magnetorquer Y dipole moment |
| 8 | 4 | `mtq_z` | Am² | Magnetorquer Z dipole moment |
| 12 | 4 | `rw_torque_x` | Nm | Reaction wheel 1 torque command |
| 16 | 4 | `rw_torque_y` | Nm | Reaction wheel 2 torque command |
| 20 | 4 | `rw_torque_z` | Nm | Reaction wheel 3 torque command |
| 24 | 1 | `controller_mode` | — | 0 = b-dot active, 1 = ADCS PD active |
| 25 | 4 | `sim_time` | s | Simulation epoch time from OBSW |

**Sink mapping:** `OBCEmulatorAdapter._parse_actuator()` injects the parsed
values into `CommandStore` using the following SRDB canonical names:

| `obsw_actuator_frame_t` field | SRDB parameter |
|---|---|
| `mtq_x` | `aocs.mtq.dipole_x` |
| `mtq_y` | `aocs.mtq.dipole_y` |
| `mtq_z` | `aocs.mtq.dipole_z` |
| `rw_torque_x` | `aocs.rw1.torque_cmd` |
| `rw_torque_y` | `aocs.rw2.torque_cmd` |
| `rw_torque_z` | `aocs.rw3.torque_cmd` |

## PUS Services

The OBSW must implement the following PUS-C services to interoperate with
opensvf:

*Table 4 — Required PUS service support*

| Service | Subservice | Direction | When emitted | opensvf use |
|---|---|---|---|---|
| S1 | 1 | OBSW → SVF | TC accepted | Procedure verification |
| S1 | 7 | OBSW → SVF | TC completed | Procedure verification |
| S3 | 25 | OBSW → SVF | Periodic HK | DHS telemetry update |
| S5 | 1 | OBSW → SVF | Mode transition or anomaly | FDIR chain / mode state |
| S8 | 1 | SVF → OBSW | Mode transition command | Nominal mode recovery |
| S17 | 1 | SVF → OBSW | Every tick (heartbeat) | Watchdog / liveness |
| S17 | 2 | OBSW → SVF | In response to TC(17,1) | Are-you-alive round-trip |
| S20 | 1 | SVF → OBSW | Parameter set | Mode command, watchdog kick |
| S20 | 2 | OBSW → SVF | Parameter get response | Parameter readback |

### TC(17,1) Heartbeat

opensvf sends a TC(17,1) Are-You-Alive ping on every tick where no other TC is
queued. The fixed binary encoding is:

```
1801 C000 0003 20 11 01 00
```

| Field | Value | Notes |
|---|---|---|
| Primary header `version+type+DFHDR` | `0x18` | TC, unsegmented |
| Primary header APID | `0x01` (low byte) | APID = 0x001 |
| Sequence flags + count | `0xC000` | Standalone packet, count=0 |
| Data length | `0x0003` | 3 bytes application data |
| PUS version + spare | `0x20` | PUS-C |
| Service | `0x11` | S17 |
| Subservice | `0x01` | Are-You-Alive |
| Padding | `0x00` | |

### TC(8,1) Mode Recovery

opensvf sends TC(8,1) when `dhs.obc.mode_cmd` is set to `1` (NOMINAL):

```
1801 C000 000? 20 08 01 00 01 00
```

User data: `[0x00, 0x01, 0x00]` (mode = NOMINAL = 1).

### S5 Event IDs — Mode Transitions

`OBCEmulatorAdapter._on_s5()` parses the event ID from bytes [17:19] of the
TM(5,1) packet (big-endian uint16):

| Event ID | Meaning | opensvf action |
|---|---|---|
| `0x0002` | Transition to SAFE mode | Sets `self._mode = MODE_SAFE (0)` |
| `0x0003` | Transition to NOMINAL mode | Sets `self._mode = MODE_NOMINAL (1)` |

## TM(3,25) DHS OBC Housekeeping Packet

The OBSW shall emit a periodic TM(3,25) packet with APID `0x103` containing
the DHS OBC housekeeping report. opensvf parses this packet in
`OBCEmulatorAdapter._on_s3_25()`.

### Packet Layout

```
Offset  Size  Field
──────  ────  ─────────────────────────────────────────────────────
0–5      6    PUS-C primary header (CCSDS)
6–16    11    PUS-C secondary header (version, svc=3, subsvc=25, ...)
17       1    set_id = 0x03  (DHS OBC HK set)
18       1    mode         uint8  — 0=SAFE, 1=NOMINAL, 2=PAYLOAD
19–22    4    obt          uint32 BE — on-board time [s]
23       1    watchdog_status  uint8  — 0=nominal, 1=timeout_warning, 2=reset
24       1    memory_used_pct  uint8  — mass memory utilisation [%]
25       1    health       uint8  — 0=nominal, 1=degraded, 2=failed
26–27    2    reset_count  uint16 BE — resets since launch
28       1    cpu_load     uint8  — CPU utilisation [%]
end–2    2    CRC-16/CCITT
```

**Python struct format (application data fields only, starting at offset 18):**

```python
_DHS_OBC_HK_FMT = ">BIBBBHB"
# B  — mode         (uint8)
# I  — obt          (uint32 BE)
# B  — watchdog     (uint8)
# B  — memory_used  (uint8)
# B  — health       (uint8)
# H  — reset_count  (uint16 BE)
# B  — cpu_load     (uint8)
```

The byte at offset 17 (`set_id`) is read separately and must equal `0x03`
before the HK fields are parsed.

### SRDB Mapping

*Table 5 — TM(3,25) HK field to SRDB parameter mapping*

| Offset | HK field | SRDB parameter | PUS param_id | Unit |
|---|---|---|---|---|
| 18 | `mode` | `dhs.obc.mode` | 0x4001 | 0/1/2 |
| 19–22 | `obt` | `dhs.obc.obt` | 0x4003 | s |
| 23 | `watchdog_status` | `dhs.obc.watchdog_status` | 0x4004 | — |
| 24 | `memory_used_pct` | `dhs.obc.memory_used_pct` | 0x4006 | % |
| 25 | `health` | `dhs.obc.health` | 0x4008 | — |
| 26–27 | `reset_count` | `dhs.obc.reset_count` | 0x4009 | count |
| 28 | `cpu_load` | `dhs.obc.cpu_load` | 0x400A | % |

All fields are within APID `0x103`, service 3, subservice 25.

## Transport Configuration

*Table 6 — Transport parameters by OBC mode*

| Parameter | Pipe mode | Socket (Renode) mode |
|---|---|---|
| Transport | `stdin`/`stdout` | TCP socket |
| OBSW endpoint | subprocess `obsw_sim` | `localhost:3456` |
| opensvf class | `OBCEmulatorAdapter(sim_path=...)` | `OBCEmulatorAdapter(socket_addr=("localhost", 3456))` |
| `spacecraft.yaml` key | `obsw.type: pipe` | `obsw.type: socket` |
| aarch64 support | Auto-detected via `file(1)`, QEMU | Not applicable (native Renode) |

---

# IF-2: FMI 2.0 Co-Simulation Interface

## Overview

OpenSVF integrates an external physics engine (plant model) via the
FMI 2.0 Co-Simulation standard. The reference implementation is
`SpacecraftDynamics.fmu` from the `opensvf-kde` project. A minimal test FMU
(`SimpleCounter.fmu`) is bundled in `models/` for infrastructure tests.

`FmuEquipment` (the SVF adapter) wraps any FMI 2.0 Co-Simulation FMU into the
`Equipment` interface, making it indistinguishable from a `NativeEquipment`
model to `SimulationMaster`.

## KDE FMU Port Contract

The `SpacecraftDynamics.fmu` exposes the following interface as seen by
opensvf. All port names use SRDB canonical names; the `make_kde_equipment()`
factory maps them to FMU variable references internally.

*Table 7 — KDE FMU input ports (SVF → FMU)*

| SRDB parameter | Unit | Description |
|---|---|---|
| `aocs.mtq.torque_x` | Nm | Magnetorquer mechanical torque X |
| `aocs.mtq.torque_y` | Nm | Magnetorquer mechanical torque Y |
| `aocs.mtq.torque_z` | Nm | Magnetorquer mechanical torque Z |

*Table 8 — KDE FMU output ports (FMU → SVF)*

| SRDB parameter | Unit | Description |
|---|---|---|
| `aocs.truth.rate_x` | rad/s | True body angular rate X (Euler body frame) |
| `aocs.truth.rate_y` | rad/s | True body angular rate Y |
| `aocs.truth.rate_z` | rad/s | True body angular rate Z |
| `aocs.mag.true_x` | T | True magnetic field X (body frame) |
| `aocs.mag.true_y` | T | True magnetic field Y |
| `aocs.mag.true_z` | T | True magnetic field Z |
| `aocs.attitude.quaternion_w` | — | True attitude quaternion scalar |
| `aocs.attitude.quaternion_x` | — | True attitude quaternion X |
| `aocs.attitude.quaternion_y` | — | True attitude quaternion Y |
| `aocs.attitude.quaternion_z` | — | True attitude quaternion Z |

## Step Synchronisation

The FMU is driven by `SimulationMaster` in fixed-step co-simulation mode.
On each tick:

1. `SimulationMaster` calls `FmuEquipment.do_step(t, dt)`
2. `FmuEquipment` sets FMU input variables from IN ports
3. `FmuEquipment` calls `fmi2DoStep(t, dt)` on the FMU
4. `FmuEquipment` reads FMU output variables into OUT ports

The FMU must not advance time autonomously — it must respect the co-simulation
step boundaries imposed by `SimulationMaster`.

## FMU Binary Location

FMU binaries are not committed to the opensvf repository. They are built
separately and placed in `models/` at the repository root:

```
models/
├── SpacecraftDynamics.fmu   (from opensvf-kde; required for L3/L4)
└── SimpleCounter.fmu        (bundled test double; required for L2)
```

Integration tests reference FMUs via:

```python
Path(__file__).parent.parent.parent / "models" / "SimpleCounter.fmu"
```

---

# IF-3: YAMCS Ground Station Interface

## Overview

OpenSVF connects to YAMCS 5.12.6 for ground station integration. YAMCS
receives PUS TM packets and sends PUS TC packets. The link is established
by `YamcsBridge` / `TtcEquipment` within the SVF equipment layer.

## Network Endpoints

*Table 9 — YAMCS network interface*

| Stream | Protocol | Address | Port | Direction |
|---|---|---|---|---|
| TM downlink | TCP | `127.0.0.1` | `10015` | opensvf → YAMCS |
| TC uplink | UDP | `127.0.0.1` | `10025` | YAMCS → opensvf |
| Web UI | HTTP | `localhost` | `8090` | Browser → YAMCS |

Default credentials for the web UI: `admin` / `password`.

## YAMCS Configuration Files

| File | Purpose |
|---|---|
| `yamcs/etc/yamcs.yaml` | Instance list, web UI port |
| `yamcs/etc/yamcs.opensvf.yaml` | Data links, MDB reference, stream config |
| `yamcs/etc/processor.yaml` | Realtime processor definition |
| `yamcs/mdb/opensvf.xml` | XTCE Mission Database (generated from SRDB) |

## Mission Database (XTCE)

The XTCE MDB is generated from the SRDB by `tools/generate_xtce.py` and
committed to `yamcs/mdb/opensvf.xml`. To regenerate after SRDB changes:

```bash
python3 tools/generate_xtce.py > yamcs/mdb/opensvf.xml
```

### Parameter Types

The MDB defines two parameter types:

| XTCE type | SRDB dtype | Size | Encoding |
|---|---|---|---|
| `float32` | `float` | 32 bits | IEEE 754 single-precision |
| `int32` | `int` | 32 bits | Two's complement |

SRDB parameters with `dtype: int` (mode, health, status counters) are mapped
to `int32`. All other parameters use `float32`.

### Container Definitions

*Table 10 — XTCE container definitions*

| Container | Service | Subservice | Description |
|---|---|---|---|
| `PUS_Packet` | — | — | Abstract root; matches all PUS packets |
| `TM_1_1_Accept` | 1 | 1 | TC acceptance success |
| `TM_1_7_Complete` | 1 | 7 | TC completion success |
| `TM_3_25_HK` | 3 | 25 | Housekeeping parameter report |
| `TM_5_1_Event` | 5 | 1 | Event report (informative) |
| `TM_17_2_Pong` | 17 | 2 | Are-You-Alive response |
| `TM_20_2_ParamReport` | 20 | 2 | Parameter value report |

### PUS-C Header Layout

The XTCE root container `PUS_Packet` locates the service and subservice fields
at fixed bit offsets from the start of the packet:

| Field | Bit offset | Size | Notes |
|---|---|---|---|
| `pus_svc` | 56 | 8 bits | Byte 7 of packet |
| `pus_subsvc` | 64 | 8 bits | Byte 8 of packet |

This assumes the standard PUS-C secondary header layout:
bytes 6–16 = `[PUS version+spare][svc][subsvc][...timestamp...]`.

### TC Definitions

*Table 11 — XTCE TC (MetaCommand) definitions*

| MetaCommand | Service | Subservice | Arguments |
|---|---|---|---|
| `TC_17_1_AreYouAlive` | 17 | 1 | None (fixed binary) |
| `TC_20_1_SetParameter` | 20 | 1 | `parameter_id` (uint16), `value` (float32) |

### SRDB → XTCE Parameter Name Mapping

XTCE parameter names are derived from SRDB canonical names by replacing `.`
and `-` with `_`:

| SRDB canonical name | XTCE parameter name |
|---|---|
| `dhs.obc.mode` | `dhs_obc_mode` |
| `aocs.mag.field_x` | `aocs_mag_field_x` |
| `dhs.obc.cpu_load` | `dhs_obc_cpu_load` |

---

# IF-4: SRDB Parameter Contract

## Overview

The Spacecraft Reference Database (SRDB) is the shared parameter namespace
contract between opensvf, openobsw, and YAMCS. Every inter-component parameter
has exactly one canonical name, one PUS service assignment, and one SRDB entry.

The SRDB baseline lives in `srdb/baseline/*.yaml` — one file per subsystem
domain. The `SrdbLoader` parses all baseline files into a single unified
registry at runtime.

## Parameter Naming Convention

SRDB canonical names follow the pattern:

```
<domain>.<subsystem>.<parameter>
```

| Segment | Example | Notes |
|---|---|---|
| `domain` | `aocs`, `dhs`, `eps` | Top-level subsystem domain |
| `subsystem` | `mag`, `obc`, `rw1` | Equipment instance or sub-system |
| `parameter` | `field_x`, `mode`, `cpu_load` | Measurement or command name |

## Parameter Record Fields

Each SRDB entry specifies:

| Field | Type | Description |
|---|---|---|
| `description` | string | Human-readable description |
| `unit` | string | Engineering unit (SI; empty string for dimensionless) |
| `dtype` | `float` or `int` | Data type for XTCE and store encoding |
| `classification` | `TM` or `TC` | Telemetry or command |
| `domain` | string | Subsystem domain label |
| `model_id` | string | Generating equipment model identifier |
| `valid_range` | [min, max] | Nominal operating range |
| `pus.apid` | int | PUS APID |
| `pus.service` | int | PUS service number |
| `pus.subservice` | int | PUS subservice number |
| `pus.parameter_id` | int | PUS parameter ID within the HK set |

## DHS OBC HK Parameter IDs

The following parameters are emitted by openobsw in APID `0x103`, S3(25),
set_id=3. The PUS parameter IDs are fixed and must not be changed without
updating both the OBSW and opensvf simultaneously.

*Table 12 — DHS OBC HK PUS parameter ID allocation*

| SRDB canonical name | param_id | dtype | Unit | Valid range |
|---|---|---|---|---|
| `dhs.obc.mode` | `0x4001` | int | — | [0, 2] |
| `dhs.obc.obt` | `0x4003` | float | s | [0, 3.156×10⁷] |
| `dhs.obc.watchdog_status` | `0x4004` | int | — | [0, 2] |
| `dhs.obc.memory_used_pct` | `0x4006` | float | % | [0, 100] |
| `dhs.obc.health` | `0x4008` | int | — | [0, 2] |
| `dhs.obc.reset_count` | `0x4009` | int | count | [0, 65535] |
| `dhs.obc.cpu_load` | `0x400A` | float | % | [0, 100] |

## PUS ID Allocation Policy

IDs within APID `0x103` / S3(25) are allocated by range to avoid collisions:

| Range | Domain | Notes |
|---|---|---|
| `0x4001`–`0x400F` | `dhs.*` | Current openobsw OBC health telemetry |
| `0x4010`–`0x403F` | `obdh.mode.*` | Mode management (future OBDH subsystem) |
| `0x4040`–`0x404F` | `obdh.obc.*` | OBDH OBC health (future) |

## SRDB Consistency Enforcement

`checkcons` (`tools/srdb_consistency_check.py`) automatically verifies that:

- Python struct formats match C struct byte counts ([1/7])
- `obc_emulator.py` store keys match the SRDB parameter mapping ([2/7])
- Sensor model port names in opensvf match field names in the C struct ([4/7])
- Equipment OUT ports declared in Python exist in the SRDB baseline ([7/7])

Run `checkcons` before any pull request that touches SRDB, wire protocol
structs, or sensor model port names.
