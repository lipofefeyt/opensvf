# MySat-1  -  Reference Mission

MySat-1 is the reference mission bundled with OpenSVF. It is a minimal 3U
CubeSat configuration designed to demonstrate the full validation workflow
from written requirements through test procedures to an HTML campaign report.

It runs entirely in **stub mode**  -  no compiled flight software binary or
FMU physics engine needed. Clone the repo and run the campaign immediately.

---

## Quickstart (60 seconds)

```bash
pip install -e ".[dev]"
svf campaign mission_mysat1/campaigns/quickstart_campaign.yaml --report
open results/quickstart_campaign_report.html
```

The report shows four PASS verdicts for AOCS requirements and four UNCOVERED
entries for EPS requirements  -  exactly where the gap is.

---

## Layout

```
mission_mysat1/
├── spacecraft.yaml              Spacecraft configuration (stub OBC, AOCS sensors)
├── requirements.md              Mission requirements (what we are validating)
│
├── campaigns/
│   ├── quickstart_campaign.yaml 4 AOCS procedures  -  run this first
│   ├── aocs_campaign.yaml       Full AOCS suite
│   ├── eps_campaign.yaml        EPS procedures (add EPS models first)
│   └── platform_campaign.yaml   OBC/PUS closed-loop scenarios
│
├── procedures/
│   ├── quickstart_procedures.py  4 clean demo procedures (start here)
│   ├── aocs_procedures.py        Extended AOCS tests
│   ├── eps_procedures.py         EPS tests (needs solar_array, battery models)
│   ├── dhs_fdir_procedures.py    FDIR / safe-mode scenarios
│   └── platform_procedures.py   PUS TC/TM closed-loop tests
│
├── hardware_profiles/           Per-unit physics constants (noise, limits, etc.)
└── wiring/                      Port connection maps (used by advanced campaigns)
```

---

## The validation workflow

OpenSVF follows a requirements → procedures → evidence chain:

### 1. Requirements (`requirements.md`)

Every procedure maps to exactly one requirement. The requirement is written
as a verifiable statement  -  something the simulation can either confirm or
refute.

```
MIS-AOCS-001: The AOCS sensor suite shall reach nominal status within
5 seconds of receiving a power-enable command.
```

### 2. Spacecraft configuration (`spacecraft.yaml`)

Declares which equipment models are in the simulation and how they connect.
MySat-1 uses stub OBC mode  -  the OBC is rule-based with no real binary.

```yaml
obsw:
  type: stub          # swap to 'pipe' when you have an openobsw binary

equipment:
  - id: mag1
    model: magnetometer
    hardware_profile: mag_default
  - id: gyro1
    model: gyroscope
    hardware_profile: gyro_default
  ...
```

To add EPS: uncomment the solar_array, battery, and pcdu entries, then run
`svf campaign mission_mysat1/campaigns/eps_campaign.yaml --report`.

### 3. Test procedures (`procedures/quickstart_procedures.py`)

Each `Procedure` subclass maps to one requirement. The `run()` method uses a
`ProcedureContext` to inject values, wait for sim-time to advance, and assert
on telemetry.

```python
class SensorPowerOn(Procedure):
    id          = "TC-AOCS-001"
    title       = "AOCS sensor power-on verification"
    requirement = "MIS-AOCS-001"

    def run(self, ctx: ProcedureContext) -> None:
        self.step("Send power-enable to magnetometer and gyroscope")
        ctx.inject("aocs.mag1.power_enable",  1.0)
        ctx.inject("aocs.gyro1.power_enable", 1.0)

        self.step("Wait 2 s for sensor initialisation")
        ctx.wait(2.0)

        self.step("Verify magnetometer status nominal")
        ctx.assert_parameter("aocs.mag1.status", equals=1.0)
```

Key `ProcedureContext` methods:

| Method | What it does |
|---|---|
| `ctx.inject(param, value)` | Write to an equipment IN port (via CommandStore) |
| `ctx.wait(seconds)` | Block until sim-time has advanced by this amount |
| `ctx.assert_parameter(param, ...)` | Fail the step if the assertion is violated |
| `ctx.monitor(param, less_than=...)` | Continuous assertion over a time window |
| `ctx.inject_equipment_fault(...)` | Inject a stuck/noise/bias/fail fault |

### 4. Campaign YAML (`campaigns/quickstart_campaign.yaml`)

Declares which procedures to run and  -  critically  -  which requirements this
campaign is responsible for. Any declared requirement with no covering
procedure appears as **UNCOVERED** in the HTML report.

```yaml
campaign: MySat-1 Quickstart Validation
spacecraft: ../spacecraft.yaml

requirements:
  - MIS-AOCS-001   # covered by TC-AOCS-001
  - MIS-AOCS-002   # covered by TC-AOCS-002
  - MIS-AOCS-003   # covered by TC-AOCS-003
  - MIS-AOCS-004   # covered by TC-FAULT-001
  - MIS-EPS-001    # UNCOVERED  -  no EPS procedure yet
  - MIS-EPS-002    # UNCOVERED
  - MIS-EPS-003    # UNCOVERED
  - MIS-EPS-004    # UNCOVERED

procedures:
  - ../procedures/quickstart_procedures.py
```

### 5. Run and report

```bash
# Run campaign and produce HTML report
svf campaign mission_mysat1/campaigns/quickstart_campaign.yaml --report

# Also save a JSON file for CI integration
svf campaign mission_mysat1/campaigns/quickstart_campaign.yaml \
    --report --json results/quickstart.json
```

The HTML report (`results/quickstart_campaign_report.html`) shows:
- Summary card: 4 PASS, 0 FAIL, 0 ERROR, 0 INCONCLUSIVE
- Per-procedure timeline with step-level events
- Requirement coverage table: 4 COVERED, 4 UNCOVERED

---

## Hardware profiles

Equipment physics are parameterised by hardware profiles  -  YAML files that
set noise levels, saturation limits, thermal constants, and so on.

```bash
svf profiles    # list all bundled profiles
```

To use a specific unit (e.g. NovAtel OEM7 GPS instead of the generic model):

```yaml
# spacecraft.yaml
equipment:
  - id: gps1
    model: gps
    hardware_profile: gps_novatel_oem7
```

---

## Next steps

| Goal | What to do |
|---|---|
| Add EPS validation | Add `solar_array`, `battery`, `pcdu` to `spacecraft.yaml`; run `eps_campaign.yaml` |
| Fault injection testing | See `TC-FAULT-001` in `quickstart_procedures.py` for the pattern |
| Closed-loop OBC testing | Run `platform_campaign.yaml` (tests PUS TC/TM exchange via stub OBC) |
| Real flight software | Set `obsw: type: pipe` and point `binary:` at your `obsw_sim` binary |
| Higher-fidelity dynamics | Uncomment the `kde` (dynamics FMU) entry in `spacecraft.yaml` |
