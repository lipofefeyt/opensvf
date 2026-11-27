# Abstraction layer

`SimulationMaster` drives a simulation through three interfaces, all in
`svf.core.abstractions`:

| Interface | Decides | Implementations |
|---|---|---|
| `TickSource` | when the next tick fires | `SoftwareTickSource`, `RealtimeTickSource` (`svf.sim.software_tick`) |
| `SyncProtocol` | how models acknowledge a tick | `DdsSyncProtocol` (`svf.ground.dds_sync`), `SharedMemorySyncProtocol` (`svf.ground.shm_sync`) |
| `ModelAdapter` | what one model does in a tick | `Equipment` and its subclasses (`svf.core`) |

Equipment models, procedures and campaigns only see the stores and their
ports, so swapping a tick source or a sync protocol does not change them.
`SpacecraftLoader` builds all of this from `spacecraft.yaml`; this page is for
building a simulation by hand.

## TickSource

```python
class TickSource(ABC):
    def start(self, on_tick: TickCallback, dt: float, stop_time: float) -> None: ...
    def stop(self) -> None: ...
```

- `SoftwareTickSource` ticks as fast as the models allow. Campaigns and tests
  use it.
- `RealtimeTickSource` aligns each tick to wall-clock time and logs a warning
  when a tick overruns `dt`. `spacecraft.yaml` selects it with
  `simulation.realtime: true`; the YAMCS demo and `svf console` use it.

## SyncProtocol

```python
class SyncProtocol(ABC):
    def reset(self) -> None: ...
    def publish_ready(self, model_id: str, t: float) -> None: ...
    def wait_for_ready(self, expected: list[str], timeout: float) -> bool: ...
```

Each model calls `publish_ready()` at the end of its tick; the master waits
for all of them with `wait_for_ready()` and stops the run with a
`SimulationError` when the sync timeout expires.

- `DdsSyncProtocol` publishes the acknowledgements on the Cyclone DDS topic
  `SVF/Sim/Ready` with `KEEP_ALL` history, so none is lost when models
  acknowledge in quick succession. It is the default.
- `SharedMemorySyncProtocol` keeps one byte per model in a POSIX shared
  memory segment and spin-waits on it, for low-latency runs. The master
  creates the segment (`create=True`, the default); another process attaches
  with `name=` and `create=False`.

## ModelAdapter and Equipment

```python
class ModelAdapter(ABC):
    model_id: str                                        # property
    def initialise(self, start_time: float = 0.0) -> None: ...
    def on_tick(self, t: float, dt: float) -> None: ...
    def suggested_dt(self) -> Optional[float]: ...       # default None
    def teardown(self) -> None: ...
```

`Equipment` (`svf.core.equipment`) implements `on_tick()` for every model:

1. take the pending CommandStore entries of its IN ports;
2. advance the time of the equipment fault engine;
3. call `do_step(t, dt)`;
4. write its OUT ports to the ParameterStore, time-stamped `t + dt`;
5. call `publish_ready()`.

```text
ModelAdapter
└── Equipment
    ├── NativeEquipment   a Python step function (most models in svf.models)
    ├── FmuEquipment      an FMI 2.0 co-simulation FMU (the dynamics model)
    ├── HilAdapter        the OBC models: ObcStub, OBCEmulatorAdapter, DualObcAdapter
    └── Bus               MIL-STD-1553B, SpaceWire, CAN (svf.bus)
```

`HilAdapter` (`svf.models.dhs.hil_adapter`) is the interface the OBC models
share, so a procedure sends TCs the same way to the stub and to real flight
software; `obsw.type` in `spacecraft.yaml` picks the implementation.

### NativeEquipment

A step function wrapped with its ports. Write the step function inside a
factory, so the port prefix derived from `equipment_id` is a closure
variable and two instances get distinct port names:

```python
--8<-- "docs/examples/abstraction-layer/native_equipment.py"
```

The models in `svf.models` follow this pattern; their ports are on the
[equipment](equipment.md) page.

### FmuEquipment

`FmuEquipment(fmu_path, equipment_id, sync_protocol, store, command_store,
parameter_map)` loads the FMU with FMPy. FMU inputs become IN ports and
outputs OUT ports; `parameter_map` renames FMU variables to SRDB names (for
example `{"battery_soc": "eps.battery.soc"}`). The committed FMUs are FMI
2.0; see [IF-2](icd.md#if-2-fmi-20-co-simulation).

## SimulationMaster

`SimulationMaster` (`svf.sim.simulation`) runs the tick loop. For each tick
at time `t` it:

1. resets the sync protocol;
2. injects the entries of the OBT parameter file that are due;
3. calls `on_tick(t, dt)` on every model, in list order, with `dt` the
   smallest of its own `dt` and any model's `suggested_dt()`;
4. waits for every model's acknowledgement (`sync_timeout`, 5 s by default,
   10 s from `spacecraft.yaml`);
5. applies the wiring: each connection's OUT port value is injected into the
   CommandStore under its IN port name;
6. writes `svf.sim_time`.

A model that raises is reported to `on_tick_error` as an
`EquipmentTickError` (`equipment_id`, `obt`, `cause`); the default handler
stops the run with a `SimulationError`. Pass another handler to record the
error and keep the other models ticking. `equipment_tick_timeout` bounds the
time of one model's tick.

With `seed=` every model gets a seed derived from it (SHA-256 of the seed and
the model ID), and the seeds are saved to `results/seed.json` so a run can
be replayed.

## Stores

**ParameterStore** (`svf.stores.parameter_store`), the TM side. OUT ports
write to it; procedures, the OBC models and the YAMCS bridge read it.

- `write(name, value, t, model_id)`, `read(name)` returns the last
  `ParameterEntry` (`value`, `t`, `model_id`) or `None`;
- `snapshot()`, `subscribe(name, callback)` (returns an unsubscribe
  function), `parameter_names()`.

**CommandStore** (`svf.stores.command_store`), the TC side. Procedures
(`ctx.inject()`), wiring, OBC models and bus adapters write to it; IN ports
consume it.

- `inject(name, value, t=..., source_id=...)`;
- `take(name, consumer=...)` reads and consumes an entry, `peek(name)`
  reads without consuming, `pending()` lists the names waiting.

Both are thread-safe. Given an SRDB (`ParameterStore(srdb=...)`,
`CommandStore(srdb=...)`) they log a warning, and do not raise, when a value
is outside its valid range or a TM parameter is written as a TC (or the
reverse). [IF-4](icd.md#if-4-srdb-parameter-contract) describes the SRDB.

## A simulation built by hand

The composition root that `SpacecraftLoader` writes for you, with two models
from `svf.models`. A unit test runs this file:

```python
--8<-- "docs/examples/abstraction-layer/composition_root.py"
```

To run it in real time, pass `RealtimeTickSource()`; for the shared-memory
sync, pass `SharedMemorySyncProtocol(model_ids=[...])` with the IDs of the
models. Nothing else changes.
