# System tests

The L3 suite (`tests/system/`) runs opensvf against real flight software:
openobsw's `obsw_sim` from the release pinned in `.openobsw-version`, with the
`SpacecraftDynamics.fmu` committed in `models/`. It tests the integration of
opensvf and openobsw. It is not mission evidence: a mission campaign runs
procedures against its own flight software (see [validation](validation.md)).

## Running it

```bash
bash scripts/build_obsw_sim.sh    # bin/obsw_sim from the pinned openobsw tag
pytest tests/system -v
```

`testosvf` and a plain `pytest` skip `tests/system` (`norecursedirs`), so
name it. A test whose binary is missing is skipped with the reason.
`OBSW_SIM=/path/to/obsw_sim` points the alignment tests at another build;
`OPENOBSW_SRC=/path/to/openobsw bash scripts/build_obsw_sim.sh` builds an
existing checkout and warns when it is not at the pinned tag.

In CI the `system-test` job builds `obsw_sim` from the pin, runs
`checkcons --obsw` against the same checkout, then the suite, on every pull
request.

## What it covers

--8<-- "docs/_gen/validation-l3.md"

The closed-loop tests replace the former SIL attitude guide:

- **SAFE, b-dot** (`test_kde_obsw_adcs_closed_loop.py`): dynamics, sensor
  models, `obsw_sim` and the magnetorquer in closed loop for 30 s of
  simulation time; the flight software's b-dot dipoles must bring the true
  rate below 1 rad/s. The magnetorquer dipoles must reach the CommandStore,
  and the flight software's OBT must advance with the sensor frames.
- **NOMINAL, ADCS PD**: after `dhs.obc.mode_cmd` = NOMINAL, housekeeping must
  report NOMINAL and the actuator frame must report the PD controller.
  Reaction wheel torques are not fed back into the dynamics yet, so this
  checks that the controller runs, not that it points.
- **Real time** (`test_realtime_detumbling.py`): the b-dot loop under
  `RealtimeTickSource`; 30 s of simulation time must take 25 to 40 s of
  wall-clock time, and a tick that overruns `dt` must log a warning.

## Other targets

| Test | Needs | Where it runs |
|---|---|---|
| `test_aarch64_obsw.py` | `bin/obsw_sim_aarch64`, `qemu-aarch64`, `AARCH64_GLIBC` | Locally |
| `test_renode_zynqmp.py` | `renode` on `PATH`, `bin/obsw_zynqmp.bin`, Renode started with `renode/zynqmp_obsw.resc` | CI on every push to `main`, with the ZynqMP binary from the newest successful openobsw push to `main` (not the pinned release); fails when no test ran |

Under Renode the target can run slower than real time (an STM32H750 at about
0.4x in the devcontainer), while `expect_tm`, `wait_until` and the adapter's
sync timeout count wall-clock time. Measure from packet OBT where it
matters; see [known limits](known-limits.md).

## Writing a system test

A test against flight software must show something about the flight
software, not about opensvf's view of it:

1. Assert on what the flight software reported: decoded TM, housekeeping
   values, TM(1,x), TM(5,x) events, the actuator frame. Not on adapter
   defaults, the adapter's clock or packet counters alone.
2. Run each new assertion once against a broken condition (skip the mode
   command, an impossible threshold) and check it fails.
3. Wait in simulation time (`ctx.wait()`, or inject before `master.run()`
   and read after it), not with `time.sleep()`.
4. Check the link health: TM dropped or a TC rejected without a reason is a
   defect.
5. Drive the same exchange by hand first:
   `svf console mission_mysat1/spacecraft_hil.yaml`.

Give the test a `@pytest.mark.requirement(...)` like any other; the
requirements it verifies appear in the table above.
