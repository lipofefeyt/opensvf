# SVF pytest Plugin

> **Status:** Draft — v0.1
> **Last updated:** 2026-03
> **Author>** lipofefeyt

---

## Purpose

The SVF pytest plugin turns the simulation infrastructure into a test tool.
It provides three things to test procedures:

1. **svf_session fixture** — starts a SimulationMaster before the test, tears it down after
2. **Observable assertion API** — fluent time-bounded telemetry assertions over DDS
3. **ECSS verdict mapper** — maps pytest outcomes to ECSS-compatible verdicts

The plugin is registered as a pytest11 entry point and is automatically
available to any project that installs opensvf — no configuration required.

---

## Quick Start

```python
# tests/test_power_model.py
import pytest
from svf.plugin.fixtures import FmuConfig

@pytest.mark.svf_fmus([FmuConfig("models/power.fmu", "power")])
@pytest.mark.svf_stop_time(10.0)
def test_battery_charges(svf_session):
    svf_session.observe("battery_voltage").exceeds(3.3).within(5.0)
```

That's a complete SVF test procedure. No boilerplate, no manual wiring.

---

## svf_session Fixture

### What it does

Before the test body runs:
1. Reads configuration from pytest marks (or uses defaults)
2. Creates a DomainParticipant, DdsSyncProtocol, and FmuModelAdapter(s)
3. Builds a SimulationMaster and starts it in a background thread
4. Waits 100ms for the simulation to initialise
5. Yields a SimulationSession to the test

After the test body completes (pass, fail, or error):
1. Joins the background thread
2. Records the ECSS verdict
3. Logs teardown

Teardown is guaranteed even if the test raises an exception.

### Configuration marks

| Mark | Type | Default | Description |
|---|---|---|---|
| svf_fmus | list[FmuConfig] | SimpleCounter.fmu | FMUs to load into the simulation |
| svf_dt | float | 0.1 | Simulation timestep in seconds |
| svf_stop_time | float | 2.0 | Simulation stop time in seconds |

### SimulationSession

The object injected into the test as `svf_session`:

```python
@dataclass
class SimulationSession:
    observe:  ObservableFactory   # entry point for assertions
    verdicts: VerdictRecorder     # populated after test completes
    error:    Optional[Exception] # set if simulation faults

    def stop(self) -> None: ...   # signal early stop
```

### FmuConfig

```python
@dataclass
class FmuConfig:
    fmu_path: str | Path   # path to the .fmu file
    model_id: str          # unique ID within this simulation run
```

### Examples

```python
# Default — SimpleCounter FMU, dt=0.1, stop_time=2.0
def test_default(svf_session):
    svf_session.observe("counter").reaches(1.0).within(3.0)


# Custom stop time
@pytest.mark.svf_stop_time(0.5)
def test_short_run(svf_session):
    svf_session.observe("counter").reaches(0.4).within(2.0)


# Multiple FMUs
@pytest.mark.svf_fmus([
    FmuConfig("models/power.fmu", "power"),
    FmuConfig("models/thermal.fmu", "thermal"),
])
@pytest.mark.svf_stop_time(30.0)
def test_power_and_thermal(svf_session):
    svf_session.observe("battery_voltage").exceeds(3.3).within(10.0)
    svf_session.observe("panel_temperature").drops_below(80.0).within(20.0)


# Early stop
@pytest.mark.svf_stop_time(60.0)
def test_with_early_stop(svf_session):
    svf_session.observe("safe_mode_flag").reaches(1.0).within(30.0)
    svf_session.stop()  # no need to run the full 60s
```

---

## Observable Assertion API

### Overview

The observable API lets test procedures express time-bounded telemetry
conditions without writing polling loops. It subscribes to
SVF/Telemetry/{variable} DDS topics and blocks until the condition is
met or the timeout expires.

### Syntax

```
svf_session.observe(variable)
    .reaches(value)         → WithinClause
    .exceeds(threshold)     → WithinClause
    .drops_below(threshold) → WithinClause
    .satisfies(fn, desc)    → WithinClause

    .within(seconds)        → float   (the value that satisfied the condition)
```

### Methods

**reaches(value, tolerance=1e-6)**
Condition met when `abs(current - value) <= tolerance`.

```python
svf_session.observe("counter").reaches(1.0).within(2.0)
svf_session.observe("voltage").reaches(3.7, tolerance=0.01).within(5.0)
```

**exceeds(threshold)**
Condition met when `current > threshold`.

```python
svf_session.observe("battery_voltage").exceeds(3.3).within(5.0)
```

**drops_below(threshold)**
Condition met when `current < threshold`.

```python
svf_session.observe("temperature").drops_below(100.0).within(10.0)
```

**satisfies(condition, description)**
Condition met when the callable returns True.

```python
svf_session.observe("status").satisfies(
    lambda v: v in (1.0, 2.0),
    description="status is 1 or 2"
).within(3.0)
```

### Return value

All `.within()` calls return the float value that satisfied the condition.
This can be used for further assertions:

```python
final_voltage = svf_session.observe("battery_voltage").exceeds(3.3).within(5.0)
assert final_voltage < 4.2, f"Voltage too high: {final_voltage}"
```

### ConditionNotMet

If the timeout expires before the condition is met, `ConditionNotMet` is raised.
It is a subclass of `AssertionError`, so pytest treats it as a test failure
(FAIL verdict, not ERROR).

The error message includes the condition description and the last observed value:

```
ConditionNotMet: Observable condition not met within 2.0s:
counter reaches 999.0 (±1e-06) (last value: 1.0)
```

### Multiple observables in one test

Each variable gets its own DDS reader, created lazily on first use.
Observing multiple variables in sequence is fine:

```python
def test_full_sequence(svf_session):
    svf_session.observe("solar_power").exceeds(10.0).within(5.0)
    svf_session.observe("battery_soc").exceeds(0.8).within(30.0)
    svf_session.observe("safe_mode").reaches(0.0).within(60.0)
```

---

## ECSS Verdict Mapper

### Verdict enum

```python
class Verdict(enum.Enum):
    PASS         = "PASS"
    FAIL         = "FAIL"
    INCONCLUSIVE = "INCONCLUSIVE"
    ERROR        = "ERROR"
```

### Mapping

| pytest outcome | ECSS Verdict | Typical cause |
|---|---|---|
| Passed | PASS | All assertions met |
| Failed (AssertionError) | FAIL | Observable condition not met, or explicit assert |
| Error (other exception) | ERROR | Infrastructure fault, missing FMU, DDS error |
| Neither | INCONCLUSIVE | Test skipped or aborted before verdict |

### Accessing verdicts

```python
def test_something(svf_session):
    svf_session.observe("counter").reaches(1.0).within(2.0)
    # After test completes, check in teardown or a subsequent fixture:
    # svf_session.verdicts.get(test_id) -> Verdict.PASS
    # svf_session.verdicts.summary -> {"PASS": 1, "FAIL": 0, ...}
```

### VerdictRecorder

```python
recorder = VerdictRecorder()
recorder.record("TC-AOCS-001", Verdict.PASS)
recorder.get("TC-AOCS-001")   # -> Verdict.PASS
recorder.summary              # -> {"PASS": 1, "FAIL": 0, ...}
recorder.all                  # -> {"TC-AOCS-001": Verdict.PASS}
```

---

## Plugin Registration

The plugin is registered via the pytest11 entry point in pyproject.toml:

```toml
[project.entry-points."pytest11"]
svf = "svf.plugin"
```

This means any project that does `pip install opensvf` gets the
svf_session fixture and SVF marks available automatically — no
conftest.py or explicit plugin loading needed.

---

## Internal Architecture

```
src/svf/plugin/
├── __init__.py       <- pytest11 registration, hooks, public API
├── fixtures.py       <- svf_session, svf_participant, SimulationSession
├── observable.py     <- ObservableFactory, ReachesClause, WithinClause
└── verdict.py        <- Verdict, VerdictRecorder, verdict_from_pytest_outcome
```

### pytest_runtest_makereport hook

The __init__.py registers a hookwrapper that fires after each test call
phase. It attaches the test report to the item as _svf_rep. The
svf_session fixture reads this in teardown to determine the correct
ECSS verdict without needing to re-evaluate the outcome itself.

---

## Related

- docs/architecture.md — system-level architecture
- docs/abstraction-layer.md — TickSource, SyncProtocol, ModelAdapter interfaces
- REQUIREMENTS.md — SVF-DEV-040 through SVF-DEV-047
- src/svf/plugin/ — plugin source code
- tests/test_fixtures.py — fixture integration tests
- tests/test_observable.py — observable API tests
- tests/test_verdict.py — verdict mapper tests
