# SVF pytest Plugin

> **Status:** v0.3
> **Last updated:** 2026-03
> **Author:** lipofefeyt

---

## Overview

The SVF pytest plugin provides the test orchestration layer. It starts a `SimulationMaster` in a background thread before each test, provides fixtures for commanding and observation, and generates ECSS-compatible verdicts with full requirements traceability.

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
        → DDS participant cleaned up
        → verdict recorded
```

---

## Observable API

Observables poll the `ParameterStore` while the simulation runs. They fail-fast when the simulation thread exits.

### Conditions

```python
# Exceeds a threshold
svf_session.observe("aocs.rw1.speed").exceeds(500.0).within(30.0)

# Drops below a threshold
svf_session.observe("eps.battery.soc").drops_below(0.75).within(120.0)

# Reaches an exact value (with tolerance)
svf_session.observe("dhs.obc.mode").reaches(1.0).within(5.0)

# Custom condition
svf_session.observe("aocs.str1.validity").satisfies(
    lambda v: v > 0.5
).within(15.0)
```

### Timeout

`within(N)` specifies real wall-clock seconds. For long simulations (e.g. 600s EPS eclipse) use the direct `SimulationMaster` pattern instead of observables:

```python
# For fast simulations — use observables
svf_session.observe("eps.battery.soc").exceeds(0.88).within(30.0)

# For long simulations — run master directly and check store
master, store, cmd_store = make_eps_system(stop_time=600.0)
master.run()
soc = store.read("eps.battery.soc")
assert soc.value < 0.55
```

---

## svf_command_schedule

Schedules commands to fire at specific simulation times. The scheduler polls `svf.sim_time` from `ParameterStore` and injects commands when `sim_t >= target_t`.

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

### Bus fault injection via schedule

```python
@pytest.mark.svf_command_schedule([
    (10.0, "bus.platform_1553.fault.rt5.no_response", 5.0),
])
@pytest.mark.requirement("1553-007")
def test_rw_fault_recovery(svf_session) -> None:
    """1553 NO_RESPONSE fault on RT5 for 5s then clears."""
    svf_session.observe("aocs.rw1.speed").drops_below(10.0).within(12.0)
    svf_session.observe("aocs.rw1.speed").exceeds(50.0).within(30.0)
    svf_session.stop()
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

Every test must declare at least one requirement:

```python
@pytest.mark.requirement("EPS-011", "SVF-DEV-063")
def test_battery_charges_in_sunlight(svf_session) -> None:
    ...
```

Multiple requirements can be declared. A test verifies all of them.

### Traceability matrix

Generated automatically after every test run to `results/traceability.txt`:

```
SVF Requirements Traceability Matrix
============================================================
Requirement          Verdict      Test Case
------------------------------------------------------------
EPS-011              PASS         test_tc_pwr_001_battery_charges_in_sunlight
OBC-005              PASS         test_obc_watchdog_reset_on_double_timeout
ST-003               PASS         test_tc_st_fail_001_sun_blinding_drops_validity
...
------------------------------------------------------------
Total requirements covered: 95
```

### JUnit XML enrichment

Every test case in the JUnit XML output includes:
- `ecss_verdict`: PASS / FAIL / ERROR / INCONCLUSIVE
- `requirement`: one property per requirement ID

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

Reports any BASELINED requirement without a passing test.

---

## Writing Test Procedures

### Minimal example

```python
@pytest.mark.svf_fmus([FmuConfig("models/EpsFmu.fmu", "eps", EPS_MAP)])
@pytest.mark.svf_stop_time(30.0)
@pytest.mark.svf_dt(1.0)
@pytest.mark.requirement("EPS-011")
def test_battery_charges(svf_session) -> None:
    """Battery SoC increases in full sunlight."""
    svf_session.observe("eps.battery.soc").exceeds(0.88).within(30.0)
    svf_session.stop()
```

### Multi-phase example

```python
@pytest.mark.svf_fmus([FmuConfig("models/EpsFmu.fmu", "eps", EPS_MAP)])
@pytest.mark.svf_stop_time(180.0)
@pytest.mark.svf_dt(1.0)
@pytest.mark.svf_initial_commands([("eps.solar_array.illumination", 1.0)])
@pytest.mark.svf_command_schedule([
    (60.0,  "eps.solar_array.illumination", 0.0),
    (120.0, "eps.solar_array.illumination", 1.0),
])
@pytest.mark.requirement("EPS-011", "EPS-012")
def test_eclipse_cycle(svf_session) -> None:
    """Charge → eclipse → discharge → sun return → recovery."""
    svf_session.observe("eps.battery.soc").exceeds(0.85).within(60.0)
    svf_session.observe("eps.battery.charge_current").drops_below(0.0).within(65.0)
    svf_session.observe("eps.battery.charge_current").exceeds(0.0).within(125.0)
    svf_session.stop()
```

### Long simulation (no observable)

For simulations where the observable polling is too slow:

```python
@pytest.mark.requirement("EPS-007")
def test_battery_deep_discharge() -> None:
    """Battery reaches minimum SoC in extended eclipse."""
    master, store, _ = make_eps_system(stop_time=600.0, illumination=0.0)
    master.run()
    soc = store.read("eps.battery.soc")
    assert soc is not None
    assert soc.value < 0.55
```

---

## Campaign Integration

Campaigns run test procedures via `pytest.main()` internally:

```bash
svf run campaigns/eps_validation.yaml
```

Each test case runs in isolation. Per-test timeouts are enforced via `pytest-timeout`. Results are collected into a `CampaignRecord` and rendered to `results/{campaign_id}/report.html`.

---

## Session Teardown

DDS participants are cleaned up via `pytest_sessionfinish` in `conftest.py`:

```python
def pytest_sessionfinish(session, exitstatus):
    import gc
    gc.collect()
```

This prevents the `corrupted double-linked list` abort that occurs when DDS C library objects are garbage-collected in the wrong order during pytest shutdown.