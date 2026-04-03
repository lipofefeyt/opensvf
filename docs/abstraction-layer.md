# SVF Abstraction Layer

> **Status:** v0.3
> **Last updated:** 2026-03
> **Author:** lipofefeyt

---

## Overview

The SVF abstraction layer defines three interfaces that decouple the simulation core from its execution environment. Switching from software simulation to real-time execution is a one-line change at the composition root — the equipment models, test procedures, and campaign manager are unaffected.

---

## 1. TickSource

Controls the simulation clock.

```python
class TickSource(ABC):
    @abstractmethod
    def start(self) -> None: ...

    @abstractmethod
    def stop(self) -> None: ...
```

### SoftwareTickSource

Default implementation. Ticks as fast as the CPU allows. Used in all current test procedures and campaigns.

```python
from svf.software_tick import SoftwareTickSource
tick = SoftwareTickSource()
```

### RealtimeTickSource (M11)

Drives the simulation at wall-clock rate using `RT_PREEMPT` timer. Required for hardware-in-the-loop with real equipment.

---

## 2. SyncProtocol

Coordinates tick synchronisation between `SimulationMaster` and equipment models. Each model acknowledges readiness after completing its tick.

```python
class SyncProtocol(ABC):
    @abstractmethod
    def reset(self) -> None: ...

    @abstractmethod
    def publish_ready(self, model_id: str, t: float) -> None: ...

    @abstractmethod
    def wait_for_ready(
        self, expected: list[str], timeout: float
    ) -> bool: ...
```

### DdsSyncProtocol

Default implementation using Eclipse Cyclone DDS.

- `SVF/Sim/Tick` topic — master broadcasts tick with `(t, dt)`
- `SVF/Sim/Ready/{model_id}` topic — each model acknowledges

```python
from cyclonedds.domain import DomainParticipant
from svf.dds_sync import DdsSyncProtocol

participant = DomainParticipant()
sync = DdsSyncProtocol(participant)
```

All DDS writers/readers use `KEEP_ALL` QoS to ensure late-joining models receive the last tick.

### SharedMemorySyncProtocol (M11)

Lock-free ring buffer for zero-copy inter-process synchronisation. Required for real-time HIL.

---

## 3. ModelAdapter

The minimal interface that any model must implement to be driven by `SimulationMaster`.

```python
class ModelAdapter(ABC):
    @property
    @abstractmethod
    def model_id(self) -> str: ...

    @abstractmethod
    def initialise(self, start_time: float = 0.0) -> None: ...

    @abstractmethod
    def on_tick(self, t: float, dt: float) -> None: ...

    @abstractmethod
    def teardown(self) -> None: ...
```

### Equipment extends ModelAdapter

`Equipment` is the primary `ModelAdapter` implementation. Every spacecraft model extends `Equipment` and is directly driveable by `SimulationMaster` without any adapter wrapping.

```
ModelAdapter (ABC)
    └── Equipment (ABC)
            ├── FmuEquipment     — wraps FMI 3.0 FMU
            ├── NativeEquipment  — wraps Python step function
            └── Bus (ABC)        — fault injection + typed ports
                    └── Mil1553Bus
```

### FmuEquipment

Wraps an FMI 3.0 FMU. Translates FMU variables to SRDB canonical port names via `parameter_map`.

```python
from svf.fmu_equipment import FmuEquipment

eps = FmuEquipment(
    fmu_path="models/EpsFmu.fmu",
    equipment_id="eps",
    sync_protocol=sync,
    store=store,
    command_store=cmd_store,
    parameter_map={
        "battery_soc":        "eps.battery.soc",
        "solar_illumination": "eps.solar_array.illumination",
    },
)
```

`on_tick()` behaviour:
1. Read `CommandStore` entries into FMU inputs
2. `fmu.doStep(t, dt)`
3. Write FMU outputs to `ParameterStore`
4. `sync.publish_ready()`

### NativeEquipment

Wraps a Python step function. Ports declared explicitly at construction.

```python
from svf.native_equipment import NativeEquipment
from svf.equipment import PortDefinition, PortDirection

def rw_step(eq: NativeEquipment, t: float, dt: float) -> None:
    torque = eq.read_port("aocs.rw1.torque_cmd")
    speed  = eq.read_port("aocs.rw1.speed")
    eq.write_port("aocs.rw1.speed", speed + torque * 100.0 * dt)

rw = NativeEquipment(
    equipment_id="rw1",
    ports=[
        PortDefinition("aocs.rw1.torque_cmd", PortDirection.IN,  unit="Nm"),
        PortDefinition("aocs.rw1.speed",       PortDirection.OUT, unit="rpm"),
    ],
    step_fn=rw_step,
    sync_protocol=sync,
    store=store,
    command_store=cmd_store,
)
```

---

## 4. SimulationMaster

Drives the tick loop. Accepts any list of `ModelAdapter` instances.

```python
from svf.simulation import SimulationMaster

master = SimulationMaster(
    tick_source=SoftwareTickSource(),
    sync_protocol=sync,
    models=[obc, ttc, bus, rw, st, sbt],
    dt=0.1,
    stop_time=30.0,
    sync_timeout=5.0,
    command_store=cmd_store,
    param_store=store,
)
master.run()
```

### Tick loop

```
for each tick at t:
  1. ParameterStore.write("svf.sim_time", t)
  2. For each model: model.on_tick(t, dt)
  3. Wait for all ready signals (timeout=sync_timeout)
  4. Apply WiringMap (copy OUT port values to connected IN ports)
  5. svf_command_schedule: fire any commands at t >= target_t
  t += dt
```

### WiringMap

Optional. Defines point-to-point connections between OUT and IN ports. Applied after each tick via `CommandStore.inject()`.

```python
from svf.wiring import WiringLoader

loader = WiringLoader({"solar_array": sa, "pcdu": pcdu})
wiring = loader.load(Path("srdb/wiring/eps_wiring.yaml"))

master = SimulationMaster(..., wiring=wiring)
```

---

## 5. Stores

### ParameterStore (TM)

Thread-safe key-value store for telemetry. Written by Equipment OUT ports. Read by observables, loggers, and OBC HK aggregation.

```python
from svf.parameter_store import ParameterStore

store = ParameterStore()
store.write("eps.battery.soc", 0.85, t=1.0, model_id="eps")
entry = store.read("eps.battery.soc")
# entry.value, entry.t, entry.model_id
snapshot = store.snapshot()  # dict[str, ParameterEntry]
```

Properties:
- Thread-safe (`threading.Lock`)
- Late-joiner safe — `read()` returns last value regardless of when called
- SRDB validation when `Srdb` instance attached — warns on range violation

### CommandStore (TC)

Thread-safe key-value store for telecommands. Written by `inject()`, wiring, OBC S20 routing, bus BC_to_RT routing. Read by Equipment IN ports via `take()` (atomic read+consume).

```python
from svf.command_store import CommandStore

cmd_store = CommandStore()
cmd_store.inject("aocs.rw1.torque_cmd", 0.1, source_id="test")
entry = cmd_store.take("aocs.rw1.torque_cmd")  # atomic, returns None if empty
entry = cmd_store.peek("aocs.rw1.torque_cmd")  # non-consuming read
```

Properties:
- Thread-safe
- `take()` is atomic — read and consume in one operation
- `peek()` for test assertions without consuming
- SRDB validation — warns when TC-classified parameter injected to TM key

---

## 6. SRDB Integration

The SRDB provides runtime validation for both stores.

```python
from svf.srdb.loader import SrdbLoader

loader = SrdbLoader()
for baseline in Path("srdb/baseline").glob("*.yaml"):
    loader.load_baseline(baseline)
srdb = loader.build()

store     = ParameterStore(srdb=srdb)
cmd_store = CommandStore(srdb=srdb)
```

Validation warnings (never raise — simulation continues):
- Value outside `valid_range`
- Model writes to TC-classified parameter
- Test injects to TM-classified parameter

---

## 7. Dependency Injection Summary

The composition root for a full platform simulation:

```python
# 1. Infrastructure
participant = DomainParticipant()
sync        = DdsSyncProtocol(participant)
store       = ParameterStore()
cmd_store   = CommandStore()

# 2. Equipment
obc = ObcEquipment(config, sync, store, cmd_store)
ttc = TtcEquipment(obc,    sync, store, cmd_store)
rw  = make_reaction_wheel( sync, store, cmd_store)
st  = make_star_tracker(   sync, store, cmd_store)
sbt = make_sbt(            sync, store, cmd_store)
bus = Mil1553Bus("platform_1553", rt_count=5,
                 mappings=mappings,
                 sync_protocol=sync,
                 store=store,
                 command_store=cmd_store)

# 3. Simulation
master = SimulationMaster(
    tick_source=SoftwareTickSource(),   # ← swap for RealtimeTickSource (M11)
    sync_protocol=sync,                 # ← swap for SharedMemorySync (M11)
    models=[ttc, obc, bus, rw, st, sbt],
    dt=0.1,
    stop_time=30.0,
    sync_timeout=5.0,
    command_store=cmd_store,
    param_store=store,
)
master.run()
```

Switching to real-time execution (M11): change `SoftwareTickSource` to `RealtimeTickSource` and `DdsSyncProtocol` to `SharedMemorySyncProtocol`. Everything else is unchanged.