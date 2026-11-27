# Validation

Two things are validated with opensvf, and they are kept apart:

- **opensvf itself**, against its own requirements (`SVF-DEV-*`, `EQP-*`,
  `PUS-*`, `KDE-*`, ... in
  [`REQUIREMENTS.md`](https://github.com/lipofefeyt/opensvf/blob/main/REQUIREMENTS.md)),
  by the L1 to L3 test levels;
- **the flight software under test**, against the mission's requirements,
  by L4 campaigns that use opensvf as the tool. MySat-1 is the reference
  mission.

The tables on this page are generated from the test files, the campaigns and
`REQUIREMENTS.md` when the site is built.

## Levels

| Level | What it tests | Needs | Run | In CI |
|---|---|---|---|---|
| L1 unit | One opensvf class at a time | nothing | `testosvf` | every pull request |
| L2 integration | Several opensvf blocks together, DDS, FMUs | the FMUs in `models/` | `testosvf` | every pull request |
| L3 system | opensvf with openobsw | `obsw_sim` from the pin | `pytest tests/system` | every pull request ([system tests](system-tests.md)) |
| L4 campaign | The flight software, through procedures | a mission's `spacecraft.yaml` | `svf campaign` | no |

--8<-- "docs/_gen/validation-counts.md"

A parametrized test function counts once here; pytest reports each case.

## Requirements and traceability

Every test carries `@pytest.mark.requirement("ID")` with an ID from
`REQUIREMENTS.md` (`checkcons` check 5 rejects unknown IDs). A pytest run
writes `results/traceability.txt`; `checkcov` then fails when a BASELINED or
IMPLEMENTED requirement has no test and is not in its `KNOWN_GAPS` table
(`src/svf/tools/checkcov.py`), whose entries name the CI job or tool that
verifies the requirement instead.

--8<-- "docs/_gen/validation-requirements.md"

"With a test" counts the requirement IDs in the test files of all three
levels. `checkcov` reads the last run, so run it right after `testosvf`;
L3 requirements count only after an L3 run.

## L1 unit tests

`tests/unit/`: no FMU, no flight software, no network.

--8<-- "docs/_gen/validation-l1.md"

## L2 integration tests

`tests/integration/`: may load the FMUs in `models/`; no flight software.

--8<-- "docs/_gen/validation-l2.md"

## L3 system tests

`tests/system/`, against `obsw_sim`; see [system tests](system-tests.md).

--8<-- "docs/_gen/validation-l3.md"

## L4 campaigns

`mission_mysat1/campaigns/`. A campaign runs each procedure against a fresh
simulation and reports a verdict per procedure; "Requirements verified" are
the `requirement` attributes of its procedures, "Declared" the requirements
the campaign YAML says it is responsible for (the report lists the declared
ones no procedure covered).

--8<-- "docs/_gen/validation-l4.md"

Every campaign uses the stub `spacecraft.yaml`, so its verdicts are about the
procedures and models, not flight software ([OBC modes](obc-modes.md)).
`freertos_hil_campaign.yaml` is meant for flight software: point its
`spacecraft:` at `../spacecraft_hil.yaml` (in stub mode its procedures are
INCONCLUSIVE).

To validate your own flight software, write `Procedure` subclasses that each
name a requirement, list them in a campaign YAML and run
`svf campaign <campaign.yaml> --report`; [Integrate your flight
software](integrate-obsw.md#a-first-campaign) has a complete example.
A campaign whose procedures trace to no requirement is exploration, not
validation.

## Not validation

- **Monte Carlo runs** (`MonteCarloRunner`): statistics of a scenario over
  seeds, not requirement verification.
- **Real-time runs** and the YAMCS demo: timing and visibility, not
  functional checks.

## The checks before a pull request

```bash
checkosvf && testosvf && checkcov && checkcons
pytest tests/system              # with bin/obsw_sim built from the pin
python tools/gen_docs.py         # when docs, the SRDB or the XTCE changed
```
