from __future__ import annotations

import logging
import struct
import time
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional, List, Union

from svf.stores.parameter_store import ParameterStore
from svf.stores.command_store import CommandStore
from svf.sim.simulation import SimulationMaster
from svf.pus.tc import PusTcBuilder, PusTcPacket

logger = logging.getLogger(__name__)

# ── New M24 Data Structures ─────────────────────────────────────────────────

class EventType(str, Enum):
    COMMAND   = "TC"      # Telecommand sent
    TELEMETRY = "TM"      # Telemetry received
    INJECTION = "INJECT"  # Direct parameter injection
    MONITOR   = "MONITOR" # Temporal monitor event
    STEP      = "STEP"    # Formal procedure step
    INFO      = "INFO"    # General diagnostic info

@dataclass
class SimEvent:
    """A granular event captured during a procedure step."""
    t: float              # Simulation time
    event_type: EventType
    description: str
    details: Optional[str] = None

@dataclass
class StepResult:
    """Result of a single procedure step, enriched with events."""
    step_name:   str
    verdict:     Verdict
    detail:      str = ""
    requirement: str = ""
    events:      List[SimEvent] = field(default_factory=list)

# ── Core Result Classes ─────────────────────────────────────────────────────

class Verdict(str, Enum):
    PASS          = "PASS"
    FAIL          = "FAIL"
    INCONCLUSIVE  = "INCONCLUSIVE"
    ERROR         = "ERROR"

@dataclass
class ProcedureResult:
    procedure_id:   str
    title:          str
    requirement:    str
    verdict:        Verdict
    duration_s:     float
    steps:          list[StepResult] = field(default_factory=list)
    error:          Optional[str] = None
    seed:           Optional[int] = None

    def summary(self) -> str:
        lines = [
            f"{'='*60}",
            f"Procedure: {self.procedure_id} — {self.title}",
            f"Verdict: {self.verdict.value} | Duration: {self.duration_s:.1f}s",
            f"{'='*60}",
        ]
        for step in self.steps:
            lines.append(f"[{step.verdict.value:<4}] {step.step_name}")
            for ev in step.events:
                lines.append(f"      t={ev.t:>6.1f}s | {ev.event_type:<6} | {ev.description}")
        return "\n".join(lines)

class ProcedureError(Exception):
    pass

# ── Background Monitoring ───────────────────────────────────────────────────

class ParameterMonitor:
    def __init__(
        self,
        store: ParameterStore,
        parameter: str,
        less_than: Optional[float] = None,
        greater_than: Optional[float] = None,
        requirement: str = "",
        poll_interval: float = 0.05,
    ) -> None:
        self._store = store
        self._parameter = parameter
        self._less_than = less_than
        self._greater_than = greater_than
        self._requirement = requirement
        self._poll_interval = poll_interval
        self._violations: list[dict] = []
        self._samples = 0
        self._max_value: Optional[float] = None
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while self._running:
            entry = self._store.read(self._parameter)
            if entry is not None:
                v = entry.value
                self._samples += 1
                if self._max_value is None or v > self._max_value: self._max_value = v
                if self._less_than is not None and v >= self._less_than:
                    self._violations.append({"t": entry.t, "v": v, "limit": self._less_than, "cond": "less_than"})
                elif self._greater_than is not None and v <= self._greater_than:
                    self._violations.append({"t": entry.t, "v": v, "limit": self._greater_than, "cond": "greater_than"})
            time.sleep(self._poll_interval)

    def stop(self) -> None:
        self._running = False
        if self._thread.is_alive():
            self._thread.join(timeout=1.0)

    def assert_no_violations(self) -> None:
        self.stop()
        if self._violations:
            v = self._violations[0]
            raise ProcedureError(f"Monitor violation: {self._parameter}={v['v']:.2f} at t={v['t']:.1f}s")

# ── The Enriched Context ────────────────────────────────────────────────────

class ProcedureContext:
    def __init__(
        self,
        master: Optional[SimulationMaster],
        store: ParameterStore,
        cmd_store: CommandStore,
        apid: int = 0x010,
    ) -> None:
        self._master = master
        self._store = store
        self._cmd_store = cmd_store
        self._apid = apid
        self._seq = 1
        self._active_monitors: list[ParameterMonitor] = []
        self._events: list[SimEvent] = [] # Current step event buffer

    def _log_event(self, event_type: EventType, description: str, details: Optional[str] = None) -> None:
        """Internal helper to capture automated events."""
        t = self.read_parameter("svf.sim_time") or 0.0
        self._events.append(SimEvent(round(t, 2), event_type, description, details))

    def inject(self, parameter: str, value: float) -> None:
        self._cmd_store.inject(parameter, value, source_id="procedure")
        self._log_event(EventType.INJECTION, f"Set {parameter} = {value}")

    def tc(self, service: int, subservice: int, data: bytes = b"", apid: Optional[int] = None) -> None:
        _apid = apid if apid is not None else self._apid
        pkt = PusTcPacket(apid=_apid, sequence_count=self._seq, service=service, subservice=subservice, app_data=data)
        self._seq = (self._seq + 1) % 16384
        tc_bytes = PusTcBuilder().build(pkt)

        target = "CommandStore"
        if self._master is not None:
            for model in self._master._models:
                if hasattr(model, "receive_tc"):
                    model.receive_tc(tc_bytes)
                    target = model.model_id
                    break
                    
        self._log_event(EventType.COMMAND, f"Sent TC({service},{subservice}) to {target}", details=tc_bytes.hex())
        if target == "CommandStore":
            self._cmd_store.inject(f"svf.tc.{service}.{subservice}", float(len(tc_bytes)), source_id="procedure")

    def expect_tm(self, service: int, subservice: int, timeout: float = 5.0) -> None:
        start_wait = time.monotonic()
        while (time.monotonic() - start_wait) < timeout:
            entry = self._store.read(f"svf.tm.{service}.{subservice}.received")
            if entry is not None and entry.value > 0.0:
                self._log_event(EventType.TELEMETRY, f"Received TM({service},{subservice})")
                return
            time.sleep(0.05)
        raise ProcedureError(f"Timeout waiting for TM({service},{subservice})")

    def wait_until(self, condition: Callable[[ParameterStore], bool], timeout: float = 60.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if condition(self._store):
                self._log_event(EventType.INFO, "Wait condition met")
                return True
            time.sleep(0.05)
        raise ProcedureError(f"Condition not met within {timeout}s")

    def wait(self, seconds: float) -> None:
        start_t = self.read_parameter("svf.sim_time") or 0.0
        target_t = start_t + seconds
        self._log_event(EventType.INFO, f"Waiting {seconds}s (until t={target_t:.1f}s)")
        while (self.read_parameter("svf.sim_time") or 0.0) < target_t:
            time.sleep(0.05)

    def read_parameter(self, parameter: str) -> Optional[float]:
        entry = self._store.read(parameter)
        return entry.value if entry else None

    def assert_parameter(self, parameter: str, less_than: Optional[float] = None, greater_than: Optional[float] = None, equals: Optional[float] = None, tolerance: float = 1e-6) -> None:
        val = self.read_parameter(parameter)
        if val is None: raise ProcedureError(f"Param '{parameter}' not found")
        if (less_than is not None and val >= less_than) or \
           (greater_than is not None and val <= greater_than) or \
           (equals is not None and abs(val - equals) > tolerance):
            raise ProcedureError(f"Assertion failed for {parameter}: current={val:.4f}")
        self._log_event(EventType.INFO, f"Verified {parameter}")

    def expect_always(self, parameter: str, less_than: Optional[float] = None, greater_than: Optional[float] = None) -> None:
        monitor = ParameterMonitor(self._store, parameter, less_than, greater_than)
        self._active_monitors.append(monitor)
        self._log_event(EventType.MONITOR, f"Active invariant: {parameter}")

# ── The Base Procedure ──────────────────────────────────────────────────────

class Procedure:
    id: str = ""
    title: str = ""
    requirement: str = ""

    def __init__(self) -> None:
        self._steps: list[StepResult] = []
        self._ctx: Optional[ProcedureContext] = None

    def step(self, name: str) -> None:
        # If there was a previous step, finalize it by moving events from context
        if self._ctx and self._ctx._events:
            if self._steps:
                self._steps[-1].events.extend(self._ctx._events)
                self._ctx._events = []
        
        logger.info(f"[{self.id}] Step: {name}")
        self._steps.append(StepResult(name, Verdict.PASS))
        if self._ctx:
            self._ctx._log_event(EventType.STEP, name)

    def run(self, ctx: ProcedureContext) -> None:
        raise NotImplementedError()

    def execute(self, master: Optional[SimulationMaster], store: ParameterStore, cmd_store: CommandStore, apid: int = 0x010) -> ProcedureResult:
        self._ctx = ProcedureContext(master, store, cmd_store, apid)
        t_start = time.monotonic()
        verdict = Verdict.PASS
        error_msg = None

        try:
            self.run(self._ctx)
            # Finalize last step events
            if self._steps and self._ctx._events:
                self._steps[-1].events.extend(self._ctx._events)
        except ProcedureError as e:
            verdict = Verdict.FAIL
            error_msg = str(e)
            if self._steps:
                self._steps[-1].verdict = Verdict.FAIL
                self._steps[-1].detail = str(e)
        except Exception as e:
            verdict = Verdict.ERROR
            error_msg = f"{type(e).__name__}: {e}"

        # Post-check invariants
        for mon in self._ctx._active_monitors:
            try:
                mon.assert_no_violations()
            except ProcedureError as e:
                if verdict == Verdict.PASS:
                    verdict = Verdict.FAIL
                    error_msg = str(e)
                    self._steps.append(StepResult(f"Invariant: {mon._parameter}", Verdict.FAIL, str(e)))

        return ProcedureResult(self.id, self.title, self.requirement, verdict, time.monotonic() - t_start, self._steps, error_msg, getattr(master, "seed", None))
