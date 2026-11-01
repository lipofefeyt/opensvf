"""
svf console  -  drive a spacecraft simulation by hand and watch the telemetry.

Runs a spacecraft configuration (the real openobsw binary, Renode or the
stub OBC) in real time and accepts operator commands: send TCs, change mode,
set parameters, and see every decoded TM packet as it arrives, with TC
rejections named and tied back to the TC that caused them. The same
commands run non-interactively from ``-c`` or a script file, where
``expect`` turns a session into a repeatable smoke check.

Implements: SVF-DEV-215
"""

from __future__ import annotations

import shlex
import struct
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from svf.models.dhs.hil_adapter import HilAdapter
from svf.models.dhs.obc import MODE_NOMINAL, MODE_SAFE, MODE_STANDBY
from svf.models.dhs.obc_emulator import S1_FAILURE_CODES
from svf.pus.tc import PusTcBuilder, PusTcPacket
from svf.pus.tm import PusTmPacket
from svf.sim.simulation import SimulationMaster
from svf.sim.software_tick import RealtimeTickSource

MODE_NAMES = {MODE_STANDBY: "STANDBY", MODE_SAFE: "SAFE", MODE_NOMINAL: "NOMINAL"}
_MODES = {"standby": MODE_STANDBY, "safe": MODE_SAFE, "nominal": MODE_NOMINAL}

HELP = """\
Commands (sim time in seconds; ids may be hex, e.g. 0x20A0):
  ping                       TC(17,1) are-you-alive
  mode safe|nominal|standby  command an OBC mode (TC(8,1) on openobsw)
  obt <seconds>              TC(9,128) set on-board time
  hk enable <sid> [ticks]    TC(3,5) enable an HK set (default every tick)
  hk disable <sid>           TC(3,6)
  param get <id>             TC(20,3)
  param set <id> <value>     TC(20,1) float32
  tc <svc> <sub> [hex]       any TC, application data as hex
  wait <seconds>             let sim time advance
  expect <svc>,<sub> [s]     wait (sim time, default 5 s) for that TM; fails otherwise
  status                     sim time, OBC mode and OBT, link health
  watch all|events|off       print every TM / all but HK TM(3,25) (default) / none
  help, quit"""


class ConsoleError(Exception):
    """A command that could not be carried out (bad syntax or failed expect)."""


@dataclass
class _Sent:
    label: str
    t: float


@dataclass
class SvfConsole:
    """Operator console over a loaded (not yet running) SimulationMaster."""

    master: SimulationMaster
    out: Callable[[str], None] = print
    apid: int = 0x010
    watch: str = "events"
    _obc: Optional[HilAdapter] = field(default=None, init=False)
    _seq: int = field(default=0, init=False)
    _sent: dict[int, _Sent] = field(default_factory=dict, init=False)
    _seen: list[tuple[int, int, float]] = field(default_factory=list, init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)
    _thread: Optional[threading.Thread] = field(default=None, init=False)
    _sim_error: list[BaseException] = field(default_factory=list, init=False)

    def __post_init__(self) -> None:
        for model in self.master._models:
            if isinstance(model, HilAdapter):
                self._obc = model
                model.add_tm_listener(self._on_tm)
                break

    # ── simulation lifecycle ────────────────────────────────────────────────

    def start(self, realtime: bool = True, duration: float = 1.0e9) -> None:
        """Run the simulation in a background thread and wait for the first tick."""
        if realtime:
            self.master._tick_source = RealtimeTickSource()
        self.master._stop_time = duration

        def _run() -> None:
            try:
                self.master.run()
            except BaseException as exc:      # reported by sim_time()/status
                self._sim_error.append(exc)

        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()
        deadline = time.monotonic() + 15.0
        while self.sim_time() is None:
            if self._sim_error:
                raise ConsoleError(f"simulation failed to start: {self._sim_error[0]}")
            if time.monotonic() > deadline:
                raise ConsoleError("simulation did not start within 15 s")
            time.sleep(0.02)

    def stop(self) -> None:
        self.master.stop()
        if self._thread is not None:
            self._thread.join(timeout=3.0)

    def sim_time(self) -> Optional[float]:
        store = self.master._param_store
        entry = store.read("svf.sim_time") if store is not None else None
        return entry.value if entry is not None else None

    # ── command handling ────────────────────────────────────────────────────

    def execute(self, line: str) -> bool:
        """Run one command line. Returns False on ``quit``; raises ConsoleError."""
        words = shlex.split(line.split("#", 1)[0])
        if not words:
            return True
        cmd, args = words[0].lower(), words[1:]
        handler = getattr(self, f"_cmd_{cmd}", None)
        if handler is None:
            raise ConsoleError(f"unknown command '{cmd}' (type 'help')")
        result: Optional[bool] = handler(args)
        return result is not False

    def _cmd_help(self, args: list[str]) -> None:
        self.out(HELP)

    def _cmd_quit(self, args: list[str]) -> bool:
        return False

    _cmd_exit = _cmd_quit

    def _cmd_ping(self, args: list[str]) -> None:
        self.send_tc(17, 1)

    def _cmd_mode(self, args: list[str]) -> None:
        if len(args) != 1 or args[0].lower() not in _MODES:
            raise ConsoleError("usage: mode safe|nominal|standby")
        store = self.master._command_store
        if store is None:
            raise ConsoleError("no command store")
        store.inject("dhs.obc.mode_cmd", float(_MODES[args[0].lower()]), source_id="console")
        self.out(f"  -> mode {args[0].upper()} commanded")

    def _cmd_obt(self, args: list[str]) -> None:
        self.send_tc(9, 128, struct.pack(">I", int(_number(args, 0, "obt <seconds>"))))

    def _cmd_hk(self, args: list[str]) -> None:
        if len(args) >= 2 and args[0] == "enable":
            ticks = int(_number(args, 2, "")) if len(args) > 2 else 1
            self.send_tc(3, 5, struct.pack(">BI", int(_number(args, 1, "")), ticks))
        elif len(args) == 2 and args[0] == "disable":
            self.send_tc(3, 6, struct.pack(">B", int(_number(args, 1, ""))))
        else:
            raise ConsoleError("usage: hk enable <sid> [ticks] | hk disable <sid>")

    def _cmd_param(self, args: list[str]) -> None:
        if len(args) == 2 and args[0] == "get":
            self.send_tc(20, 3, struct.pack(">H", int(_number(args, 1, ""))))
        elif len(args) == 3 and args[0] == "set":
            pid, value = int(_number(args, 1, "")), _number(args, 2, "")
            self.send_tc(20, 1, struct.pack(">Hf", pid, value))
        else:
            raise ConsoleError("usage: param get <id> | param set <id> <value>")

    def _cmd_tc(self, args: list[str]) -> None:
        if len(args) not in (2, 3):
            raise ConsoleError("usage: tc <svc> <sub> [hex]")
        try:
            data = bytes.fromhex(args[2]) if len(args) == 3 else b""
        except ValueError as exc:
            raise ConsoleError(f"bad hex data: {exc}") from exc
        self.send_tc(int(_number(args, 0, "")), int(_number(args, 1, "")), data)

    def _cmd_wait(self, args: list[str]) -> None:
        self._wait_sim(_number(args, 0, "wait <seconds>"))

    def _cmd_expect(self, args: list[str]) -> None:
        if not args or "," not in args[0]:
            raise ConsoleError("usage: expect <svc>,<sub> [seconds]")
        svc, sub = (int(x, 0) for x in args[0].split(",", 1))
        timeout = _number(args, 1, "") if len(args) > 1 else 5.0
        start = self.sim_time() or 0.0
        if not self._wait_sim(timeout, until=lambda: any(
                s == svc and u == sub and t >= start for s, u, t in self._snapshot())):
            raise ConsoleError(f"expected TM({svc},{sub}) within {timeout:g} s, none arrived")
        self.out(f"  ok: TM({svc},{sub}) received")

    def _cmd_status(self, args: list[str]) -> None:
        store = self.master._param_store
        def read(name: str) -> Optional[float]:
            e = store.read(name) if store is not None else None
            return e.value if e is not None else None
        mode = read("dhs.obc.mode")
        self.out(f"  sim t={self.sim_time() or 0.0:.1f}s  "
                 f"mode={MODE_NAMES.get(int(mode), mode) if mode is not None else '?'}  "
                 f"obt={read('dhs.obc.obt')}")
        health = self._obc.link_health() if self._obc is not None else None
        self.out("  link: " + (health.summary(S1_FAILURE_CODES) if health is not None
                               else "no OBSW link (stub OBC)"))
        if self._sim_error:
            self.out(f"  SIMULATION STOPPED: {self._sim_error[0]}")

    def _cmd_watch(self, args: list[str]) -> None:
        if len(args) != 1 or args[0] not in ("all", "events", "off"):
            raise ConsoleError("usage: watch all|events|off")
        self.watch = args[0]

    # ── TC out, TM in ───────────────────────────────────────────────────────

    def send_tc(self, service: int, subservice: int, data: bytes = b"") -> int:
        if self._obc is None:
            raise ConsoleError("this spacecraft has no OBC model to command")
        # Share the adapter's sequence counter when it has one, so the
        # console's TCs and the adapter's own (mode commands, pings) never
        # carry the same sequence count.
        build = getattr(self._obc, "_build_tc", None)
        if callable(build):
            raw = build(service, subservice, data)
        else:
            self._seq = (self._seq + 1) % 16384
            raw = PusTcBuilder().build(PusTcPacket(
                apid=self.apid, sequence_count=self._seq,
                service=service, subservice=subservice, app_data=data))
        seq = int(struct.unpack_from(">H", raw, 2)[0]) & 0x3FFF
        label = f"TC({service},{subservice})"
        self._sent[seq] = _Sent(label, self.sim_time() or 0.0)
        self._obc.receive_tc(raw)
        self.out(f"  -> {label} #{seq} sent" + (f" data={data.hex()}" if data else ""))
        return seq

    def _on_tm(self, pkt: PusTmPacket, t: float) -> None:
        sim_t = self.sim_time() or t
        with self._lock:
            self._seen.append((pkt.service, pkt.subservice, sim_t))
        hk = (pkt.service, pkt.subservice) == (3, 25)
        if self.watch == "all" or (self.watch == "events" and not hk):
            self.out(f"  <- t={sim_t:7.1f}s {self.describe_tm(pkt)}")

    def _snapshot(self) -> list[tuple[int, int, float]]:
        with self._lock:
            return list(self._seen)

    def _wait_sim(self, seconds: float, until: Optional[Callable[[], bool]] = None) -> bool:
        start = self.sim_time() or 0.0
        while (self.sim_time() or 0.0) < start + seconds:
            if until is not None and until():
                return True
            if self._sim_error:
                raise ConsoleError(f"simulation stopped: {self._sim_error[0]}")
            time.sleep(0.02)
        return until() if until is not None else True

    def describe_tm(self, pkt: PusTmPacket) -> str:
        """One line naming what a TM packet means."""
        d, key = pkt.app_data, (pkt.service, pkt.subservice)
        if pkt.service == 1 and len(d) >= 4:
            seq = struct.unpack_from(">I", d, 0)[0] & 0x3FFF
            sent = self._sent.get(seq)
            what = f"{sent.label} #{seq}" if sent else f"TC #{seq} (sent by the adapter)"
            if pkt.subservice in (2, 8) and len(d) >= 6:
                code = struct.unpack_from(">H", d, 4)[0]
                stage = "rejected" if pkt.subservice == 2 else "failed"
                return (f"TM(1,{pkt.subservice}) {what} {stage}: "
                        f"0x{code:04X} {S1_FAILURE_CODES.get(code, 'unknown code')}")
            word = {1: "accepted", 3: "started", 7: "completed"}.get(pkt.subservice, "?")
            return f"TM(1,{pkt.subservice}) {what} {word}"
        if key == (3, 25) and d:
            sid = d[0]
            if sid == 3 and len(d) >= 12:
                mode, obt, wd, mem, health, resets, cpu = struct.unpack_from(">BIBBBHB", d, 1)
                return (f"TM(3,25) HK set 3: mode={MODE_NAMES.get(mode, mode)} obt={obt}s "
                        f"health={health} resets={resets} cpu={cpu}% mem={mem}%")
            if sid == 4 and len(d) >= 13:
                gain, kp, kd = struct.unpack_from(">fff", d, 1)
                return f"TM(3,25) HK set 4: bdot_gain={gain:g} adcs_kp={kp:g} adcs_kd={kd:g}"
            return f"TM(3,25) HK set {sid}: {d[1:].hex()}"
        if pkt.service == 5 and len(d) >= 2:
            event = struct.unpack_from(">H", d, 0)[0]
            aux = f" value={struct.unpack_from('>f', d, 2)[0]:g}" if len(d) >= 6 else ""
            severity = {1: "info", 2: "low", 3: "medium", 4: "high"}.get(pkt.subservice, "?")
            return f"TM(5,{pkt.subservice}) event 0x{event:04X} ({severity}){aux}"
        if key == (17, 2):
            return "TM(17,2) pong"
        if key == (20, 2) and len(d) >= 6:
            pid, value = struct.unpack_from(">Hf", d, 0)
            return f"TM(20,2) param 0x{pid:04X} = {value:g}"
        return f"TM({pkt.service},{pkt.subservice}) {d.hex()}"


def _number(args: list[str], i: int, usage: str) -> float:
    try:
        text = args[i]
        return float(int(text, 0)) if text.lower().startswith("0x") else float(text)
    except (IndexError, ValueError) as exc:
        raise ConsoleError(f"usage: {usage}" if usage else f"bad number in {args}") from exc


def run_console(master: SimulationMaster, commands: Optional[list[str]] = None,
                realtime: bool = True, duration: float = 1.0e9) -> int:
    """
    Interactive when ``commands`` is None; otherwise run them in order and
    stop at the first failure. Returns a process exit code.
    """
    console = SvfConsole(master)
    console.start(realtime=realtime, duration=duration)
    code = 0
    try:
        if commands is not None:
            for line in commands:
                console.out(f"svf> {line}")
                try:
                    if not console.execute(line):
                        break
                except ConsoleError as exc:
                    console.out(f"  FAILED: {exc}")
                    code = 1
                    break
            console.execute("status")
        else:
            console.out("svf console  -  type 'help' for commands, 'quit' to leave")
            while True:
                try:
                    line = input("svf> ")
                except (EOFError, KeyboardInterrupt):
                    break
                try:
                    if not console.execute(line):
                        break
                except ConsoleError as exc:
                    console.out(f"  error: {exc}")
    finally:
        console.stop()
    return code
