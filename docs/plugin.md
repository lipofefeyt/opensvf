# SVF pytest Plugin

> **Status:** v0.4
> **Last updated:** 2026-04
> **Author:** lipofefeyt

---

## Overview

The SVF pytest plugin provides the test orchestration layer. It starts a `SimulationMaster` in a background thread before each test, provides fixtures for commanding and observation, and generates ECSS-compatible verdicts with full requirements traceability.

The plugin is fully compatible with `pytest-xdist` for parallel test execution.

---

## Registration

The plugin is registered as a `pytest11` entry point in `pyproject.toml`:

```toml
[project.entry-points."pytest11"]
svf = "svf.plugin"
```

It is automatically active in any project that has `opensvf` installed.

---

## Marks Reference

| Mark | Type | Default | Description |
|---|---|---|---|
| `svf_fmus([FmuConfig(...)])` | list | SimpleCounter.fmu | FMU equipment list |
| `svf_dt(float)` | float | 0.1 | Simulation timestep (s) |
| `svf_stop_time(float)` | float | 2.0 | Maximum simulation time (s) |
| `svf_initial_commands([(name, value)])` | list | [] | Commands injected before first tick |
| `svf_command_schedule([(t, name, value)])` | list | [] | Commands fired at simulation time t |
| `requirement(*ids)` | varargs | — | Requirement IDs verified by this test |

### FmuConfig

```python
@dataclass
class FmuConfig:
    fmu_path: str
    model_id: str
    parameter_map: Optional[dict[str, str]] = None
```

---

## svf_session Fixture

The `svf_session` fixture starts the simulation and provides the test interface:

```python
def test_my_procedure(svf_session) -> None:
    # observe a parameter
    svf_session.observe("eps.battery.soc").exceeds(0.88).within(120.0)

    # inject a command mid-test
    svf_session.inject("eps.solar_array.illumination", 0.0)

    # read a value directly
    entry = svf_session.store.read("eps.battery.soc")
    assert entry is not None
    assert entry.value > 0.5

    # stop simulation early
    svf_session.stop()
```

### Fixture lifecycle

```
pytest collects test
    → svf_session fixture starts
        → SimulationMaster created with marks configuration
        → svf_initial_commands injected into CommandStore
        → svf_command_schedule scheduler thread started
        → SimulationMaster.run() started in background thread
    → test function executes (observables poll ParameterStore)
    → test function returns
        → SimulationMaster torn down
        → DDS participant closed explicitly (via DdsSyncProtocol.close())
        → verdict recorded
```

---

## Observable API

Observables poll the `ParameterStore` while the simulation runs. They fail-fast when the simulation thread exits.

### Conditions

```python
# Exceeds a threshold
svf_session.observe("aocs.rw1.speed").exceeds(500.0).within(30.0)

# Drops below a threshold (returns value at crossing)
svf_session.observe("eps.battery.soc").drops_below(0.75).within(120.0)

# Reaches an exact value (with tolerance)
svf_session.observe("dhs.obc.mode").reaches(1.0).within(5.0)

# Custom condition
svf_session.observe("aocs.str1.validity").satisfies(
    lambda v: v > 0.5
).within(15.0)
```

### Timeout

`within(N)` specifies real wall-clock seconds. For long simulations use `SimulationMaster` directly:

```python
# For fast simulations — observables
svf_session.observe("eps.battery.soc").exceeds(0.88).within(30.0)

# For long simulations — run master directly
master, store, cmd_store = make_eps_system(stop_time=600.0)
master.run()
soc = store.read("eps.battery.soc")
assert soc.value < 0.55
```

---

## svf_command_schedule

Schedules commands to fire at specific simulation times:

```python
@pytest.mark.svf_fmus([FmuConfig("models/EpsFmu.fmu", "eps", EPS_MAP)])
@pytest.mark.svf_stop_time(180.0)
@pytest.mark.svf_dt(1.0)
@pytest.mark.svf_initial_commands([
    ("eps.solar_array.illumination", 1.0),
    ("eps.load.power", 30.0),
])
@pytest.mark.svf_command_schedule([
    (60.0,  "eps.solar_array.illumination", 0.0),  # eclipse at t=60s
    (120.0, "eps.solar_array.illumination", 1.0),  # sun return at t=120s
])
@pytest.mark.requirement("EPS-011", "EPS-012")
def test_eclipse_cycle(svf_session) -> None:
    """Battery charges, enters eclipse, then recovers."""
    svf_session.observe("eps.battery.soc").exceeds(0.85).within(60.0)
    svf_session.observe("eps.battery.charge_current").drops_below(0.0).within(65.0)
    svf_session.observe("eps.battery.charge_current").exceeds(0.0).within(125.0)
    svf_session.stop()
```

---

## Parallel Execution (pytest-xdist)

The plugin is fully compatible with `pytest-xdist`:

```bash
pytest tests/ -n 4 --dist=worksteal
```

### xdist compatibility notes

`Mark` objects are not serialised across xdist worker processes. The plugin collects requirement IDs from `item.user_properties` (strings) rather than from `item.own_markers` directly, avoiding the `execnet` serialisation error.

Each worker process runs its own DDS participant. DDS participants are explicitly closed via `DdsSyncProtocol.close()` in `SimulationMaster._teardown()` — no reliance on garbage collection.

Worker processes run a final `gc.collect()` in `pytest_sessionfinish` as belt-and-suspenders cleanup.

### Performance

Parallel speedup depends on the test type. Unit tests with no DDS are highly parallel. Tests with DDS discovery (50ms sleep) have limited speedup due to I/O overhead. The main benefit of parallel execution is for long-running campaign suites and Monte Carlo runs.

---

## Deterministic Replay

Every `SimulationMaster` run logs its seed to `results/seed.json`:

```
SVF seed: 809481067  (replay with seed=809481067)
```

Per-model seeds are derived deterministically:

```python
seed_for_model = int.from_bytes(SHA256(f"{master}:{model_id}")[:4], "big")
```

Replay any run exactly:

```python
master = SimulationMaster(..., seed=809481067)
master.run()  # identical noise, identical results
```

---

## ECSS Verdict Mapping

| pytest outcome | ECSS Verdict |
|---|---|
| Passed | PASS |
| Failed (AssertionError) | FAIL |
| Error (infrastructure) | ERROR |
| Neither | INCONCLUSIVE |

---

## Requirements Traceability

### Marking tests

```python
@pytest.mark.requirement("EPS-011", "SVF-DEV-063")
def test_battery_charges_in_sunlight(svf_session) -> None:
    ...
```

### Traceability matrix

Generated automatically after every test run to `results/traceability.txt`:

```
SVF Requirements Traceability Matrix
============================================================
Requirement          Verdict      Test Case
------------------------------------------------------------
EPS-011              PASS         test_tc_pwr_001_battery_charges_in_sunlight
OBC-005              PASS         test_obc_watchdog_reset_on_double_timeout
SVF-DEV-060          PASS         test_bridge_sends_tm_to_yamcs
------------------------------------------------------------
Total requirements covered: 97
```

### JUnit XML enrichment

```xml
<testcase name="test_tc_pwr_001_battery_charges_in_sunlight">
  <properties>
    <property name="ecss_verdict" value="PASS"/>
    <property name="requirement" value="EPS-011"/>
    <property name="requirement" value="SVF-DEV-063"/>
  </properties>
</testcase>
```

### Coverage check

```bash
checkcov   # cross-references BASELINED requirements vs traceability matrix
```

---

## Session Teardown

DDS lifecycle is managed explicitly — no reliance on garbage collection:

```python
# SimulationMaster._teardown()
for model in self._models:
    model.teardown()

# Close DDS explicitly — prevents corrupted double-linked list crash
if hasattr(self._sync_protocol, "close"):
    self._sync_protocol.close()
```

`conftest.py` adds a final GC sweep as a fallback:

```python
def pytest_sessionfinish(session, exitstatus):
    import gc
    gc.collect()
    gc.collect()
    gc.collect()
```