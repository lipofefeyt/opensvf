# OpenSVF

**Open-source spacecraft software validation facility**

OpenSVF is a Python platform for validating flight software before hardware integration. You write test procedures in Python; OpenSVF runs your flight software binary in a closed loop with a 6-DOF physics engine and a real PUS ground station, then produces an HTML campaign report with a requirement traceability matrix.

```
Your flight software binary
        │  stdin/stdout wire protocol
        ▼
    OpenSVF (Python)
  ┌─────────────────────────────┐
  │  Sensor models              │  magnetometer, gyro, star tracker, GPS, RW
  │  Bus adapters               │  MIL-STD-1553B, SpaceWire, CAN 2.0B
  │  PUS TM/TC stack            │  ECSS-E-ST-70-41C
  │  Campaign runner            │  procedure → verdict → HTML report
  └─────────────────────────────┘
        │  PUS TM/TC
        ▼
    YAMCS 5.12.6  (optional ground station)
```

---

## Install

```bash
pip install opensvf
```

---

## 60-second demo

No flight binary needed  -  the MySat-1 reference mission runs in stub mode:

```bash
pip install opensvf
svf campaign mission_mysat1/campaigns/quickstart_campaign.yaml --report
open results/quickstart_campaign_report.html
```

The HTML report shows four PASS verdicts for AOCS requirements and flags four UNCOVERED EPS requirements  -  exactly where the gap is.

---

## Three modes

| Mode | OBC | When to use |
|------|-----|-------------|
| **Stub** | Rule-based Python stub | Rapid iteration, no binary needed |
| **Pipe** | Real binary via stdin/stdout | Primary SIL validation, CI |
| **Socket** | Binary in Renode ZynqMP | Instruction-accurate emulation |

---

## What a procedure looks like

```python
from svf.campaign.procedure import Procedure, ProcedureContext

class BdotConvergence(Procedure):
    id          = "TC-AOCS-001"
    title       = "B-dot detumbling convergence"
    requirement = "MIS-AOCS-042"

    def run(self, ctx: ProcedureContext) -> None:
        self.step("Power on sensors")
        ctx.inject("aocs.mag.power_enable", 1.0)
        ctx.inject("aocs.gyro.power_enable", 1.0)

        self.step("Monitor angular rate for 60s")
        monitor = ctx.monitor("aocs.gyro.rate_x", less_than=0.5)
        ctx.wait(60.0)
        monitor.assert_no_violations()
```

```bash
svf campaign campaign.yaml --report
```

---

## Related projects

| Project | What it is |
|---------|------------|
| [openobsw](https://github.com/lipofefeyt/openobsw) | C11 flight software: PUS stack, b-dot, ADCS PD, FDIR |
| [opensvf-kde](https://github.com/lipofefeyt/opensvf-kde) | C++ 6-DOF kinematics and dynamics engine (FMI 2.0 FMU) |

---

*Apache 2.0  -  built by [lipofefeyt](https://github.com/lipofefeyt/opensvf)*
