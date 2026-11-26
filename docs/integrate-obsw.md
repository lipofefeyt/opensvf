# Integrate your flight software

opensvf drives a flight software binary through the wire protocol (IF-1 on
the [ICD](icd.md) page): over stdin/stdout when it runs the binary itself
(pipe mode), or over a TCP socket to a Renode UART (socket mode). This page
says what the binary has to do and then runs a first campaign against it.

openobsw is the reference: `obsw_sim` from the pinned release passes every
example on this page in CI.

## What the binary must do

In pipe mode opensvf starts the binary as a subprocess. The binary must:

1. **Print the start-up banner on stderr** within the first second:

    --8<-- "docs/_gen/obsw-banner.md"

    The adapter refuses to start a binary whose banner names another wire
    protocol version. Without a banner it logs a warning and assumes the
    current version.

2. **Read frames from stdin.** Each frame is a type byte, a big-endian
   `uint16` body length and the body: `0x01` a PUS-C TC space packet, `0x02`
   the sensor frame.

3. **Answer every frame it reads** with the frames that frame produced,
   then exactly one `0xFF` byte, and flush stdout. A frame it writes is
   `0x04` with one PUS-C TM space packet, or `0x03` with the actuator frame.
   Body lengths must be 1 to 4096 bytes.

4. **Keep stdout for frames.** Logs go to stderr: opensvf reads stderr for
   the whole run and shows its last lines when the link fails. Text on
   stdout is read as frames and loses the sync.

5. **Answer in time:** the sensor frame within the sync timeout (10 s from
   `spacecraft.yaml`), each TC within 1 s more. Three ticks in a row without
   `0xFF` stop the run with `Lost sync`.

The frame layouts, the sensor and actuator fields and the tick sequence are
on the [ICD](icd.md#if-1-obsw-wire-protocol) page. TCs from opensvf carry
APID `0x010`, a sequence count and a CRC; accept any APID. TM is expected
without a Packet Error Control field.

What opensvf can observe depends on the TM the binary sends: TM(1,x)
verification, TM(17,2) for a ping, TM(5,x) events and TM(3,25) housekeeping
with the set layouts listed in the ICD. The OBC mode, OBT and the other
`dhs.obc.*` values come from housekeeping set 3.

### Start from the reference implementation

--8<-- "docs/_gen/openobsw-contrib.md"

!!! warning "Print the banner yourself"
    In openobsw v0.20 `svf_init()` in `contrib/svf_protocol/` does not print
    the banner yet (its body is a TODO). Write the line above to stderr at
    start-up, or opensvf runs without checking the protocol version.

## A first campaign

The three files below are the ones CI runs against `obsw_sim`
(`docs/examples/integrate-obsw/`). Put your binary at `bin/my_obsw` next to
`spacecraft.yaml`, or change `obsw.binary`.

`spacecraft.yaml` names the binary and the models that fill the sensor frame
and take the actuator frame:

```yaml
--8<-- "docs/examples/integrate-obsw/spacecraft.yaml"
```

`procedures/first_contact.py` pings the binary, waits for housekeeping and
commands NOMINAL. `ensure_nominal()` sets `dhs.obc.mode_cmd`, which the
adapter sends as TC(8,1); openobsw boots in SAFE and rejects most TCs there.

```python
--8<-- "docs/examples/integrate-obsw/procedures/first_contact.py"
```

`campaign.yaml` lists the procedures and the requirements they cover:

```yaml
--8<-- "docs/examples/integrate-obsw/campaign.yaml"
```

Check the configuration, then run the campaign:

```bash
svf validate spacecraft.yaml
svf campaign campaign.yaml --report
```

Against `obsw_sim` v0.20 the summary ends like this (the counts depend on
how long the procedure runs):

```text
ID                   Verdict        Requirement          Title
------------------------------------------------------------------------
TC-INT-001           PASS           INT-001              The OBSW answers a ping and reports its mode
                     link: TM 14/14 parsed, 0 dropped; TC 2 sent, 2 accepted, rejected none
```

The `link:` line is the link health: TM packets parsed and dropped, TCs sent
and verified. `--report` writes `results/campaign_report.html`; `--json
<path>` writes the same results, link health included, as JSON.

## aarch64 binaries

An aarch64 binary is detected with `file(1)` and run under `qemu-aarch64`,
which must be on `PATH`. The aarch64 glibc is taken from the binary's
interpreter path when it is under `/nix/store`, otherwise from the
`AARCH64_GLIBC` environment variable.

## Socket mode (Renode)

For a target running under Renode, connect to its UART terminal instead of
starting a binary:

```yaml
obsw:
  type: socket
  host: localhost
  port: 3456
```

`obsw.port` is required; Renode's UART terminal listens on 3456. There is
no start-up banner check in socket mode. What each openobsw target
supports over the socket (TCs, housekeeping, closed-loop AOCS) is in the
openobsw integration guide; see also the [known limits](known-limits.md).

## Common problems

| Message | Cause | Fix |
|---|---|---|
| `obsw_sim speaks wire protocol vN ...` | The banner names another protocol version | Build a binary that speaks the version on the [compatibility](compatibility.md) page |
| Warning `no obsw_sim start-up banner` | No banner on stderr within the first second | Print the banner at start-up |
| `Lost sync: 3 consecutive ticks without 0xFF` | No `0xFF` after a frame, stdout not flushed, or text on stdout | Write one `0xFF` per frame read and flush; log to stderr |
| `obsw_sim exited with status N` | The binary exited or crashed | Read the stderr lines in the message |
| Warning `Unknown frame type 0x..` or `Bad length` | Bytes on stdout that are not frames | Log to stderr |
| `Timeout waiting for TM(17,2)` | The binary does not answer TC(17,1), or the TM was dropped | Check `TM n/m parsed, k dropped` in the `link:` line |
| `aarch64 binary detected but qemu-aarch64 not found` | No QEMU user emulator | Install `qemu-aarch64` |
| Config error from `svf validate` | Unknown model or a missing field (`obsw.binary`, `obsw.port`) | Fix the line it names |
