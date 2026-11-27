# OpenSVF

**Open-source spacecraft software validation facility**

OpenSVF validates flight software before hardware integration. It runs the
flight software binary in closed loop with equipment models, an orbit and
6-DOF dynamics, sends it telecommands and decodes its telemetry. Test
procedures are written in Python; a campaign turns them into an HTML report
with a requirement traceability matrix. YAMCS can be attached as the ground
station.

```text
 Flight software binary (openobsw, or yours)
        |  wire protocol: stdin/stdout, or TCP to Renode
 OpenSVF (Python)
   OBC models         stub, pipe, socket
   Equipment models   AOCS sensors and actuators, EPS, thermal, TT&C
   Dynamics           opensvf-kde 6-DOF FMU, SGP4 orbit, B-field
   Bus adapters       MIL-STD-1553B, SpaceWire, CAN 2.0B
   PUS TM/TC stack    ECSS-E-ST-70-41C
   Campaign runner    procedure -> verdict -> HTML report
        |  PUS TM/TC (optional)
 YAMCS 5.12.6
```

## Install

```bash
pip install opensvf
```

This installs the library and the `svf` command. The reference mission
(MySat-1) is in the repository, not in the package.

## First campaign

MySat-1 runs without a flight software binary: the OBC is a rule-based stub.

```bash
git clone https://github.com/lipofefeyt/opensvf
cd opensvf
pip install .
svf campaign mission_mysat1/campaigns/quickstart_campaign.yaml --report
```

Four procedures PASS, and the report lists four EPS requirements the campaign
declares but does not cover. The [MySat-1 quickstart](quickstart-mysat1.md)
explains both.

## Three OBC modes

| `obsw.type` | OBC | When to use |
|---|---|---|
| `stub` | `ObcStub` rule engine, no flight software | Writing procedures and models |
| `pipe` | Your binary as a subprocess (stdin/stdout); aarch64 under QEMU | SIL validation, CI |
| `socket` | Your target under Renode (UART over TCP) | Target builds: TCs and housekeeping |

[Integrate your flight software](integrate-obsw.md) explains pipe and
socket mode.

## What a procedure looks like

The first MySat-1 procedure:

```python
--8<-- "mission_mysat1/procedures/quickstart_procedures.py:p1"
```

## Related projects

| Project | What it is |
|---|---|
| [openobsw](https://github.com/lipofefeyt/openobsw) | C11 flight software: PUS stack, b-dot, ADCS PD, FDIR ([documentation](https://openobsw.readthedocs.io/)) |
| [opensvf-kde](https://github.com/lipofefeyt/opensvf-kde) | C++ 6-DOF kinematics and dynamics engine (FMI 2.0 FMU) |

*Apache 2.0  -  [lipofefeyt/opensvf](https://github.com/lipofefeyt/opensvf)*
