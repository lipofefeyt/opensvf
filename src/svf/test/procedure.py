"""
SVF Structured Test Procedure API

Provides a Python base class that makes test procedures read like
structured validation procedures while remaining plain Python.

Usage:
    from svf.test.procedure import Procedure, ProcedureContext

    class BdotConvergence(Procedure):
        id          = "TC-AOCS-001"
        title       = "B-dot detumbling convergence"
        requirement = "MIS-AOCS-042"

        def run(self, ctx: ProcedureContext) -> None:
            self.step("Power on AOCS sensors")
            ctx.inject("aocs.mag.power_enable", 1.0)
            ctx.inject("aocs.gyro.power_enable", 1.0)

            self.step("Verify ping")
            ctx.tc(17, 1)
            ctx.expect_tm(17, 2, timeout=5.0)

            self.step("Wait for detumbling")
            ctx.wait(60.0)

            self.step("Verify convergence")
            ctx.assert_parameter(
                "aocs.truth.rate_magnitude",
                less_than=0.1,
                requirement="MIS-AOCS-042",
            )

Implements: SVF-DEV-120
"""
from __future__ import annotations

import logging
import struct
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

from svf.stores.parameter_store import ParameterStore
from svf.stores.command_store import CommandStore
from svf.sim.simulation import SimulationMaster

logger = logging.getLogger(__name__)


class Verdict(str, Enum):
    PASS          = "PASS"
    FAIL          = "FAIL"
    INCONCLUSIVE  = "INCONCLUSIVE"
    ERROR         = "ERROR"


@dataclass
class StepResult:
    """Result of a single procedure step."""
    step_name:   str
    verdict:     Verdict
    detail:      str = ""
    requirement: str = ""


@dataclass
class ProcedureResult:
    """Aggregated result of a complete procedure run."""
    procedure_id:   str
    title:          str
    requirement:    str
    verdict:        Verdict
    duration_s:     float
    steps:          list[StepResult] = field(default_factory=list)
    error:          Optional[str] = None

    def summary(self) -> str:
        lines = [
            f"{'='*60}",
            f"Procedure: {self.procedure_id} — {self.title}",
            f"Requirement: {self.requirement}",
            f"Verdict: {self.verdict.value}",
            f"Duration: {self.duration_s:.1f}s",
            f"{'='*60}",
        ]
        for step in self.steps:
            verdict_str = f"[{step.verdict.value}]"
            lines.append(
                f"  {verdict_str:<8} {step.step_name}"
            )
            if step.detail:
                lines.append(f"           {step.detail}")
        return "\n".join(lines)


class ProcedureError(Exception):
    """Raised when a procedure assertion fails."""




@dataclass
class MonitorViolation:
    """A single violation recorded by a ParameterMonitor."""
    sim_time: float
    value:    float
    limit:    float
    condition: str  # "less_than" | "greater_than"


@dataclass
class MonitorResult:
    """Result from a completed ParameterMonitor run."""
    parameter:   str
    requirement: str
    compliant:   bool
    violations:  list[MonitorViolation]
    max_value:   Optional[float]
    min_value:   Optional[float]
    samples:     int

    def summary_str(self) -> str:
        status = "COMPLIANT" if self.compliant else f"VIOLATED ({len(self.violations)} times)"
        return (
            f"Monitor({self.parameter}): {status} "
            f"over {self.samples} samples"
        )


class ParameterMonitor:
    """
    Background monitor that continuously checks a parameter condition.

    Started by ctx.monitor() and runs until stop() is called
    or assert_no_violations() / summary() is called.

    Usage:
        monitor = ctx.monitor("aocs.truth.rate_magnitude", less_than=0.1)
        ctx.wait(60.0)
        monitor.assert_no_violations()
    """

    def __init__(
        self,
        store:        "ParameterStore",
        parameter:    str,
        less_than:    Optional[float] = None,
        greater_than: Optional[float] = None,
        requirement:  str = "",
        poll_interval: float = 0.05,
    ) -> None:
        import threading
        self._store        = store
        self._parameter    = parameter
        self._less_than    = less_than
        self._greater_than = greater_than
        self._requirement  = requirement
        self._poll_interval = poll_interval
        self._violations:  list[MonitorViolation] = []
        self._samples      = 0
        self._max_value:   Optional[float] = None
        self._min_value:   Optional[float] = None
        self._running      = True
        self._thread       = threading.Thread(
            target=self._run, daemon=True
        )
        self._thread.start()

    def _run(self) -> None:
        import time
        while self._running:
            entry = self._store.read(self._parameter)
            if entry is not None:
                v = entry.value
                self._samples += 1
                if self._max_value is None or v > self._max_value:
                    self._max_value = v
                if self._min_value is None or v < self._min_value:
                    self._min_value = v
                if self._less_than is not None and v >= self._less_than:
                    self._violations.append(MonitorViolation(
                        sim_time=entry.t,
                        value=v,
                        limit=self._less_than,
                        condition="less_than",
                    ))
                elif self._greater_than is not None and v <= self._greater_than:
                    self._violations.append(MonitorViolation(
                        sim_time=entry.t,
                        value=v,
                        limit=self._greater_than,
                        condition="greater_than",
                    ))
            time.sleep(self._poll_interval)

    def stop(self) -> None:
        """Stop the background monitoring thread."""
        self._running = False
        self._thread.join(timeout=1.0)

    def assert_no_violations(self) -> None:
        """
        Stop monitor and assert no violations occurred.
        Raises ProcedureError with first violation detail.
        """
        self.stop()
        if self._violations:
            v = self._violations[0]
            cond = f"< {v.limit}" if v.condition == "less_than" else f"> {v.limit}"
            raise ProcedureError(
                f"Monitor violation: {self._parameter} = {v.value:.6f} "
                f"(required {cond}) at t={v.sim_time:.2f}s. "
                f"{len(self._violations)} total violations over "
                f"{self._samples} samples."
            )
        logger.info(
            f"[monitor] {self._parameter}: COMPLIANT "
            f"({self._samples} samples, "
            f"max={self._max_value:.6f})"
        )

    def summary(self) -> MonitorResult:
        """Stop monitor and return full result."""
        self.stop()
        return MonitorResult(
            parameter=self._parameter,
            requirement=self._requirement,
            compliant=len(self._violations) == 0,
            violations=list(self._violations),
            max_value=self._max_value,
            min_value=self._min_value,
            samples=self._samples,
        )

class ProcedureContext:
    """
    Runtime context passed to Procedure.run().

    Provides: inject, tc, expect_tm, wait, assert_parameter,
              read_parameter.
    """

    def __init__(
        self,
        master:    Optional[SimulationMaster],
        store:     ParameterStore,
        cmd_store: CommandStore,
        apid:      int = 0x010,
    ) -> None:
        self._master    = master
        self._store     = store
        self._cmd_store = cmd_store
        self._apid      = apid
        self._tm_buffer: list[tuple[int, int, bytes]] = []

    def inject(self, parameter: str, value: float) -> None:
        """Inject a parameter value into the CommandStore."""
        self._cmd_store.inject(
            name=parameter,
            value=value,
            source_id="procedure",
        )
        logger.debug(f"[ctx] inject {parameter} = {value}")

    def tc(
        self,
        service:    int,
        subservice: int,
        data:       bytes = b"",
        apid:       Optional[int] = None,
    ) -> None:
        """
        Send a PUS-C telecommand.
        Builds a minimal space packet and queues it for the OBSW.
        """
        _apid = apid if apid is not None else self._apid
        secondary = bytes([0x20, service, subservice, 0x00]) + data
        header = struct.pack(
            ">HHH",
            0x1800 | (_apid & 0x7FF),
            0xC000,
            len(secondary) - 1,
        )
        tc_bytes = header + secondary

        # Find OBC emulator in master models and send directly
        if self._master is not None:
            for model in self._master._models:
                if hasattr(model, "receive_tc"):
                    model.receive_tc(tc_bytes)
                    eq_id = model.equipment_id if hasattr(model, "equipment_id") else "obc"
                    logger.info(
                        f"[ctx] TC({service},{subservice}) sent via {eq_id}"
                    )
                    return
        # Fallback: inject via CommandStore
        self._cmd_store.inject(
            name=f"svf.tc.{service}.{subservice}",
            value=float(len(tc_bytes)),
            source_id="procedure",
        )
        logger.warning(
            f"[ctx] TC({service},{subservice}): no OBC emulator found, "
            f"injected via CommandStore only"
        )

    def expect_tm(
        self,
        service:    int,
        subservice: int,
        timeout:    float = 5.0,
    ) -> None:
        """
        Wait for a TM packet with the given service/subservice.
        Polls the ParameterStore for TM receipt confirmation.
        Raises ProcedureError on timeout.
        """
        param = f"svf.tm.{service}.{subservice}.received"
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            entry = self._store.read(param)
            if entry is not None and entry.value > 0.0:
                logger.info(f"[ctx] TM({service},{subservice}) received")
                return
            time.sleep(0.05)
        raise ProcedureError(
            f"Timeout waiting for TM({service},{subservice}) "
            f"after {timeout}s"
        )

    def wait(self, seconds: float) -> None:
        """Wait for simulation time to advance by given seconds."""
        start = self._store.read("svf.sim_time")
        start_t = start.value if start is not None else 0.0
        target_t = start_t + seconds
        deadline = time.monotonic() + seconds * 10 + 5.0  # wall-clock guard

        while time.monotonic() < deadline:
            entry = self._store.read("svf.sim_time")
            if entry is not None and entry.value >= target_t:
                logger.debug(f"[ctx] wait({seconds}s) complete")
                return
            time.sleep(0.01)
        logger.warning(
            f"[ctx] wait({seconds}s): simulation time did not advance — "
            f"wall-clock timeout"
        )

    def read_parameter(self, parameter: str) -> Optional[float]:
        """Read a parameter value from the ParameterStore."""
        entry = self._store.read(parameter)
        return entry.value if entry is not None else None

    def monitor(
        self,
        parameter:    str,
        less_than:    Optional[float] = None,
        greater_than: Optional[float] = None,
        requirement:  str = "",
        poll_interval: float = 0.05,
    ) -> "ParameterMonitor":
        """
        Start a continuous background monitor on a parameter.

        The monitor polls the ParameterStore at poll_interval and records
        any violations of the given condition.

        Args:
            parameter:    SRDB canonical parameter name
            less_than:    Violation if value >= this threshold
            greater_than: Violation if value <= this threshold
            requirement:  Requirement ID for traceability
            poll_interval: Polling interval in seconds (default 0.05)

        Returns:
            ParameterMonitor — call assert_no_violations() or summary()

        Example:
            monitor = ctx.monitor("aocs.truth.rate_magnitude", less_than=0.1)
            ctx.wait(60.0)
            monitor.assert_no_violations()
        """
        mon = ParameterMonitor(
            store=self._store,
            parameter=parameter,
            less_than=less_than,
            greater_than=greater_than,
            requirement=requirement,
            poll_interval=poll_interval,
        )
        logger.info(
            f"[ctx] monitor started: {parameter} "
            f"{'< ' + str(less_than) if less_than is not None else ''}"
            f"{'> ' + str(greater_than) if greater_than is not None else ''}"
        )
        return mon

    def inject_equipment_fault(
        self,
        equipment_id: str,
        port:         str,
        fault_type:   str,
        value:        float = 0.0,
        duration_s:   float = 0.0,
        seed:         Optional[int] = None,
    ) -> None:
        """
        Inject a fault on a specific equipment port.

        Args:
            equipment_id: Equipment ID as defined in spacecraft.yaml
            port:         SRDB canonical port name
            fault_type:   "stuck" | "noise" | "bias" | "scale" | "fail"
            value:        Fault value (std_dev for noise, offset for bias,
                          factor for scale, fixed value for stuck)
            duration_s:   Fault duration in seconds (0.0 = permanent)
            seed:         Optional seed for reproducible noise faults

        Example:
            ctx.inject_equipment_fault(
                "str1", "aocs.str1.quaternion_w",
                fault_type="stuck", value=0.0, duration_s=10.0
            )
        """
        from svf.core.equipment_fault import EquipmentFaultEngine, EquipmentFault, FaultMode

        sim_time = self._store.read("svf.sim_time")
        t = sim_time.value if sim_time is not None else 0.0

        # Store fault spec in CommandStore for the equipment to pick up
        # via a special fault namespace
        fault_key = f"svf.fault.{equipment_id}.{port}"
        self._cmd_store.inject(
            name=fault_key,
            value=value,
            source_id="procedure.fault_engine",
        )
        # Also store metadata
        self._cmd_store.inject(
            name=f"{fault_key}.type",
            value=float(list(FaultMode).index(FaultMode(fault_type))),
            source_id="procedure.fault_engine",
        )
        self._cmd_store.inject(
            name=f"{fault_key}.duration",
            value=duration_s,
            source_id="procedure.fault_engine",
        )

        # Direct injection via master models if available
        if self._master is not None:
            from svf.core.equipment_fault import EquipmentFaultEngine, EquipmentFault, FaultMode
            for model in self._master._models:
                if not hasattr(model, "equipment_id"):
                    continue
                if model.equipment_id != equipment_id:
                    continue
                if not hasattr(model, "_fault_engine"):
                    continue
                if model._fault_engine is None:
                    model._fault_engine = EquipmentFaultEngine(
                        equipment_id, seed=seed
                    )
                model._fault_engine.inject(EquipmentFault(
                    port=port,
                    fault_type=FaultMode(fault_type),
                    value=value,
                    duration_s=duration_s,
                    injected_at=t,
                    seed=seed,
                ))
                logger.info(
                    f"[ctx] fault injected: {equipment_id}.{port} "
                    f"type={fault_type} value={value} duration={duration_s}s"
                )
                return
        logger.warning(
            f"[ctx] inject_equipment_fault: equipment '{equipment_id}' "
            f"not found in master models"
        )

    def clear_equipment_faults(self, equipment_id: str) -> None:
        """
        Clear all active faults on a given equipment.

        Args:
            equipment_id: Equipment ID as defined in spacecraft.yaml
        """
        if self._master is not None:
            for model in self._master._models:
                if not hasattr(model, "equipment_id"):
                    continue
                if model.equipment_id != equipment_id:
                    continue
                if hasattr(model, "_fault_engine") and model._fault_engine is not None:
                    model._fault_engine.clear()
                logger.info(f"[ctx] faults cleared: {equipment_id}")
                return
        logger.warning(
            f"[ctx] clear_equipment_faults: equipment '{equipment_id}' "
            f"not found"
        )

    def assert_parameter(
        self,
        parameter:   str,
        less_than:   Optional[float] = None,
        greater_than:Optional[float] = None,
        equals:      Optional[float] = None,
        tolerance:   float = 1e-6,
        requirement: str = "",
        message:     str = "",
    ) -> None:
        """
        Assert a parameter value meets a condition.
        Raises ProcedureError on failure.
        """
        value = self.read_parameter(parameter)
        if value is None:
            raise ProcedureError(
                f"Parameter '{parameter}' not found in ParameterStore"
            )

        fail_msg = None
        if less_than is not None and value >= less_than:
            fail_msg = (
                f"{parameter} = {value:.6f} "
                f"not less than {less_than:.6f}"
            )
        elif greater_than is not None and value <= greater_than:
            fail_msg = (
                f"{parameter} = {value:.6f} "
                f"not greater than {greater_than:.6f}"
            )
        elif equals is not None and abs(value - equals) > tolerance:
            fail_msg = (
                f"{parameter} = {value:.6f} "
                f"not equal to {equals:.6f} "
                f"(tolerance {tolerance})"
            )

        if fail_msg:
            detail = message or fail_msg
            raise ProcedureError(detail)

        detail = message or (
            f"{parameter} = {value:.6f} ✓"
        )
        logger.info(f"[ctx] assert_parameter: {detail}")


class Procedure:
    """
    Base class for structured test procedures.

    Subclass this and implement run(ctx). SVF will:
    - Provide a ProcedureContext with tc/expect_tm/wait/assert_parameter
    - Capture step-level verdicts
    - Trace results to requirements
    - Include in HTML campaign report (M21)

    Class attributes:
        id:          Unique procedure identifier (e.g. "TC-AOCS-001")
        title:       Human-readable title
        requirement: Primary requirement identifier

    Example:
        class BdotConvergence(Procedure):
            id          = "TC-AOCS-001"
            title       = "B-dot detumbling convergence"
            requirement = "MIS-AOCS-042"

            def run(self, ctx: ProcedureContext) -> None:
                self.step("Power on sensors")
                ctx.inject("aocs.mag.power_enable", 1.0)
                ctx.wait(60.0)
                ctx.assert_parameter(
                    "aocs.truth.rate_magnitude",
                    less_than=0.1,
                )
    """

    id:          str = ""
    title:       str = ""
    requirement: str = ""

    def __init__(self) -> None:
        self._steps:       list[StepResult] = []
        self._current_step: str = ""

    def step(self, name: str) -> None:
        """Mark the start of a named procedure step."""
        self._current_step = name
        logger.info(f"[{self.id}] Step: {name}")

    def run(self, ctx: ProcedureContext) -> None:
        """Override this method to implement the test procedure."""
        raise NotImplementedError(
            f"{self.__class__.__name__}.run() not implemented"
        )

    def execute(
        self,
        master:    Optional[SimulationMaster],
        store:     ParameterStore,
        cmd_store: CommandStore,
        apid:      int = 0x010,
    ) -> ProcedureResult:
        """
        Execute the procedure and return a ProcedureResult.
        Called by the campaign runner.
        """
        ctx = ProcedureContext(
            master=master,
            store=store,
            cmd_store=cmd_store,
            apid=apid,
        )

        t_start = time.monotonic()
        verdict = Verdict.INCONCLUSIVE
        error_msg: Optional[str] = None

        try:
            self.run(ctx)
            verdict = Verdict.PASS
            if self._current_step:
                self._steps.append(StepResult(
                    step_name=self._current_step,
                    verdict=Verdict.PASS,
                ))
        except ProcedureError as e:
            verdict = Verdict.FAIL
            error_msg = str(e)
            self._steps.append(StepResult(
                step_name=self._current_step or "assertion",
                verdict=Verdict.FAIL,
                detail=str(e),
            ))
            logger.error(f"[{self.id}] FAIL: {e}")
        except Exception as e:
            verdict = Verdict.ERROR
            error_msg = f"{type(e).__name__}: {e}"
            logger.error(f"[{self.id}] ERROR: {error_msg}")

        duration = time.monotonic() - t_start
        result = ProcedureResult(
            procedure_id=self.id or self.__class__.__name__,
            title=self.title or self.__class__.__name__,
            requirement=self.requirement,
            verdict=verdict,
            duration_s=duration,
            steps=list(self._steps),
            error=error_msg,
        )

        print(result.summary())
        return result
