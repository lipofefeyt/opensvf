# Design philosophy

## What OpenSVF is

OpenSVF is a **flight software validation platform**. Its purpose is to answer the question:

> *Does my flight software behave correctly against real physics and a real ground station?*

It is not an AOCS design tool. It does not replace MATLAB/Simulink. It does not generate flight code.

---

## The traditional AOCS development flow

At most spacecraft primes and mid-tier New Space companies, AOCS software development follows this pattern:

```
MATLAB/Simulink
  ↓ design algorithm, tune gains, run Monte Carlo on design model
  ↓ autogenerate C (Embedded Coder / TargetLink)
  ↓ integrate into OBSW as AOCS module
  ↓ MIL validation: Simulink model vs Simulink plant
  ↓ SIL validation: C code vs Simulink plant
  ↓ HIL validation: C code on target hardware
```

The Simulink model serves two roles: design tool (gain tuning, Monte Carlo) and code generator (flight C). The SVF validates that the generated C matches the design model.

---

## Where OpenSVF fits

OpenSVF targets teams that **hand-code their AOCS algorithms in C**  -  which is most smallsat programmes that cannot afford Embedded Coder, and most research and academic projects.

```
Hand-coded C algorithm (openobsw)
  ↓ closed loop against physics (opensvf-kde plant model), on the host
  ↓ the target builds under Renode: TCs and housekeeping (closed loop not yet, see known limits)
  ↓ ground station integration (YAMCS)
```

Under Renode, closed-loop AOCS is not supported yet; see
[known limits](known-limits.md).
--8<-- "docs/_gen/openobsw-targets.md"

The question OpenSVF answers is different from Simulink Monte Carlo:

| Question | Tool |
|---|---|
| "What is the statistical performance of my design model?" | Simulink + Monte Carlo |
| "What is the statistical performance of my actual flight C code?" | OpenSVF + Monte Carlo |

The second question is arguably more honest  -  it tests the code that will actually fly, not a model of it.

---

## Role of each component

### opensvf-kde  -  spacecraft plant model

The C++ physics engine is a **plant model**, not an AOCS algorithm. It provides:
- 6-DOF Euler equation integration
- Quaternion kinematics
- Earth magnetic field model

It does **not** contain any control algorithm. It is the environment the flight software runs against.

### openobsw  -  flight software under test

The C11 OBSW contains the actual flight algorithms:
- B-dot detumbling controller (`src/aocs/bdot.c`)
- ADCS PD attitude controller (`src/aocs/adcs.c`)
- FDIR state machine (`src/fdir/fsm.c`)
- PUS service stack (see the targets page above)

These are hand-coded, not generated. opensvf runs them in `obsw_sim` (SIL)
and under Renode.

### opensvf Python b-dot controller  -  reference model

The `bdot_controller` model in opensvf is a **reference model**, not flight
code. It closes the detumbling loop without flight software, so the
dynamics, sensor and actuator models can be tested on their own
(`tests/integration/test_closed_loop_detumbling.py`).

The intent is also to use it as an oracle: for identical inputs, the C
controller and the Python one should agree within numerical tolerance, the
SIL counterpart of a MIL-versus-SIL comparison. No test does this
comparison yet.

### YAMCS  -  ground station validation

YAMCS validates the **commanding interface**: that TC packets are correctly parsed, routed, and acknowledged, and that TM housekeeping flows correctly to the ground station. This is separate from AOCS validation.

---

## Monte Carlo in OpenSVF

Monte Carlo in OpenSVF answers: *given a distribution of initial conditions and noise realisations, what is the statistical performance of the actual flight C code?*

The correct architecture:

Fix the algorithm (the C code in `obsw_sim`) and vary the environment
(initial tumble, noise seeds). `MonteCarloRunner` (`svf.monte_carlo`) runs a
function `run_one(seed) -> dict` of metrics for N seeds in parallel processes
and reports the mean, standard deviation, percentiles and pass rate of each
metric. Each run is reproducible from its seed: `SimulationMaster(seed=N)`
derives every model's seed from it.

---

## What OpenSVF is not

| Not this | Why |
|---|---|
| An AOCS design tool | Gain tuning and algorithm design happen elsewhere |
| A Simulink replacement | No code generation, no visual block diagrams |
| A plant model library | opensvf-kde is one plant model, not a general physics library |
| A flight dynamics simulator | The orbit is SGP4 from a TLE; no orbit control, no perturbations beyond a dipole B-field |
| A certification tool | Produces evidence for validation, not formal verification |

---

## Design constraints

**SRDB as the shared parameter contract.** Every parameter has one canonical name defined in the SRDB. The OBSW, opensvf and the YAMCS mission database use the same names. When the two sides diverge, `checkcons` fails  -  intentionally.

**Equipment as the universal abstraction.** Every model is an Equipment. The simulation master does not know whether it drives a Python sensor model, a C++ FMU or a real C OBSW binary. Only `spacecraft.yaml` changes.

**HilAdapter as the plug-in point for the OBC.** `ObcStub` (no flight software), `OBCEmulatorAdapter` over a pipe (`obsw_sim`) and over a socket (Renode) implement the same interface. Switching is one line: `obsw.type` in `spacecraft.yaml`.

**Deterministic by default.** Every run is reproducible. Stochastic models require explicit seed injection. This is a deliberate choice  -  non-deterministic test suites are unusable for flight software validation.