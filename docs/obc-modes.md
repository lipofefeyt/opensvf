# OBC modes

`obsw.type` in `spacecraft.yaml` selects what plays the on-board computer.
All three implement `HilAdapter`, so procedures, the console and the YAMCS
bridge send TCs and read the OBC parameters the same way; what a run proves
depends on the mode.

| `obsw.type` | OBC | What a PASS shows |
|---|---|---|
| `stub` | `ObcStub`: opensvf's Python OBC model plus rules | The procedure, the models and the campaign work. Nothing about flight software |
| `pipe` | `OBCEmulatorAdapter` running a flight software binary as a subprocess | The flight software, on the host, did what the procedure checks |
| `socket` | `OBCEmulatorAdapter` on a Renode UART (TCP) | The target build did what the procedure checks, within what the target supports (below) |

The wire protocol and the adapter's behaviour per tick are in the
[ICD](icd.md#if-1-obsw-wire-protocol); setting up pipe and socket mode is in
[Integrate your flight software](integrate-obsw.md).

## Mode encoding

`dhs.obc.mode` uses the housekeeping encoding of openobsw's SRDB:

| Value | Mode |
|---|---|
| 0 | STANDBY |
| 1 | SAFE |
| 2 | NOMINAL |

The stub also has 3 (PAYLOAD). To command a mode, set `dhs.obc.mode_cmd` to
the value; against flight software the adapter sends TC(8,1) with the
function ID from the [ICD](icd.md#tcs-the-adapter-builds). openobsw and the
stub both boot in SAFE, and openobsw rejects most TCs there, so a procedure
that needs NOMINAL starts with `ctx.ensure_nominal()`.

Against flight software, `dhs.obc.mode` comes from housekeeping set 3; an S5
mode event updates it until the next set 3 report.

## Stub

`ObcStub` extends `ObcEquipment`, opensvf's Python OBC model: a mode state
machine, OBT, a watchdog, memory and CPU-load figures, S17 and S20 handling,
housekeeping reports. On top of it, rules evaluated each tick against the
ParameterStore inject commands, the ECSS "model responder"
(ECSS-E-TM-10-21A). No binary, no wire protocol.

The stub is not openobsw, and differs from it where a procedure could
notice:

- **Mode events.** The stub reports a transition to mode *m* as event
  `0x0010 + m` (SAFE `0x0011`, NOMINAL `0x0012`). openobsw uses `0x0002`,
  `0x0004` and `0x0005` for the transitions, and `0x0010` is its
  `watchdog_expiry`.
- **Watchdog.** When `dhs.obc.watchdog_kick` is not set, the stub reports
  event `0x0001` after 30 s and resets to SAFE with event `0x0002`
  (openobsw's `safe_mode_entry`) after 60 s. The openobsw host sim kicks its
  own watchdog every tick and never expires.

A procedure that checks event IDs or the watchdog therefore verifies the
stub, not openobsw. Run it in pipe mode for flight software evidence.

## Pipe

`OBCEmulatorAdapter` starts the binary and exchanges frames over
stdin/stdout. With openobsw it runs `obsw_sim`, the host build of the flight
software: the same application code as the targets, on Linux. An aarch64
binary runs under QEMU user mode. The adapter checks the start-up banner
and stops the run when the binary exits.

## Socket

`OBCEmulatorAdapter` connects to a Renode UART terminal over TCP and
exchanges the same frames. There is no banner check. What works depends on
the openobsw target:

| Target under Renode | TCs and TM | Housekeeping | Closed-loop AOCS | opensvf evidence |
|---|---|---|---|---|
| ZynqMP | S8 and S17 only; stops answering in NOMINAL | no | no | CI: TC(17,1) ping against openobsw `main` (`test_renode_zynqmp.py`) |
| STM32H7 FreeRTOS | yes | yes | no: sensor frames are dropped, no actuator frame | none in opensvf CI |

--8<-- "docs/_gen/openobsw-targets.md"

## Serial

From Python only: `OBCEmulatorAdapter(serial_port=..., baud_rate=...)`
talks to a board over a UART (`pip install opensvf[uart]`). There is no
`spacecraft.yaml` setting for it; a unit test covers it with a fake port,
not against a board.
