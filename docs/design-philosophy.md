# OpenSVF Design Philosophy

> **Status:** v1.0
> **Last updated:** 2026-04
> **Author:** lipofefeyt

---

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

OpenSVF targets teams that **hand-code their AOCS algorithms in C** — which is most smallsat programmes that cannot afford Embedded Coder, and most research and academic projects.

```
Hand-coded C algorithm (openobsw)
  ↓ validated against physics (opensvf-kde plant model)
  ↓ validated against reference oracle (Python reference controller)
  ↓ validated on hardware (MSP430 LaunchPad)
  ↓ ground station integration (YAMCS)
```

The question OpenSVF answers is different from Simulink Monte Carlo:

| Question | Tool |
|---|---|
| "What is the statistical performance of my design model?" | Simulink + Monte Carlo |
| "What is the statistical performance of my actual flight C code?" | OpenSVF + Monte Carlo |

The second question is arguably more honest — it tests the code that will actually fly, not a model of it.

---

## Role of each component

### opensvf-kde — spacecraft plant model

The C++ physics engine is a **plant model**, not an AOCS algorithm. It provides:
- 6-DOF Euler equation integration
- Quaternion kinematics
- Earth magnetic field model

It does **not** contain any control algorithm. It is the environment the flight software runs against.

### openobsw — flight software under test

The C11 OBSW contains the actual flight algorithms:
- B-dot detumbling controller (`src/aocs/bdot.c`)
- ADCS PD attitude controller (`src/aocs/adcs.c`)
- FDIR state machine (`src/fdir/fsm.c`)
- PUS service stack (S1, S3, S5, S8, S17, S20)

These are hand-coded, not generated. They run on MSP430 hardware and in `obsw_sim` for SIL.

### opensvf Python reference controllers — validation oracles

The Python b-dot and ADCS implementations in opensvf are **reference oracles**, not flight code. They exist to validate the C implementations:

```python
# This is NOT flight code — it is a validation oracle
controller = make_bdot_controller(sync, store, cmd_store)
```

A model comparison test asserts that for identical inputs, the C implementation and the Python oracle agree within numerical tolerance. This is the SIL equivalent of a MIL vs SIL comparison.

### YAMCS — ground station validation

YAMCS validates the **commanding interface**: that TC packets are correctly parsed, routed, and acknowledged, and that TM housekeeping flows correctly to the ground station. This is separate from AOCS validation.

---

## Monte Carlo in OpenSVF

Monte Carlo in OpenSVF answers: *given a distribution of initial conditions and noise realisations, what is the statistical performance of the actual flight C code?*

The correct architecture:

```python
# Fix the algorithm (C code in obsw_sim)
# Vary the environment (initial tumble, noise seeds)

results = []
for seed in range(100):
    master = SimulationMaster(..., seed=seed)
    master.run()
    results.append(store.read("aocs.truth.rate_x").value)

# Report: mean, std, 99th percentile of detumbling convergence time
```

This is supported by the existing infrastructure: `SeedManager`, `SimulationMaster(seed=N)`, `pytest -n 8` for parallel runs.

---

## What OpenSVF is not

| Not this | Why |
|---|---|
| An AOCS design tool | Gain tuning and algorithm design happen elsewhere |
| A Simulink replacement | No code generation, no visual block diagrams |
| A plant model library | opensvf-kde is one plant model, not a general physics library |
| A flight dynamics simulator | No orbit propagation, no environmental perturbations beyond B-field |
| A certification tool | Produces evidence for validation, not formal verification |

---

## Design constraints

**SRDB as the shared parameter contract.** Every parameter has one canonical name defined in SRDB. The OBSW, SVF, and YAMCS ground station all use the same names. Changing a parameter name in SRDB breaks the build — intentionally.

**Equipment as the universal abstraction.** Every model is an Equipment. The simulation master doesn't know whether it's driving a Python sensor model, a C++ FMU, or a real C OBSW binary. Only the wiring YAML changes.

**ObcInterface as the HIL plug-in point.** Swapping `ObcStub` for `OBCEmulatorAdapter` is one line. When Renode emulation is ready, it will be a third implementation of the same interface.

**Deterministic by default.** Every run is reproducible. Stochastic models require explicit seed injection. This is a deliberate choice — non-deterministic test suites are unusable for flight software validation.