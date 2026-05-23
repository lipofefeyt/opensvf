# openobsw — Handoff Context (2026-05-23)

This document gives you everything you need to continue work on **openobsw**
with full awareness of how opensvf integrates with it.

---

## What opensvf is

opensvf is the spacecraft software validation facility — a Python framework
that runs campaigns of test procedures against a simulated or real OBSW binary.
It lives at `../opensvf` (parallel to this repo).

The relevant integration point is `OBCEmulatorAdapter` in
`opensvf/src/svf/models/dhs/obc_emulator.py`. It wraps the real openobsw
binary as a drop-in replacement for the software OBC stub.

---

## Wire protocol (what opensvf expects from openobsw)

Communication is over **stdin/stdout** (pipe mode) or **TCP socket** (Renode
UART terminal on port 3456). Frames are type-prefixed:

```
Type 0x01 — TC uplink:        [0x01][uint16 BE length][raw PUS TC bytes]
Type 0x02 — Sensor injection: [0x02][uint16 BE length][obsw_sensor_frame_t]
Type 0x03 — Actuator output:  [0x03][uint16 BE length][obsw_actuator_frame_t]
Type 0x04 — TM downlink:      [0x04][uint16 BE length][raw PUS TM bytes]
```

Each transaction ends with a **0xFF sync byte**.

### obsw_sensor_frame_t (47 bytes, little-endian)
```c
float mag_x, mag_y, mag_z;       // [T]
uint8_t mag_valid;
float st_q_w, st_q_x, st_q_y, st_q_z;  // unit quaternion
uint8_t st_valid;
float gyro_x, gyro_y, gyro_z;   // [rad/s]
uint8_t gyro_valid;
float sim_time;                   // [s]
```

### obsw_actuator_frame_t (29 bytes, little-endian)
```c
float mtq_x, mtq_y, mtq_z;      // dipole [Am²]
float rw_torque_x, rw_torque_y, rw_torque_z;  // [Nm]
uint8_t controller_mode;          // 0=bdot, 1=adcs
float sim_time;                   // [s]
```

---

## PUS services opensvf expects openobsw to emit

| Service | Subservice | When | Used for |
|---------|-----------|------|---------|
| S1      | 1         | TC accepted | Procedure verification |
| S1      | 7         | TC completed | Procedure verification |
| S3      | 25        | Periodic HK | DHS telemetry (mode, OBT, watchdog, health, CPU load, memory) |
| S5      | 1         | Mode transition or anomaly | FDIR chain verification |
| S17     | 2         | In response to TC(17,1) | Are-you-alive roundtrip |
| S20     | 2         | Parameter get response | Parameter readback |

S5 event IDs opensvf parses for mode state:
- `0x0002` → transition to SAFE
- `0x0003` → transition to NOMINAL

---

## SRDB parameter names opensvf uses

These are the canonical parameter names that opensvf maps to OUT ports and
reads in campaign procedures. The S3 HK report from openobsw must include:

| Parameter | Unit | PUS param_id | Notes |
|-----------|------|-------------|-------|
| `dhs.obc.mode` | 0/1/2 | 0x4001 | SAFE=0, NOMINAL=1, PAYLOAD=2 |
| `dhs.obc.obt` | s | 0x4003 | On-board time |
| `dhs.obc.watchdog_status` | 0/1/2 | 0x4004 | 0=nominal |
| `dhs.obc.memory_used_pct` | % | 0x4006 | Mass memory fill |
| `dhs.obc.health` | 0/1/2 | 0x4008 | 0=nominal, 1=degraded, 2=failed |
| `dhs.obc.reset_count` | count | 0x4009 | Reset counter |
| `dhs.obc.cpu_load` | % | 0x400A | CPU utilisation |

All above parameters are in APID **0x103**, service **3**, subservice **25**
(the DHS OBC HK set, set_id=3). The S3(25) HK packet layout opensvf parses:

```python
_DHS_OBC_HK_FMT = ">BIBBBHB"  # mode(B), obt(I), wd(B), mem(B), health(B), reset(H), cpu(B)
# app_data[0] = set_id = 3
# app_data[1:] = struct.pack(_DHS_OBC_HK_FMT, mode, obt, wd, mem, health, reset, cpu)
```

---

## SRDB PUS ID changes (2026-05-23)

The `obdh.*` parameter namespace (intended for a future OBDH model,
`model_id: obdh`) had parameter ID collisions with `dhs.*` within the same
APID 0x103 / S3(25) packet. **These are now fixed:**

| Parameter | Old ID | New ID | Reason |
|-----------|--------|--------|--------|
| `obdh.obc.cpu_load` | 0x4001 | **0x4040** | clashed with `dhs.obc.mode` |
| `obdh.obc.uptime` | 0x4003 | **0x4042** | clashed with `dhs.obc.obt` |

**Impact on openobsw:** none — openobsw emits `dhs.*` parameters (IDs
0x4001–0x400A), which are unchanged. The `obdh.*` parameters are for a future
model that doesn't exist yet.

---

## XTCE MDB type fix (2026-05-23)

`yamcs/mdb/opensvf.xml` has been regenerated. Integer SRDB parameters
(`dtype: int`) now declare `parameterTypeRef="int32"` instead of `float32`.
This affects YAMCS display and range checking only — no wire protocol change.

Parameters that changed type in the MDB: `dhs_obc_mode`, `dhs_obc_reset_count`,
`dhs_obc_watchdog_status`, `dhs_obc_health`, `aocs_mode`, and others with
`dtype: int`.

---

## Integration status (as of 2026-05-23)

All three gaps from the previous handoff are **closed and tested**:

| Gap | Status | Test |
|-----|--------|------|
| `get_tm_queue()` returned `[]` — TM not queued | **Fixed** | `test_get_tm_queue_returns_and_drains_parsed_packet` (SVF-DEV-159) |
| DHS HK fields hardcoded to 0.0 | **Fixed** — `_on_s3_25()` parses and updates all fields | `test_on_s3_25_updates_hk_ports` (SVF-DEV-160) |
| No sync-byte error recovery | **Fixed** — raises `RuntimeError` after `MAX_DESYNC=3` missed syncs | `test_consecutive_desync_raises_after_max_desync` (SVF-DEV-161) |

---

## Renode integration

Script: `opensvf/renode/zynqmp_obsw.resc`

```
machine LoadPlatformDescription @platforms/cpus/zynqmp.repl
sysbus LoadBinary @bin/obsw_zynqmp.bin 0x400000
emulation CreateServerSocketTerminal 3456 "term" false
```

opensvf connects via `OBCEmulatorAdapter(socket_addr=("localhost", 3456))`.
The binary must use the same wire protocol over the UART terminal.

---

## YAMCS ground system

opensvf auto-generates an XTCE mission database from the SRDB:
`opensvf/tools/generate_xtce.py` → `opensvf/yamcs/mdb/opensvf.xml`

TM downlink: TCP port 10015
TC uplink: UDP port 10025

---

## How to run a validation campaign against the real binary

```bash
# From opensvf root, with obsw_sim on PATH:
svf campaign mission_mysat1/campaigns/platform_campaign.yaml --report

# Or with Renode:
# 1. Start Renode: renode opensvf/renode/zynqmp_obsw.resc
# 2. Run campaign with socket mode (spacecraft.yaml obsw.type: socket)
```

---

## Key opensvf files to reference

| File | Purpose |
|------|---------|
| `src/svf/models/dhs/obc_emulator.py` | Wire protocol implementation |
| `src/svf/models/dhs/obc.py` | Software OBC stub (reference for expected behaviour) |
| `src/svf/models/dhs/hil_adapter.py` | HilAdapter ABC — interface both must satisfy |
| `src/svf/pus/services.py` | PUS S1/S3/S5/S17/S20 parsing logic |
| `mission_mysat1/spacecraft.yaml` | Equipment list and obsw.type setting |
| `mission_mysat1/campaigns/platform_campaign.yaml` | End-to-end validation entry point |
| `tests/system/test_obc_emulator.py` | System tests that run against real binary |
| `tests/unit/test_procedure_tc_tm.py` | Unit tests for TM queue, HK parsing, desync recovery |
