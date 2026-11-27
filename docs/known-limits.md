# Known limits

What opensvf does not do, or does not show, at this version. Each item was
checked against the source and the pinned openobsw release
(`.openobsw-version`); the documentation inventory (issue #199) is the
source of the list.

## Against the openobsw flight software

- **STM32H7 is not a closed-loop SIL target.** At openobsw v0.20 the
  STM32H7 FreeRTOS image drops every sensor frame (type `0x02`) and sends no
  actuator frame (type `0x03`); the superloop build takes only `sim_time`
  from a sensor frame. Socket mode connects and TCs work, so TC and HK
  procedures can run over Renode, but a closed attitude loop cannot.
- **The host sim watchdog never expires.** `obsw_sim` kicks its watchdog
  every tick, so event `0x0010` (`watchdog_expiry`) cannot be provoked and
  `dhs.obc.watchdog_status` stays 0 against `obsw_sim`.
- **The OBC thermal input is host sim only.** The `obc_temperature_raw` and
  `thermal_valid` fields of the sensor frame are used by `obsw_sim`;
  openobsw targets ignore them.
- **Wall-clock waits under Renode undercount.** Renode can run slower than
  real time (STM32H750 at about 0.4x in the devcontainer), while
  `ProcedureContext.expect_tm`, `wait_until` and the adapter sync timeout are
  wall-clock. Measure from packet OBT instead where it matters.

## Simulation

- **Reaction wheel torque is not fed back into the dynamics.** The
  `dynamics` model takes the magnetorquer torque only. A closed loop in
  NOMINAL shows that the ADCS PD controller runs and commands the wheels,
  not that it points the spacecraft.
- **The dynamics model needs a repository checkout.** It loads
  `models/SpacecraftDynamics.fmu` from above the installed package or from
  the working directory; the PyPI package contains neither the FMUs nor the
  MySat-1 mission files.
- **No comparison of the C and Python controllers.** The Python
  `bdot_controller` closes the loop without flight software; no test checks
  that it and openobsw's b-dot agree for the same inputs.

## OBC modes

- **The stub is not openobsw.** `ObcStub` reports mode transitions as
  events `0x0010 + mode` and resets to SAFE with event `0x0002` when its
  watchdog is not kicked for 60 s; openobsw uses `0x0002`, `0x0004`,
  `0x0005` for transitions and `0x0010` for `watchdog_expiry`. A stub-mode
  check of event IDs or the watchdog says nothing about openobsw
  ([OBC modes](obc-modes.md#stub)).
- **Renode targets are not tested at the pinned release.** The CI Renode
  job pings the ZynqMP binary from the newest openobsw `main` build; no
  opensvf test runs against STM32H7 under Renode.
- **Serial transport is untested against a board.** It is reachable from
  Python only, and its unit test uses a fake port.

## Campaigns

- **L4 campaigns do not run in CI**, and every MySat-1 campaign uses the
  stub `spacecraft.yaml`.
- **Three MySat-1 procedures fail in stub mode**: TC-AOCS-001
  (`aocs_campaign.yaml`), TC-DEMO-001 and TC-DEMO-002 (`demo_campaign.yaml`)
  read `aocs.mtq.status` and `aocs.mag.status`, while `spacecraft.yaml`
  names the equipment `mtq1` and `mag1`.

## Observing the OBSW

- **No public raw TM hook.** `HilAdapter.add_tm_listener()` sees every
  decoded TM packet, not the raw bytes.
- **TM listener exceptions are not caught.** An exception raised by a TM
  listener escapes the simulation tick that delivered the packet.

## Development

- **The unit suite can abort at exit.** Rarely, pytest finishes with every
  test passed and then aborts with `corrupted double-linked list` while the
  interpreter shuts down (issue #215). Rerun it.

## Releases before 1.4.0

Versions before 1.4.0 have no versioned documentation. Their
[README](https://github.com/lipofefeyt/opensvf/blob/v1.3.0/README.md) and
[REQUIREMENTS.md](https://github.com/lipofefeyt/opensvf/blob/v1.3.0/REQUIREMENTS.md)
at the release tag describe them.
