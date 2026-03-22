# SVF Abstraction Layer

> **Status:** Draft — v0.1
> **Last updated:** 2026-03

---

## Purpose

The abstraction layer is the mechanism that makes SVF real-time switchable
without architectural surgery. The SimulationMaster depends exclusively on
three abstract interfaces — never on concrete implementations. Swapping from
software to real-time execution is a one-line change at the composition root.

---

## The Three Interfaces

### TickSource (`src/svf/abstractions.py`)

Answers the question: **when is the next tick?**
```python
class TickSource(ABC):
    def start(self, on_tick: TickCallback, dt: float, stop_time: float) -> None: ...
    def stop(self) -> None: ...
```

The master calls `start()` and provides a callback. Whenever a tick occurs,
the callback is invoked with the current simulation time `t`. The master never
advances time on its own — it always waits for the TickSource.

| Implementation | Behaviour |
|---|---|
| `SoftwareTickSource` | Python while loop, runs as fast as hardware allows |
| `RealtimeTickSource` *(deferred)* | RT_PREEMPT timer or external hardware sync pulse |

---

### SyncProtocol (`src/svf/abstractions.py`)

Answers the question: **are all models done with this tick?**
```python
class SyncProtocol(ABC):
    def wait_for_ready(self, expected: list[str], timeout: float) -> bool: ...
    def publish_ready(self, model_id: str, t: float) -> None: ...
    def reset(self) -> None: ...
```

After broadcasting a tick, the master calls `wait_for_ready()` and blocks
until every registered model has called `publish_ready()`. This is the
lockstep barrier — nobody advances until everyone crosses the line.

`reset()` is called before each tick to drain stale acknowledgements.

| Implementation | Behaviour |
|---|---|
| `DdsSyncProtocol` | Acknowledgements over DDS `SVF/Sim/Ready` topic |
| `SharedMemorySyncProtocol` *(deferred)* | Lock-free ring buffer, sub-millisecond latency |

---

### ModelAdapter (`src/svf/abstractions.py`)

Answers the question: **how do I drive a model?**
```python
class ModelAdapter(ABC):
    @property
    def model_id(self) -> str: ...
    def initialise(self, start_time: float = 0.0) -> None: ...
    def on_tick(self, t: float, dt: float) -> dict[str, float]: ...
    def teardown(self) -> None: ...
```

Every model — FMU, Python class, or future hardware bridge — looks identical
to the master through this interface. The master never knows what is underneath.

| Implementation | Behaviour |
|---|---|
| `FmuModelAdapter` | Wraps an FMI 3.0 FMU via fmpy |
| `NativeModelAdapter` | Wraps a plain Python class for lightweight testing |
| Hardware adapter *(deferred)* | Bridges DDS topics to physical interfaces |

---

## Concrete Implementations

### SoftwareTickSource (`src/svf/software_tick.py`)

The default TickSource for software-only simulation runs. Advances time in a
simple Python while loop, calling `on_tick(t)` at each step before incrementing
`t` by `dt`. No real-time guarantees — runs as fast as the hardware allows.

`round(..., 9)` is applied to both `t` and `stop_time` comparisons to prevent
floating point drift from causing missed stop conditions over long runs.

---

### DdsSyncProtocol (`src/svf/dds_sync.py`)

Exchanges tick acknowledgements over the DDS topic `SVF/Sim/Ready`. Each model
publishes a `SimReady(model_id, t)` message when it finishes processing a tick.
The master reads all `SimReady` messages and blocks until it has seen one from
every expected model or the timeout expires.

`reset()` drains the reader before each tick to prevent stale acknowledgements
from a previous tick being counted toward the current one.

---

### FmuModelAdapter (`src/svf/fmu_adapter.py`)

Wraps an FMI 3.0 FMU as a ModelAdapter. Handles FMU loading, initialisation,
stepping via `fmu.doStep()`, output reading, optional CSV logging, and teardown.
The adapter does not own the simulation loop — it only responds to ticks
driven from outside by the SimulationMaster.

Each adapter instance has a unique `model_id` that identifies it in sync
acknowledgements and log output.

---

### NativeModelAdapter (`src/svf/native_adapter.py`)

Wraps any plain Python class that implements the `NativeModel` protocol:
```python
class MyModel:
    def step(self, t: float, dt: float) -> dict[str, float]:
        return {"value": t * 2.0}
```

No inheritance required — the class just needs a `step()` method with the
right signature. Primarily useful for writing fast unit tests without
loading a full FMU.

---

## Execution Flow
```
SimulationMaster.run()
    │
    ├── initialise all ModelAdapters
    │
    └── SoftwareTickSource.start(on_tick, dt, stop_time)
            │
            └── on_tick(t):
                    ├── SyncProtocol.reset()
                    ├── for each ModelAdapter:
                    │       └── adapter.on_tick(t, dt)
                    │               ├── fmu.doStep()
                    │               ├── publish outputs → SVF/Telemetry/{name}
                    │               └── SyncProtocol.publish_ready(model_id, t)
                    └── SyncProtocol.wait_for_ready(all_model_ids, timeout)
```

---

## Real-Time Upgrade Path

The upgrade path is explicit and bounded. Each step is a one-line change
at the composition root where SimulationMaster is constructed:
```python
# Software (default)
master = SimulationMaster(
    tick_source=SoftwareTickSource(),
    sync_protocol=DdsSyncProtocol(participant),
    models=[FmuModelAdapter("power.fmu", "power")],
    dt=0.1,
)

# Real-time (future — change only these two lines)
master = SimulationMaster(
    tick_source=RealtimeTickSource(clock_source="/dev/pps0"),
    sync_protocol=SharedMemorySyncProtocol(),
    models=[FmuModelAdapter("power.fmu", "power")],
    dt=0.1,
)
```

The SimulationMaster, ModelAdapters, test procedures, and campaign definitions
are identical in both cases.

---

## Adding a New Implementation

To add a new TickSource (e.g. driven by a GPS pulse-per-second signal):

1. Create `src/svf/gps_tick.py`
2. Subclass `TickSource` and implement `start()` and `stop()`
3. Inject it at the composition root — nothing else changes

The same pattern applies to new SyncProtocol and ModelAdapter implementations.

---

## Related

- `docs/architecture.md` — system-level architecture and design principles
- `REQUIREMENTS.md` — SVF-DEV-009 through SVF-DEV-018 cover this layer
- `src/svf/abstractions.py` — interface definitions
