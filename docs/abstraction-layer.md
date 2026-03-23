# SVF Abstraction Layer

> **Status:** Draft — v0.2
> **Last updated:** 2026-03
> **Author>** lipofefeyt

---

## Purpose

The abstraction layer is the mechanism that makes SVF real-time switchable
without architectural surgery. The SimulationMaster depends exclusively on
three abstract interfaces — never on concrete implementations. Swapping from
software to real-time execution is a one-line change at the composition root.

A key design rule: **models speak for themselves.** The SimulationMaster
never publishes telemetry or sync acknowledgements on behalf of models.
Each ModelAdapter is responsible for its own outputs and readiness signals.

---

## The Three Interfaces

### TickSource (src/svf/abstractions.py)

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
| SoftwareTickSource | Python while loop, runs as fast as hardware allows |
| RealtimeTickSource (deferred) | RT_PREEMPT timer or external hardware sync pulse |

---

### SyncProtocol (src/svf/abstractions.py)

Answers the question: **are all models done with this tick?**

```python
class SyncProtocol(ABC):
    def wait_for_ready(self, expected: list[str], timeout: float) -> bool: ...
    def publish_ready(self, model_id: str, t: float) -> None: ...
    def reset(self) -> None: ...
```

After each tick, the master calls `wait_for_ready()` and blocks until every
model has called `publish_ready()` on the SyncProtocol it was given at
construction. The master never calls `publish_ready()` itself.

`reset()` is called before each tick to drain stale acknowledgements.

| Implementation | Behaviour |
|---|---|
| DdsSyncProtocol | Acknowledgements over DDS SVF/Sim/Ready topic, KEEP_ALL QoS |
| SharedMemorySyncProtocol (deferred) | Lock-free ring buffer, sub-millisecond latency |

---

### ModelAdapter (src/svf/abstractions.py)

Answers the question: **how do I drive a model?**

```python
class ModelAdapter(ABC):
    @property
    def model_id(self) -> str: ...
    def initialise(self, start_time: float = 0.0) -> None: ...
    def on_tick(self, t: float, dt: float) -> None: ...
    def teardown(self) -> None: ...
```

Every model looks identical to the master through this interface.
on_tick() returns None — data flows over DDS, exceptions flow up the
call stack. Each adapter is responsible for:
- Executing its model
- Publishing outputs to SVF/Telemetry/{variable}
- Calling sync_protocol.publish_ready() when done

| Implementation | Behaviour |
|---|---|
| FmuModelAdapter | Wraps an FMI 3.0 FMU via fmpy |
| NativeModelAdapter | Wraps a plain Python class for lightweight testing |
| Hardware adapter (deferred) | Bridges DDS topics to physical interfaces |

---

## Concrete Implementations

### SoftwareTickSource (src/svf/software_tick.py)

The default TickSource for software-only simulation runs. Advances time in a
simple Python while loop, calling `on_tick(t)` at each step before incrementing
`t` by `dt`. No real-time guarantees — runs as fast as the hardware allows.

`round(..., 9)` is applied to prevent floating point drift over long runs.

---

### DdsSyncProtocol (src/svf/dds_sync.py)

Exchanges tick acknowledgements over the DDS topic SVF/Sim/Ready.
Uses KEEP_ALL QoS to ensure no acknowledgement is lost when multiple
models publish concurrently.

`reset()` drains the reader before each tick to prevent stale acknowledgements
from a previous tick being counted toward the current one.

---

### FmuModelAdapter (src/svf/fmu_adapter.py)

Wraps an FMI 3.0 FMU as a ModelAdapter.

On each tick:
1. Calls fmu.doStep(t, dt)
2. Reads all output variables
3. Publishes each to SVF/Telemetry/{variable} as a TelemetrySample
4. Optionally records to CsvLogger
5. Calls sync_protocol.publish_ready()

Output variable names are discovered at initialise() time from the FMU
model description. One DDS DataWriter is created per output variable.

---

### NativeModelAdapter (src/svf/native_adapter.py)

Wraps any plain Python class implementing the NativeModel protocol:

```python
class MyModel:
    def step(self, t: float, dt: float) -> dict[str, float]:
        return {"value": t * 2.0}
```

Output variable names must be declared explicitly at construction time:

```python
adapter = NativeModelAdapter(
    model=MyModel(),
    model_id="my_model",
    output_names=["value"],    # declared upfront — never inferred
    participant=participant,
    sync_protocol=sync,
)
```

This avoids calling step() during initialise(), which would cause
side effects in recording models and corrupt step counts.

---

## Execution Flow

```
SimulationMaster.run()
    |
    +-- initialise all ModelAdapters
    |
    +-- SoftwareTickSource.start(on_tick, dt, stop_time)
            |
            +-- on_tick(t):
                    +-- SyncProtocol.reset()
                    +-- for each ModelAdapter:
                    |       +-- adapter.on_tick(t, dt)
                    |               +-- model.step() / fmu.doStep()
                    |               +-- publish SVF/Telemetry/{name}
                    |               +-- SyncProtocol.publish_ready(model_id, t)
                    +-- SyncProtocol.wait_for_ready(all_model_ids, timeout)
```

Note: on_tick() returns None. All data flows over DDS topics.
Faults flow up as exceptions and are caught by the master.

---

## Real-Time Upgrade Path

Each step is a one-line change at the composition root:

```python
# Software (default)
master = SimulationMaster(
    tick_source=SoftwareTickSource(),
    sync_protocol=DdsSyncProtocol(participant),
    models=[FmuModelAdapter("power.fmu", "power", participant, sync)],
    dt=0.1,
)

# Real-time (future — change only these two lines)
master = SimulationMaster(
    tick_source=RealtimeTickSource(clock_source="/dev/pps0"),
    sync_protocol=SharedMemorySyncProtocol(),
    models=[FmuModelAdapter("power.fmu", "power", participant, sync)],
    dt=0.1,
)
```

The SimulationMaster, ModelAdapters, test procedures, and campaign
definitions are identical in both cases.

---

## Adding a New Implementation

To add a new TickSource (e.g. driven by a GPS pulse-per-second signal):

1. Create src/svf/gps_tick.py
2. Subclass TickSource and implement start() and stop()
3. Inject it at the composition root — nothing else changes

The same pattern applies to new SyncProtocol and ModelAdapter implementations.

---

## Related

- docs/architecture.md — system-level architecture and design principles
- docs/plugin.md — pytest plugin built on top of these abstractions
- REQUIREMENTS.md — SVF-DEV-009 through SVF-DEV-018
- src/svf/abstractions.py — interface definitions
