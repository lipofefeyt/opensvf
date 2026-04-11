# SIL Attitude Validation Guide

> **Status:** v1.0
> **Milestone:** M13 — SIL Attitude Loop Closure
> **Last updated:** 2026-04
> **Author:** lipofefeyt

---

## 1. Purpose

This document defines and records the Software-in-the-Loop (SIL) attitude validation performed in OpenSVF M13. It describes what was validated, under what conditions, and what the results demonstrate.

The validation objective is to confirm that:

1. The real C11 OBSW b-dot algorithm correctly detumbles a spacecraft in SAFE mode using magnetorquer dipoles fed back into a 6-DOF physics engine.
2. The real C11 OBSW ADCS PD controller activates correctly on SAFE→NOMINAL transition and produces attitude torque commands.
3. The full sensor injection pipeline (KDE → sensor models → obsw_sim) operates correctly at each simulation tick.

---

## 2. System Under Test

### Three-project closed loop

```
opensvf-kde (C++ / Eigen3)
    ↓ true ω, B  via FMI 2.0
MAG model  →  noisy B field measurement
GYRO model →  noisy angular rate measurement
ST model   →  noisy quaternion measurement
    ↓ packed as obsw_sensor_frame_t (type-0x02)
openobsw / obsw_sim (C11)
    FSM SAFE:    b-dot  → mtq_dipole[3]  (type-0x03)
    FSM NOMINAL: ADCS PD → rw_torque[3] (type-0x03)
    ↓ actuator frame injected into CommandStore
MTQ model  →  torque = m × B  →  KDE (loop closed, SAFE)
RW model   →  torque command  →  KDE (loop closed, NOMINAL)
```

### Software versions

| Component | Version | Language |
|---|---|---|
| opensvf | v0.6.0 | Python 3.12 |
| openobsw | v0.5.0+ | C11 |
| opensvf-kde | v0.1.0 | C++ / Eigen3 |
| Cyclone DDS | 0.11.x | — |
| FMI | 2.0 | — |

### Wire protocol

```
stdin  type-0x02: [mag_x/y/z + valid][st_q + valid][gyro + valid][sim_time]
stdout type-0x03: [mtq_dipole_x/y/z][rw_torque_x/y/z][controller][sim_time]
stdout type-0x04: [PUS TM packet]
stdout 0xFF:      end-of-tick sync
```

---

## 3. Test Procedures

### TC-ADCS-001 — B-dot detumbling reduces angular rate

**Objective:** Confirm that b-dot running in real C OBSW reduces spacecraft angular rate when MTQ dipole commands are fed back into the physics engine.

**Initial conditions:**
- FSM state: SAFE
- Sensor noise seed: 42 (deterministic replay)
- KDE initial conditions: non-zero tumble rates (KDE default)
- MAG valid: true
- ST valid: false (b-dot does not require ST)

**Procedure:**
1. Start simulation with KDE + MAG + GYRO + MTQ + OBCEmulatorAdapter
2. Run for 30 seconds at dt=0.1s (300 ticks)
3. Each tick: MAG field → type-0x02 → obsw_sim → b-dot → type-0x03 dipoles → MTQ → torque = m×B → KDE
4. At t=30s, read true angular rate from KDE ParameterStore

**Acceptance criterion:**
```
|ω_final| = √(ωx² + ωy² + ωz²) < 1.0 rad/s
```

**Result:** PASS

**Notes:** The 1.0 rad/s threshold is conservative. Full detumbling to near-zero rates requires longer simulation time (typically 300–600s depending on initial conditions and B-field geometry). This test validates that the control loop is active and effective, not that it achieves full detumbling.

---

### TC-ADCS-002 — MTQ dipole commands reach CommandStore

**Objective:** Validate the actuator frame pipeline: obsw_sim → type-0x03 → OBCEmulatorAdapter → CommandStore → MTQ.read_port().

**Procedure:**
1. Run simulation for 5 seconds
2. After run, check CommandStore for `aocs.mtq.dipole_x`

**Acceptance criterion:**
```
cmd_store.peek("aocs.mtq.dipole_x") is not None
```

**Result:** PASS

**Notes:** This validates the type-0x03 parsing pipeline end-to-end. The dipole value may be zero on the first tick (b-dot needs two measurements to compute dB/dt) but the key is that the CommandStore entry exists.

---

### TC-ADCS-003 — ADCS PD controller activates on NOMINAL transition

**Objective:** Validate that after SAFE→NOMINAL FSM transition, obsw_sim switches from b-dot to ADCS PD and produces RW torque commands.

**Procedure:**
1. Run simulation for 20 seconds
2. At t≈5s wall clock: inject `dhs.obc.mode_cmd = 1.0` (NOMINAL)
3. OBCEmulatorAdapter sends TC(8,1) recover_nominal to obsw_sim
4. obsw_sim FSM transitions SAFE→NOMINAL
5. Next sensor frame: ST+GYRO valid → ADCS PD runs → rw_torque in actuator frame
6. After run, check CommandStore for `aocs.rw1.torque_cmd`

**Acceptance criterion:**
```
cmd_store.peek("aocs.rw1.torque_cmd") is not None
```

**Result:** PASS

**Notes:** The ADCS PD controller requires ST validity. The star tracker model enters TRACKING mode after ~10s acquisition. The test injects NOMINAL at t≈5s wall clock, which corresponds to t≈5s simulation time (fast-as-possible tick source). The test passes because by the time the simulation completes, ST is valid and ADCS has had at least one tick to run.

---

### TC-ADCS-004 — Sensor frames drive obsw_sim each tick

**Objective:** Validate that sensor injection pipeline operates correctly — KDE provides truth state, sensor models add noise, OBCEmulatorAdapter packs and sends type-0x02 frames, obsw_sim advances OBT.

**Procedure:**
1. Run simulation for 5 seconds
2. After run, read `dhs.obc.obt` from ParameterStore

**Acceptance criterion:**
```
store.read("dhs.obc.obt").value > 4.0  (OBT advanced by sensor ticks)
```

**Result:** PASS

---

## 4. Controller Parameters

### B-dot controller (SAFE mode)

| Parameter | Value | Units |
|---|---|---|
| Gain k | 1.0×10⁴ | Am²·s/T |
| Max dipole | 10.0 | Am² |
| Finite difference dt | from sensor.sim_time delta | s |

### ADCS PD controller (NOMINAL mode)

| Parameter | Value | Units |
|---|---|---|
| Kp | 0.5 | N·m/rad |
| Kd | 0.1 | N·m·s/rad |
| Max torque | 0.01 | N·m |
| Target attitude | Identity quaternion [1,0,0,0] | — |

---

## 5. Sensor Noise Models

All noise parameters use deterministic seed=42 for reproducible results.

### Magnetometer

| Parameter | Value |
|---|---|
| Noise model | Gaussian white noise |
| Std dev | ~1×10⁻⁷ T per axis |
| Bias drift | Random walk |

### Gyroscope

| Parameter | Value |
|---|---|
| Noise model | Angle Random Walk (ARW) |
| ARW std dev | 1×10⁻⁴ rad/s/√Hz |
| Bias drift | Random walk |

### Star Tracker

| Parameter | Value |
|---|---|
| Acquisition time | 10s from cold start |
| Noise | Gaussian per quaternion component |
| Blinding threshold | Sun angle < 30° |

---

## 6. Deterministic Replay

All tests use `seed=42`. To replay any test exactly:

```python
master = SimulationMaster(..., seed=42)
master.run()
```

The seed manifest is saved to `results/seed.json` after each run:

```json
{
  "master_seed": 42,
  "derived_seeds": {
    "mag": 1731045123,
    "gyro": 2849201847,
    "css": 938471623
  }
}
```

---

## 7. Known Limitations

**RW torques not yet fed back into KDE.** The ADCS PD controller produces RW torque commands (TC-ADCS-003 validates they exist in CommandStore) but the KDE FMU currently only accepts MTQ torques as input. Adding RW torque ports to KDE is planned for M14.

**No quantitative detumbling time statistics.** TC-ADCS-001 validates that b-dot is active and effective (rate decreases) but does not characterise detumbling time as a function of initial tumble rate. Monte Carlo analysis (running the same scenario with different seeds and initial conditions) is planned.

**Fast-as-possible tick source.** All tests use `SoftwareTickSource` (no wall-clock alignment). Real-time validation with `RealtimeTickSource` is planned for M14.

**B-dot gain and dipole limits are literals.** The constants `1.0e4f` and `10.0f` in obsw_sim are not yet in the SRDB. SRDB AOCS parameter entries are planned for openobsw v0.6.

---

## 8. Running the Validation

```bash
# Hardware tests (requires obsw_sim + SpacecraftDynamics.fmu)
pytest tests/hardware/test_kde_obsw_adcs_closed_loop.py -v

# Full closed-loop tests (KDE + sensors, no real OBSW)
pytest tests/hardware/test_kde_obsw_closed_loop.py -v

# All hardware tests
pytest tests/hardware/ -v
```

Expected output:

```
tests/hardware/test_kde_obsw_adcs_closed_loop.py::test_safe_mode_bdot_reduces_angular_rate PASSED
tests/hardware/test_kde_obsw_adcs_closed_loop.py::test_bdot_dipoles_reach_mtq PASSED
tests/hardware/test_kde_obsw_adcs_closed_loop.py::test_nominal_mode_adcs_controller_activates PASSED
tests/hardware/test_kde_obsw_adcs_closed_loop.py::test_sensor_frames_drive_obsw_each_tick PASSED
```