# Architecture

opensvf runs a spacecraft simulation in closed loop with the flight software
under test, and turns test procedures into a campaign report with
requirement traceability. It connects four components:

| Component | What it is | Interface |
|---|---|---|
| opensvf (this repository) | Python: simulation master, equipment models, PUS stack, campaign runner | |
| openobsw | C11 flight software, the software under test | wire protocol ([IF-1](icd.md#if-1-obsw-wire-protocol)) |
| opensvf-kde | C++ 6-DOF dynamics, built as an FMI 2.0 FMU | FMI ([IF-2](icd.md#if-2-fmi-20-co-simulation)) |
| YAMCS 5.12.6 | Ground station: TM display, TC uplink | PUS over TCP/UDP ([IF-3](icd.md#if-3-yamcs-ground-station)) |

## Entry points

| Command | Does |
|---|---|
| `svf validate spacecraft.yaml` | Checks a configuration without starting DDS or loading models |
| `svf check spacecraft.yaml` | Loads the configuration in full (DDS, models) without running it |
| `svf run spacecraft.yaml` | Runs the simulation to `stop_time` |
| `svf campaign campaign.yaml --report` | Runs a campaign; writes `results/<campaign>_report.html` |
| `svf console spacecraft.yaml` | Runs in real time and takes operator commands (ping, mode, OBT, HK) |
| `svf profiles` | Lists the bundled hardware profiles |

The same from Python:

```python
from pathlib import Path

from svf.campaign.campaign_runner import CampaignRunner
from svf.campaign.reporter import generate_html_report
from svf.config.spacecraft import SpacecraftLoader

SpacecraftLoader.load("spacecraft.yaml").run()          # one simulation

report = CampaignRunner.from_yaml("campaign.yaml").run()  # a campaign
generate_html_report(report, Path("results/campaign_report.html"))
```

To build a simulation without `spacecraft.yaml`, see
[abstraction layer](abstraction-layer.md#a-simulation-built-by-hand).

## Closed loop

```text
 YAMCS 5.12.6 (optional)
     |  TM over TCP 10015, TC over UDP 10025
 YamcsBridge
     |  ParameterStore / TC queue
 OBC model, selected by obsw.type
     stub    ObcStub rule engine, no flight software
     pipe    OBCEmulatorAdapter + obsw_sim (aarch64 under QEMU)
     socket  OBCEmulatorAdapter + Renode UART on TCP 3456
     |  wire protocol: sensor frame and TCs in, actuator frame and TM out
 openobsw flight software
     |  actuator frame -> CommandStore (MTQ dipoles, RW torques)
 Actuator models: magnetorquer, reaction wheels, thruster
     |  magnetorquer torque (reaction wheel torque is not fed back yet)
 Dynamics: the opensvf-kde FMU (the dynamics model, 6-DOF)
     |  true rates, attitude, field
 Environment: SGP4 orbit, dipole B-field, eclipse, solar flux
     |
 Sensor models: magnetometer, gyroscope, star tracker, CSS, GPS
     |  noisy measurements -> sensor frame
 (back to the OBC model)
```

EPS (solar array, battery, PCDU), thermal and TT&C (S-band transponder)
models run in the same loop. Bus adapters (MIL-STD-1553B, SpaceWire with RMAP, CAN 2.0B) can carry
parameters between models, with bus-level fault injection. Every model and
its ports are on the [equipment](equipment.md) page.

Each tick, `SimulationMaster` steps every model in order, waits for their
acknowledgements, applies the wiring and publishes `svf.sim_time`; the
[abstraction layer](abstraction-layer.md#simulationmaster) page has the
details. What the OBC model does on the wire in a tick is in the
[ICD](icd.md#one-tick).

## PUS services

`svf.pus` builds TCs and decodes TM for these services; procedures, the
console and the YAMCS bridge use them:

--8<-- "docs/_gen/pus-services.md"

## Spacecraft configuration

```yaml
version: 1
spacecraft: MySat-1

obsw:
  type: pipe              # stub | pipe | socket
  binary: bin/obsw_sim    # pipe: relative to this file
  # host: localhost       # socket
  # port: 3456            # socket (required)

equipment:
  - id: mag1
    model: magnetometer
    hardware_profile: mag_default
    seed: 42              # optional, per model

buses:                    # optional: mil1553 | spacewire | can
  - id: aocs_bus
    type: mil1553
    # ...

wiring:
  auto: true              # connect OUT and IN ports with the same name
  overrides:             # names differ, so auto-wiring cannot match these
    - from: pcdu.eps.pcdu.charge_current
      to:   battery.eps.battery.charge_current

simulation:
  dt: 0.1
  stop_time: 300.0
  seed: 42
  realtime: false         # true: RealtimeTickSource
```

Port names are SRDB canonical names (`aocs.mag.field_x`), so auto-wiring
connects most of a spacecraft; overrides handle the rest.
`mission_mysat1/` has complete configurations: `spacecraft.yaml` (stub),
`spacecraft_hil.yaml` (pipe), `spacecraft_with_buses.yaml`.

## Hardware profiles

A hardware profile is a YAML file of physical constants for one equipment
(noise, limits, timings). `hardware_profile: <name>` in `spacecraft.yaml`
loads one of the profiles bundled with the package (`svf profiles` lists
them). A model factory called from Python also takes `hardware_dir=`, which is
searched first; the `obsw-srdb` package, when installed, is searched last.
`mission_mysat1/hardware_profiles/` holds a copy of the bundled profiles;
`checkcons` check 6 keeps the two in step.

## Procedures and campaigns

A procedure is a `Procedure` subclass (`svf.campaign.procedure`) with an
`id`, a `title`, the `requirement` it verifies and a `run(ctx)` method. The
`ProcedureContext` it gets can inject commands (`inject`), send TCs (`tc`,
`schedule_tc`), wait in simulation time (`wait`) or on a condition
(`wait_until`), wait for TM (`expect_tm`), assert on parameters
(`assert_parameter`, `monitor`), inject equipment faults
(`inject_equipment_fault`) and bring the OBC to NOMINAL (`ensure_nominal`).
[Integrate your flight software](integrate-obsw.md#a-first-campaign) has a
complete example that CI runs.

A campaign YAML names the spacecraft, the procedure files and the
requirements the campaign is responsible for. Each procedure runs against a
fresh simulation. Its verdict is PASS, FAIL, ERROR or INCONCLUSIVE; a PASS
on an OBSW link that dropped TM or lost sync becomes FAIL. The HTML report
lists the verdicts, the steps and the declared requirements no procedure
covered; `--json` writes the same results with the link health and step
events.

## Checks

| Command | Checks |
|---|---|
| `svf validate` | Duplicate equipment IDs, bus address conflicts, wiring references, the OBT parameter file |
| `checkcov` | Every BASELINED requirement in `REQUIREMENTS.md` has a test in `results/traceability.txt` (written by the last pytest run), and the equipment fidelity levels |
| `checkcons` | opensvf against its own SRDB and against openobsw (below) |
| `tools/gen_docs.py` | The generated reference pages against their sources, and every `svf` import shown in these docs |

`checkcons` runs these checks; with `--obsw <openobsw checkout>` it also
reads the openobsw sources (CI runs it against the pinned release):

--8<-- "docs/_gen/icd-checkcons.md"

## Roadmap

The milestones and the roadmap are kept in one place, the
[README](https://github.com/lipofefeyt/opensvf/blob/main/README.md#roadmap).
