# MySat-1 quickstart

MySat-1 is the reference mission in the opensvf repository: a 3U CubeSat
with AOCS sensors and actuators, EPS and TT&C models, its requirements, test
procedures and campaigns. Its default configuration needs no flight software
binary and no FMU: the OBC is `ObcStub`, a rule-based Python stub.

## Install

The mission files are in the repository, so clone it and install the
package from the checkout:

```bash
git clone https://github.com/lipofefeyt/opensvf
cd opensvf
pip install .
```

The Python versions opensvf supports are on the
[compatibility](compatibility.md) page.

## Run the quickstart campaign

```bash
svf campaign mission_mysat1/campaigns/quickstart_campaign.yaml --report
```

The summary:

```text
Procedures: 4
PASS:          4
FAIL:          0
ERROR:         0
INCONCLUSIVE:  0
Pass rate: 100.0%

UNCOVERED requirements (4):
  MIS-EPS-001
  MIS-EPS-002
  MIS-EPS-003
  MIS-EPS-004

ID                   Verdict        Requirement          Title
------------------------------------------------------------------------
TC-AOCS-001          PASS           MIS-AOCS-001         AOCS sensor power-on verification
TC-AOCS-002          PASS           MIS-AOCS-002         Star tracker cold-start acquisition
TC-AOCS-003          PASS           MIS-AOCS-003         Reaction wheel spin-up under positive torque
TC-FAULT-001         PASS           MIS-AOCS-004         Reaction wheel thermal protection activation
```

The HTML report is `results/quickstart_campaign_report.html`.

The campaign declares eight requirements and its procedures cover the four
AOCS ones. The four EPS requirements are UNCOVERED on purpose, to show how a
report flags a gap: `eps_campaign.yaml` covers MIS-EPS-001 to 003, and
MIS-EPS-004 has no procedure yet.

## What ran

```text
mission_mysat1/
├── spacecraft.yaml                  stub OBC and the equipment models
├── requirements.md                  the mission requirements
├── campaigns/
│   └── quickstart_campaign.yaml     the procedure file and 8 requirements
└── procedures/
    └── quickstart_procedures.py     the 4 procedures
```

```yaml
--8<-- "mission_mysat1/campaigns/quickstart_campaign.yaml"
```

Each procedure runs against a fresh simulation; the runner orders them by
class name (`P1_` to `P4_`).

## Next steps

- The other campaigns in `mission_mysat1/campaigns/`: AOCS, EPS, DHS,
  platform with buses, contact pass.
- Run against the real flight software. `bash scripts/build_obsw_sim.sh`
  builds `obsw_sim` from the pinned openobsw release into `bin/`, and
  `spacecraft_hil.yaml` runs it in pipe mode:
    - `svf console mission_mysat1/spacecraft_hil.yaml` drives it by hand;
    - `freertos_hil_campaign.yaml` runs on it once its `spacecraft:` line
      points at `../spacecraft_hil.yaml`. Against `obsw_sim` v0.20 three
      procedures PASS; TC-HIL-004 stays INCONCLUSIVE because the host sim
      does not run FreeRTOS.

  To bring your own binary, see
  [Integrate your flight software](integrate-obsw.md).
- Check a configuration before running it:
  `svf validate mission_mysat1/spacecraft.yaml`.
- List the bundled hardware profiles: `svf profiles`.
