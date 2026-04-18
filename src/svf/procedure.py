"""
SVF Structured Test Procedure API

Provides a Python base class that makes test procedures read like
structured validation procedures while remaining plain Python.

Usage:
    from svf.procedure import Procedure, ProcedureContext

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

from svf.parameter_store import ParameterStore
from svf.command_store import CommandStore
from svf.simulation import SimulationMaster

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

        # Inject via CommandStore — OBCEmulatorAdapter picks it up
        self._cmd_store.inject(
            name=f"svf.tc.{service}.{subservice}",
            value=float(len(tc_bytes)),
            source_id="procedure",
        )
        # Store raw bytes for direct adapter use
        self._cmd_store.inject(
            name="svf.tc.raw",
            value=float(len(tc_bytes)),
            source_id="procedure",
        )
        logger.info(f"[ctx] TC({service},{subservice}) sent")

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
