# Interfaces (ICD)

The external interfaces of opensvf. For each one this page says what opensvf
does at the interface. Where another project owns the definition, the page
links to it instead of copying it.

| ID | Interface | Counterpart | Owner of the definition |
|---|---|---|---|
| IF-1 | OBSW wire protocol | openobsw (`obsw_sim`, Renode, hardware UART) | openobsw |
| IF-2 | FMI 2.0 co-simulation | opensvf-kde (`SpacecraftDynamics.fmu`) | FMI 2.0 standard; ports: opensvf |
| IF-3 | YAMCS TM/TC | YAMCS 5.12.6 | opensvf |
| IF-4 | SRDB parameter contract | all components | opensvf (its baseline); openobsw (its SRDB) |

## IF-1: OBSW wire protocol

--8<-- "docs/_gen/openobsw-links.md"

The protocol version and frame size this opensvf version speaks are on the
[compatibility](compatibility.md) page. This section describes what
`OBCEmulatorAdapter` does on the link.

### Frames

Each frame is a type byte, a big-endian `uint16` body length, and the body.

| Type | Direction | Body |
|---|---|---|
| `0x01` | opensvf to OBSW | One PUS-C TC space packet (not a transfer frame) |
| `0x02` | opensvf to OBSW | Sensor frame (`obsw_sensor_frame_t`) |
| `0x03` | OBSW to opensvf | Actuator frame (`obsw_actuator_frame_t`) |
| `0x04` | OBSW to opensvf | One PUS-C TM space packet |

The OBSW answers every frame it receives with one bare `0xFF` byte (no
length, no body) after the frames that frame produced.

### Transports

| | Pipe | Socket | Serial |
|---|---|---|---|
| OBSW | `obsw_sim` as a subprocess (stdin/stdout) | Renode UART terminal over TCP | Hardware UART |
| `spacecraft.yaml` | `obsw.type: pipe`, `obsw.binary` | `obsw.type: socket`, `obsw.host`, `obsw.port` (default 3456) | Python API only: `OBCEmulatorAdapter(serial_port=..., baud_rate=...)`, needs `opensvf[uart]` |
| Sync timeout | 10 s from YAML, 5 s by default in the API | 10 s from YAML | 5 s by default |
| Start-up check | The banner must name wire protocol v4, else the adapter refuses to start; no banner gives a warning | none | none |
| aarch64 | `obsw_sim` for aarch64 runs under QEMU, detected with `file(1)` | n/a | n/a |

### One tick

In each `do_step()` the adapter:

1. sends the sensor frame;
2. sends the TCs of this tick, in this order: the TCs from the port commands
   below, then every TC queued with `receive_tc()` (by procedures, the
   console or YAMCS) since the last tick. Nothing is sent when nothing is
   queued: there is no automatic heartbeat;
3. reads frames until the `0xFF` for the sensor frame, within the sync
   timeout, then one more `0xFF` per TC frame, within 1 s each;
4. decodes the TM packets it read and updates its OUT ports.

More than 4 TCs in one tick log a warning: the openobsw FreeRTOS TMTC queue
holds 4 and drops the rest.

**Order of the replies.** The host sim sends a TC's TM, then the actuator
frame, then `0xFF`, so TM arrives in the tick of its TC. The STM32H7
FreeRTOS image sends `0xFF` right after queueing a TC, before the PUS task
has run it, so its TM can arrive after that `0xFF` and is then decoded in a
later tick.

**Lost sync.** A tick without `0xFF` counts as a desync in the link health.
Three in a row raise `RuntimeError("Lost sync ...")` with the last lines the
sim wrote to stderr. If the sim has exited, the adapter raises at once with
its exit status and those lines instead, and records the status in the link
health (`obsw_exit_status`), so a crash is not reported as telemetry loss.

### Sensor frame sources

`OBCEmulatorAdapter` fills the sensor frame from the ParameterStore. The
`*_valid` flags are the status ports thresholded at 0.5.

| Sensor frame field | Source | Notes |
|---|---|---|
| `mag_x/y/z` | `aocs.mag.field_x/y/z` | Magnetometer model measurement |
| `mag_valid` | `aocs.mag.status` | |
| `st_q_w/x/y/z` | `aocs.str1.quaternion_w/x/y/z` | Star tracker model |
| `st_valid` | `aocs.str1.validity` | |
| `gyro_x/y/z` | `aocs.gyro.rate_x/y/z` | Gyroscope model measurement |
| `gyro_valid` | `aocs.gyro.status` | |
| `sim_time` | the tick time `t` | |
| `obc_temperature_raw` | `dhs.obc_thermal.temperature_raw` | `obc_thermal` model; rounded and clamped to int16; host sim only |
| `thermal_valid` | `dhs.obc_thermal.status` | 0 when there is no `obc_thermal` model, so openobsw keeps its own value |

### Actuator frame sinks

The adapter writes the actuator frame into the CommandStore:

| Actuator frame field | CommandStore name |
|---|---|
| `mtq_x/y/z` | `aocs.mtq.dipole_x/y/z` |
| `rw_torque_x/y/z` | `aocs.rw1.torque_cmd`, `aocs.rw2.torque_cmd`, `aocs.rw3.torque_cmd` |

### TCs the adapter builds

TCs are built with `PusTcBuilder`: APID `0x010` by default (the `apid`
argument), the TC APID openobsw's telecommands use; a running sequence
count; a CRC-16 Packet Error Control field. openobsw accepts any TC APID.
Procedures send their own TCs with `ctx.tc(service, subservice, data)`.

--8<-- "docs/_gen/icd-adapter-tcs.md"

`dhs.obc.mode_cmd` uses the housekeeping mode encoding (0 STANDBY, 1 SAFE,
2 NOMINAL), not the S8 function ID.

### TM the adapter decodes

openobsw TM has no Packet Error Control field; with `tm_pec=True` the
adapter expects one. The TM header time (`PusTmPacket.timestamp`) carries
the OBSW's OBT in whole seconds on the host sim and on STM32H7 FreeRTOS.

**S1 verification.** TM(1,1), (1,7) and failures (1,2), (1,8) are counted
in the link health per failure code:

--8<-- "docs/_gen/icd-s1-codes.md"

**S3 housekeeping.** Each TM(3,25) report is decoded with its set layout
from `src/svf/data/srdb/hk_sets.yaml`: the set ID (`uint8`) then the
parameters in order, big-endian. Each value is written raw to the
ParameterStore as `dhs.obc.<parameter>`. A report whose length does not match
its layout is not decoded and makes the link unhealthy (`hk_undecoded`).
`checkcons` check 9 compares the layouts with openobsw's SRDB.

--8<-- "docs/_gen/icd-hk-sets.md"

Set 3 is the source of the OBC mode, OBT and the other `dhs.obc.*` OUT
ports (`dhs.obc.mode`, `dhs.obc.obt`, `dhs.obc.watchdog_status`,
`dhs.obc.memory_used_pct`, `dhs.obc.health`, `dhs.obc.reset_count`,
`dhs.obc.cpu_load`). Against `obsw_sim` `dhs.obc.watchdog_status` stays 0:
the host sim never lets its watchdog expire.

**S5 mode events.** An event in any severity subtype with one of these IDs
sets `dhs.obc.mode` until the next set 3 report, which is the authoritative
mode and overrides it. `obc_mode` and the link health mode timeline record
set 3 reports only. The host sim and STM32H7 FreeRTOS emit one event per
transition, without auxiliary data. `checkcons` check 8 compares the table
with openobsw's events.

--8<-- "docs/_gen/icd-s5-mode-events.md"

## IF-2: FMI 2.0 co-simulation

`FmuEquipment` wraps an FMI 2.0 co-simulation FMU as an equipment model. In
each tick it sets the FMU inputs from its IN ports, calls `doStep`, and reads
the outputs into its OUT ports. The FMU must not advance time on its own.

The reference plant is `SpacecraftDynamics.fmu` from opensvf-kde, built into
the `dynamics` model (`make_kde_equipment()`); its ports are listed on the
[equipment](equipment.md#dynamics) page. Both FMUs are committed in
`models/`:

| File | Used by |
|---|---|
| `models/SpacecraftDynamics.fmu` | `dynamics` model, L3 and L4 tests |
| `models/SimpleCounter.fmu` | L2 integration tests |

## IF-3: YAMCS ground station

`YamcsBridge` connects a running simulation to YAMCS.

| Stream | Protocol | Port | Direction |
|---|---|---|---|
| TM downlink | TCP | 10015 | opensvf to YAMCS |
| TC uplink | UDP | 10025 | YAMCS to opensvf |
| Web UI | HTTP | 8090 | browser to YAMCS (`scripts/start-yamcs.sh`) |

| File | Purpose |
|---|---|
| `yamcs/etc/yamcs.yaml` | Instance list, web UI |
| `yamcs/etc/yamcs.opensvf.yaml` | Data links, mission database, streams |
| `yamcs/etc/processor.yaml` | Realtime processor |
| `yamcs/mdb/opensvf.xml` | XTCE mission database |

The mission database is generated from the SRDB by
`tools/generate_xtce.py`; its packets, parameters and commands are listed on
the [YAMCS mission database](yamcs-mdb.md) page. SRDB TM parameters appear
there with `.` replaced by `_` (`aocs.mag.field_x` is `aocs_mag_field_x`).

## IF-4: SRDB parameter contract

Every parameter that crosses a component boundary has one canonical name,
`<domain>.<subsystem>.<parameter>` (for example `aocs.mag.field_x`), defined
in `srdb/baseline/*.yaml`. The ParameterStore and CommandStore are keyed by
these names, and wiring connects an OUT port to an IN port with the same
name. A baseline entry gives the description, unit, data type, TM or TC
classification, domain, owning model, an optional valid range and an
optional PUS mapping.

The parameters, events and telecommands of the flight software are defined
by openobsw's SRDB (links above). opensvf keeps the subset it decodes, the
housekeeping set layouts, in `src/svf/data/srdb/hk_sets.yaml`.

`checkcons` checks that the two sides agree; given `--obsw` it also reads
the openobsw sources. Its checks:

--8<-- "docs/_gen/icd-checkcons.md"

Run `checkcons` before a pull request that touches the SRDB, the wire
protocol or sensor model port names.
