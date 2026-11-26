# Known limits

What opensvf does not do, or does not show, at this version. Each item was
checked against the source and the pinned openobsw release
(`.openobsw-version`). The list is not complete yet: the documentation
milestone (1.4.0) finishes it from the inventory in issue #199.

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

## Observing the OBSW

- **No public raw TM hook.** `HilAdapter.add_tm_listener()` sees every
  decoded TM packet, not the raw bytes.
- **TM listener exceptions are not caught.** An exception raised by a TM
  listener escapes the simulation tick that delivered the packet.

## Releases before 1.4.0

Versions before 1.4.0 have no versioned documentation. Their
[README](https://github.com/lipofefeyt/opensvf/blob/v1.3.0/README.md) and
[REQUIREMENTS.md](https://github.com/lipofefeyt/opensvf/blob/v1.3.0/REQUIREMENTS.md)
at the release tag describe them.
