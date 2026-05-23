# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

OpenSVF is a Python spacecraft Software Validation Facility. It drives a closed-loop simulation across three independent components:

- **opensvf** (this repo) — Python orchestration, equipment models, PUS stack, campaign runner
- **opensvf-kde** — external C++/Eigen3 6-DOF physics engine, packaged as an FMI 2.0 FMU (`SpacecraftDynamics.fmu`)
- **openobsw** — external C11 flight software (PUS services, b-dot, ADCS PD, FDIR), runs as a subprocess (pipe) or under Renode (socket)

The dev container expects `openobsw` and `opensvf-kde` mounted as sibling workspaces at `/workspace/`.

## Common commands

```bash
pip install -e ".[dev]"           # install package + dev deps

testosvf                          # full pytest suite (~453 tests)
testosvf tests/unit/test_xxx.py   # extra args are forwarded to pytest
checkosvf                         # mypy --strict over src/
checkcov                          # requirement coverage + equipment fidelity (F1-F4)
checkcons                         # 7-check cross-repo SRDB consistency

svf validate <spacecraft.yaml>    # fast pre-flight check (no DDS, no FMU, no model imports)
svf check    <spacecraft.yaml>    # full config load (DDS + models), no run
svf run      <spacecraft.yaml>    # run a simulation
svf campaign <campaign.yaml> --report   # run + emit results/<name>_report.html
svf profiles                      # list bundled hardware profiles

bash scripts/start-yamcs.sh       # YAMCS 5.12.6 ground station on :8090
bash scripts/stop-yamcs.sh
```

Run a single test: `pytest tests/unit/test_spacecraft_loader.py::test_xxx -v`. `tests/system/` is excluded by default (`norecursedirs` in `pyproject.toml`) — invoke those files explicitly when needed.

**Non-standard pytest class discovery**: `pyproject.toml` sets `python_classes = ["*Suite", "*Tests"]`. Test classes must end in `Suite` or `Tests` (e.g. `class MagnetometerSuite:`). Classes named `TestFoo` are silently ignored.

CI (`.github/workflows/ci.yml`) runs `pytest tests/` on Ubuntu/Python 3.12 plus a Renode ZynqMP job on push to main that pulls the OBSW binary artifact from the openobsw repo.

## Architecture

### Validation pyramid

| Level | Needs | Scope |
|---|---|---|
| L1 unit | nothing | equipment physics, bus logic, stores, PUS packets |
| L2 integration | `SimpleCounter.fmu` | wiring, FmuEquipment adapter, SimulationMaster |
| L3 system | `SpacecraftDynamics.fmu` + `obsw_sim` binary | full SIL with flight software in loop |
| L4 campaign | mission `spacecraft.yaml` | operator procedures, HTML verdict report |

CI covers L1+L2 only; L3/L4 need external binaries.

### Core abstractions (`src/svf/core/`)

`SimulationMaster` drives ticks against three pluggable interfaces:
- `TickSource` — when the next tick fires (`SoftwareTickSource` vs `RealtimeTickSource`; `Equipment.suggested_dt()` lets models request a smaller step)
- `SyncProtocol` — how models acknowledge a tick (`DdsSyncProtocol` over CycloneDDS)
- `Equipment` — base class implemented by either `NativeEquipment` (pure-Python closures) or `FmuEquipment` (FMI 2.0 adapter)

All reference models in `src/svf/models/` are `NativeEquipment` factories. `FmuEquipment` is reserved for operator-supplied external physics and the KDE dynamics FMU. FMU binaries (`SimpleCounter.fmu`, `SpacecraftDynamics.fmu`) are committed to `models/` at the repo root; integration tests reference them via `Path(__file__).parent.parent.parent / "models" / "SimpleCounter.fmu"`.

### Three OBC modes (`src/svf/models/dhs/`)

Same `HilAdapter` ABC, three implementations selected by `obsw.type` in `spacecraft.yaml`:

- `stub` — `ObcStub` rule engine (no binary, no wire protocol)
- `pipe` — `OBCEmulatorAdapter` runs `obsw_sim` as a subprocess over stdin/stdout
- `socket` — `OBCEmulatorAdapter` connects to Renode UART terminal at TCP `localhost:3456`

`pipe` and `socket` both use **wire protocol v3** (type-prefixed, big-endian length, 0xFF end-of-tick sync). See [OBSW_CONTEXT.md](OBSW_CONTEXT.md) for the full frame layouts — the C reference lives in `contrib/svf_protocol/` of the openobsw repo. Struct sizes are verified against C layouts by `checkcons` check [1/7].

### Stores and SRDB

`ParameterStore` (telemetry) and `CommandStore` (commands) are keyed by **SRDB canonical parameter names** of the form `domain.subsystem.parameter` (e.g. `aocs.mag1.field_x`). Auto-wiring in `src/svf/config/wiring.py` connects OUT→IN ports when the names match.

The SRDB baseline lives in `srdb/baseline/*.yaml` (one file per domain: aocs, eps, dhs, thermal, ttc, obdh). Adding a new parameter means: add to the baseline YAML, add an SRDB-aware equipment port, and write a test marked `@pytest.mark.requirement(...)`. `checkcons` check [7/7] catches OUT ports that don't appear in the baseline; check [4/7] catches sensor model port renames that would silently produce zeros on the OBSW side.

### Two test APIs

There are two distinct ways to write tests — pick based on level:

- **L2 integration tests** (`tests/integration/`): use the `svf_session` fixture and `FmuConfig` from `src/svf/plugin/fixtures.py`. Decorate with `@pytest.mark.svf_fmus(...)`, `@pytest.mark.svf_dt(...)`, etc. These run inside pytest directly.
- **L4 campaign procedures** (`mission_mysat1/procedures/` or user-defined): subclass `Procedure` from `src/svf/campaign/procedure.py` and use `ProcedureContext`. Run via `svf campaign`. These are operator-level test scripts, not pytest tests.

`@pytest.mark.requirement` belongs on L1/L2 pytest tests; campaign procedures declare their requirement via the `requirement = "ID"` class attribute.

### Campaign runner (`src/svf/campaign/`)

`CampaignRunner` loads a `campaign.yaml`, instantiates a spacecraft from `SpacecraftLoader`, runs each `Procedure` subclass, and emits PASS/FAIL/INCONCLUSIVE/ERROR verdicts. `reporter.generate_html_report` produces a self-contained HTML report (no CDN) with a requirement coverage table. The pytest plugin (`src/svf/plugin/__init__.py`) writes `results/traceability.txt` after every run by scanning `@pytest.mark.requirement` markers.

### YAMCS bridge

`scripts/start-yamcs.sh` downloads YAMCS 5.12.6 on first run. The XTCE MDB is generated from the SRDB by `tools/generate_xtce.py` → `yamcs/mdb/opensvf.xml`. TM downlink is TCP 10015, TC uplink is UDP 10025; UI on `:8090` (`admin`/`password`).

## Conventions

- **No test without a requirement.** Every test must carry `@pytest.mark.requirement("ID")` where `ID` exists in `REQUIREMENTS.md` (or `mission_mysat1/requirements.md` for mission tests). `checkcons` check [5/7] enforces this.
- **mypy strict** is non-negotiable. `checkosvf` must be clean before a PR. `tools/` is excluded.
- **SRDB canonical names everywhere** — never invent ad-hoc parameter strings.
- **Conventional commits** (`feat:`, `fix:`, `refactor:`, `docs:`, `chore:`); commit body lists `Implements: SVF-DEV-xxx` for requirement traceability.
- **Pre-PR ritual**: `checkosvf && testosvf && checkcov && checkcons`.

