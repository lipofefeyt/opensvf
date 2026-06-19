# MySat-1 Quickstart

MySat-1 is the reference mission bundled with OpenSVF. It is a minimal 3U CubeSat that demonstrates the full validation workflow  -  from written requirements through test procedures to an HTML campaign report  -  with **no compiled binary or FMU needed**.

---

## Prerequisites

```bash
pip install opensvf
```

That's it. MySat-1 runs in stub mode; the OBC is replaced by a rule-based Python stub.

---

## Run your first campaign

```bash
git clone https://github.com/lipofefeyt/opensvf
cd opensvf
svf campaign mission_mysat1/campaigns/quickstart_campaign.yaml --report
open results/quickstart_campaign_report.html   # or xdg-open on Linux
```

The report shows:

- **4 PASS**  -  AOCS detumbling and attitude procedures
- **4 UNCOVERED**  -  EPS requirements (no EPS procedures written yet  -  intentional gap)

---

## What just ran

```
mission_mysat1/
├── spacecraft.yaml              # stub OBC + AOCS sensor models
├── requirements.md              # what we are validating
└── campaigns/
    └── quickstart_campaign.yaml # 4 procedures, declares 8 requirements
└── procedures/
    └── quickstart_procedures.py # the 4 procedures
```

The campaign YAML is straightforward:

```yaml
campaign: MySat-1 AOCS Quickstart
spacecraft: ../spacecraft.yaml
requirements:
  - MIS-AOCS-001
  - MIS-AOCS-002
  - MIS-AOCS-003
  - MIS-AOCS-004
  - MIS-EPS-001
  - MIS-EPS-002
  - MIS-EPS-003
  - MIS-EPS-004
procedures:
  - ../procedures/quickstart_procedures.py
```

---

## Next steps

- Browse the full AOCS suite: `mission_mysat1/campaigns/aocs_campaign.yaml`
- Add fault injection: `ctx.inject_equipment_fault("mag1", ...)`
- Bring your own binary: see [Plug In Your Own Binary](quickstart-own-binary.md)

---

## Developer tools

```bash
svf validate mission_mysat1/spacecraft.yaml   # fast config check, no DDS
svf profiles                                   # list bundled hardware profiles
checkcov                                       # requirement coverage report
checkcons                                      # SRDB consistency checks
```
