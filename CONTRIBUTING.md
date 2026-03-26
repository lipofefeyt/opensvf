# Contributing to OpenSVF

Thank you for your interest in contributing to OpenSVF. This guide covers the four main contribution paths: adding a new equipment model, writing a test procedure, defining a campaign, and contributing to the SVF platform itself.

---

## Development Setup

```bash
git clone https://github.com/lipofefeyt/opensvf
cd opensvf
pip install -e ".[dev]"
```

Verify everything works:

```bash
testosvf     # run full test suite
checkcov     # verify requirement coverage
```

---

## Code Standards

- **Type annotations** everywhere — `mypy` strict mode must pass (`checkosvf`)
- **Tests for everything** — every new test must have `@pytest.mark.requirement()`
- **No test without a requirement** — if you need a test, define the requirement first
- **SRDB canonical names** for all parameters — `domain.subsystem.parameter`
- **Conventional commits** — `feat:`, `fix:`, `refactor:`, `docs:`, `chore:`

---

## Adding a New Equipment Model

Equipment models are the core building blocks of SVF simulations. There are two approaches depending on your needs.

### Option A — NativeEquipment (Python only)

Best for simple models or when you want full Python control:

```python
from svf.native_equipment import NativeEquipment
from svf.equipment import PortDefinition, PortDirection

def rw_step(eq: NativeEquipment, t: float, dt: float) -> None:
    if eq.read_port("power_enable") > 0.5:
        speed = eq.read_port("speed") + eq.read_port("torque_cmd") * dt * 100.0
        eq.write_port("speed", min(speed, 6000.0))
    else:
        eq.write_port("speed", 0.0)

rw = NativeEquipment(
    equipment_id="rw1",
    ports=[
        PortDefinition("power_enable", PortDirection.IN),
        PortDefinition("torque_cmd",   PortDirection.IN,  unit="Nm"),
        PortDefinition("speed",        PortDirection.OUT, unit="rpm"),
    ],
    step_fn=rw_step,
    sync_protocol=sync,
    store=store,
    command_store=cmd_store,
)
```

### Option B — FmuEquipment (FMI 3.0)

Best for physics-heavy models or when sharing models with other simulation tools. Author FMUs in Python using pythonfmu:

```python
# models/ReactionWheelFmu.py
from pythonfmu import Fmi2Slave, Real

class ReactionWheelFmu(Fmi2Slave):
    author = "your_name"
    description = "Reaction wheel model"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.power_enable: float = 0.0
        self.torque_cmd: float = 0.0
        self.speed: float = 0.0
        self._speed: float = 0.0

        self.register_variable(Real("power_enable", causality="input",
                                    variability="continuous", start=0.0))
        self.register_variable(Real("torque_cmd", causality="input",
                                    variability="continuous", start=0.0))
        self.register_variable(Real("speed", causality="output",
                                    variability="continuous"))

    def do_step(self, t: float, dt: float) -> bool:
        if self.power_enable > 0.5:
            self._speed += self.torque_cmd * dt * 100.0
            self._speed = min(self._speed, 6000.0)
        else:
            self._speed = 0.0
        self.speed = self._speed
        return True
```

Build the FMU:

```bash
python3 -m pythonfmu build -f models/ReactionWheelFmu.py --dest models/
```

Wrap it as FmuEquipment with a parameter map:

```python
RW_MAP = {
    "power_enable": "aocs.rw1.power_enable",
    "torque_cmd":   "aocs.rw1.torque_cmd",
    "speed":        "aocs.rw1.speed",
}

rw = FmuEquipment(
    fmu_path="models/ReactionWheelFmu.fmu",
    equipment_id="rw1",
    sync_protocol=sync,
    store=store,
    command_store=cmd_store,
    parameter_map=RW_MAP,
)
```

### Add parameters to the SRDB

Add your equipment parameters to the appropriate domain baseline in `srdb/baseline/`:

```yaml
# srdb/baseline/aocs.yaml
  aocs.rw1.speed:
    description: Reaction wheel 1 speed
    unit: rpm
    dtype: float
    classification: TM
    domain: AOCS
    model_id: rw1
    valid_range: [-6000.0, 6000.0]
    pus:
      apid: 0x101
      service: 3
      subservice: 25
      parameter_id: 0x2020

  aocs.rw1.torque_cmd:
    description: Reaction wheel 1 torque command
    unit: Nm
    dtype: float
    classification: TC
    domain: AOCS
    model_id: rw1
    valid_range: [-0.2, 0.2]
    pus:
      apid: 0x101
      service: 20
      subservice: 1
      parameter_id: 0x2021
```

### Add requirements

Add equipment-specific requirements to `REQUIREMENTS.md` under the relevant functional area — or create a new one (e.g. `[RW]` for reaction wheel):

```
**RW-001** `[RW]` `BASELINED`
ReactionWheelFmu speed shall increase when power_enable > 0.5 and torque_cmd > 0.

**RW-002** `[RW]` `BASELINED`
ReactionWheelFmu speed shall be 0.0 when power_enable = 0.0.
```

### Write equipment tests

Add tests to `tests/equipment/` or `tests/spacecraft/`:

```python
@pytest.mark.requirement("RW-001")
def test_rw_speed_increases_when_enabled(rw: FmuEquipment) -> None:
    rw.receive("aocs.rw1.power_enable", 1.0)
    rw.receive("aocs.rw1.torque_cmd", 0.1)
    rw.do_step(0.0, 1.0)
    assert rw.read_port("aocs.rw1.speed") > 0.0
```

---

## Writing a Test Procedure

Test procedures live in `tests/spacecraft/`. Each test procedure:
- Uses the `svf_session` fixture
- Declares the FMU configuration via marks
- Uses SRDB canonical parameter names
- References at least one requirement

```python
@pytest.mark.svf_fmus([FmuConfig("models/ReactionWheelFmu.fmu", "rw1", RW_MAP)])
@pytest.mark.svf_stop_time(30.0)
@pytest.mark.svf_dt(0.1)
@pytest.mark.svf_initial_commands([
    ("aocs.rw1.power_enable", 1.0),
    ("aocs.rw1.torque_cmd", 0.1),
])
@pytest.mark.requirement("RW-001")
def test_rw_spins_up(svf_session) -> None:
    """
    TC-RW-001: Reaction wheel spins up when enabled.

    Preconditions: power_enable=1.0, torque_cmd=0.1Nm
    Expected: speed exceeds 100 rpm within 30s
    """
    svf_session.observe("aocs.rw1.speed").exceeds(100.0).within(30.0)
    svf_session.stop()
```

### Available marks

| Mark | Description |
|---|---|
| `svf_fmus([FmuConfig(...)])` | FMU equipment list with parameter map |
| `svf_dt(float)` | Simulation timestep in seconds |
| `svf_stop_time(float)` | Maximum simulation time in seconds |
| `svf_initial_commands([(name, value)])` | Commands injected before simulation starts |
| `svf_command_schedule([(t, name, value)])` | Commands fired at specific simulation time |
| `requirement(*ids)` | Requirement IDs verified by this test |

### Observable API

```python
# Assert parameter reaches a value within a time window
svf_session.observe("aocs.rw1.speed").exceeds(100.0).within(30.0)
svf_session.observe("aocs.rw1.speed").drops_below(10.0).within(10.0)
svf_session.observe("aocs.rw1.speed").reaches(500.0).within(60.0)
svf_session.observe("aocs.rw1.speed").satisfies(lambda v: 100 < v < 6000).within(30.0)

# Read current value directly
entry = svf_session.store.read("aocs.rw1.speed")
assert entry is not None
assert entry.value > 0.0

# Inject mid-test command
svf_session.inject("aocs.rw1.torque_cmd", 0.0)

# Stop simulation early once conditions are met
svf_session.stop()
```

---

## Defining a Campaign

Campaigns live in `campaigns/`. A campaign defines an ordered set of test procedures against a model baseline:

```yaml
campaign_id: AOCS-VAL-001
description: AOCS reaction wheel validation campaign
svf_version: "0.1"
model_baseline: aocs_rw_v1

requirements:
  - RW-001
  - RW-002

test_cases:
  - id: TC-RW-001
    test: tests/spacecraft/test_rw.py::test_rw_spins_up
    timeout: 60

  - id: TC-RW-002
    test: tests/spacecraft/test_rw.py::test_rw_stops_when_disabled
    timeout: 30
```

Run it:

```bash
svf run campaigns/aocs_rw_validation.yaml
```

View the report:

```bash
runcampaign campaigns/aocs_rw_validation.yaml
```

---

## Contributing to the SVF Platform

### Branching

```
main        — always green, tagged for releases
feat/xxx    — feature branches
fix/xxx     — bug fixes
```

### Before submitting a PR

```bash
checkosvf   # mypy strict — must be clean
testosvf    # full test suite — must be green
checkcov    # requirement coverage — no unexpected gaps
```

### Adding a new SVF-DEV requirement

1. Add the requirement to `REQUIREMENTS.md` with status `BASELINED`
2. Write the implementation
3. Write a test with `@pytest.mark.requirement("SVF-DEV-xxx")`
4. Verify `checkcov` shows no unexpected gaps
5. Update the traceability index in `REQUIREMENTS.md`

### Commit message format

```
feat(area): short description

Longer explanation if needed.

Closes #issue_number
Implements: SVF-DEV-xxx, EQP-xxx
```

---

## Questions

Open an issue on GitHub. Tag it with the appropriate label:
- `type: feature` — new capability
- `type: bug` — something broken
- `type: docs` — documentation improvement
- `type: spike` — research or investigation needed