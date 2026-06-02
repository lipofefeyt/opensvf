"""
MySat-1 FreeRTOS HIL Validation Procedures

Validates that the SVF platform meets the timing and diagnostic requirements
for Hardware-in-the-Loop sessions with an STM32H750 running FreeRTOS OBSW:

  TC-RTOS-001  Tick p95 latency < 3 500 ms (IWDG keepalive margin)
  TC-RTOS-002  SRDB dhs.obc.freertos.* PUS ID namespace has no collisions
  TC-RTOS-003  No FreeRTOS fault events detected during nominal operation

In pipe/socket OBC mode the procedures exercise the real diagnostics path.
In stub mode they verify the platform invariants that hold in both modes.

Requirements covered: MIS-RTOS-001, MIS-RTOS-002, MIS-RTOS-003
"""
from __future__ import annotations

from pathlib import Path

import yaml  # type: ignore[import-untyped]

from svf.campaign.procedure import Procedure, ProcedureContext, ProcedureError


# PUS IDs reserved for dhs.obc.freertos.* telemetry (SVF-DEV-180).
_FREERTOS_RESERVED_LOW  = 0x4020
_FREERTOS_RESERVED_HIGH = 0x402F  # inclusive

# STM32H750 IWDG timeout is 4 000 ms; 3 500 ms leaves 500 ms jitter margin.
_IWDG_P95_LIMIT_MS = 3_500.0

# Path to the SRDB baseline DHS file, resolved relative to this file.
_DHS_YAML = Path(__file__).resolve().parent.parent.parent / "srdb" / "baseline" / "dhs.yaml"


class TickTimingCompliant(Procedure):
    """
    TC-RTOS-001 — Tick p95 wall-clock latency stays within IWDG margin.

    Runs the simulation for 10 s of sim-time, then reads the rolling tick
    statistics from SimulationMaster.  The p95 must be below 3 500 ms so
    that the OBCEmulatorAdapter always kicks the OBSW watchdog before the
    STM32H750 IWDG fires (4 000 ms timeout).

    In stub/non-realtime mode ticks complete in microseconds, so this
    passes trivially and demonstrates the constraint is always met.
    """

    id          = "TC-RTOS-001"
    title       = "Tick p95 latency within IWDG keepalive budget"
    requirement = "MIS-RTOS-001"

    def run(self, ctx: ProcedureContext) -> None:
        self.step("Run simulation for 10 s to accumulate tick timing samples")
        ctx.wait(10.0)

        self.step("Read rolling tick statistics from SimulationMaster")
        if ctx._master is None:
            raise ProcedureError("SimulationMaster not available — cannot read tick stats")
        stats = ctx._master.tick_stats()
        if stats is None:
            raise ProcedureError("tick_stats() returned None — fewer than 2 ticks elapsed")

        self.step(
            f"Assert p95 tick latency < {_IWDG_P95_LIMIT_MS:.0f} ms "
            f"(measured: {stats.p95_ms:.1f} ms, p99: {stats.p99_ms:.1f} ms, "
            f"mean: {stats.mean_ms:.1f} ms over {stats.count} samples)"
        )
        if stats.p95_ms >= _IWDG_P95_LIMIT_MS:
            raise ProcedureError(
                f"p95 tick latency {stats.p95_ms:.1f} ms exceeds "
                f"IWDG budget {_IWDG_P95_LIMIT_MS:.0f} ms"
            )


class FreeRTOSNamespaceIntact(Procedure):
    """
    TC-RTOS-002 — SRDB dhs.obc.freertos.* PUS ID namespace has no collisions.

    Loads the SRDB DHS baseline YAML directly and checks that no existing
    parameter has been assigned a PUS parameter_id in the reserved range
    0x4020–0x402F.  This is a static check that runs identically in all
    OBC modes (stub, pipe, socket).
    """

    id          = "TC-RTOS-002"
    title       = "FreeRTOS PUS ID namespace 0x4020–0x402F has no collisions"
    requirement = "MIS-RTOS-002"

    def run(self, ctx: ProcedureContext) -> None:
        self.step("Load SRDB DHS baseline YAML")
        if not _DHS_YAML.exists():
            raise ProcedureError(f"SRDB DHS baseline not found: {_DHS_YAML}")
        data = yaml.safe_load(_DHS_YAML.read_text())

        self.step("Scan parameter PUS IDs for reserved-namespace collisions")
        reserved = set(range(_FREERTOS_RESERVED_LOW, _FREERTOS_RESERVED_HIGH + 1))
        used_ids: dict[int, str] = {}
        for name, param in data.get("parameters", {}).items():
            pid = param.get("pus", {}).get("parameter_id")
            if pid is not None:
                used_ids[int(pid)] = name

        collisions = {pid: used_ids[pid] for pid in reserved if pid in used_ids}
        if collisions:
            detail = ", ".join(
                f"{hex(pid)}={name}" for pid, name in sorted(collisions.items())
            )
            raise ProcedureError(
                f"PUS IDs in reserved FreeRTOS namespace already used: {detail}"
            )

        self.step(
            f"Namespace 0x{_FREERTOS_RESERVED_LOW:04X}–"
            f"0x{_FREERTOS_RESERVED_HIGH:04X} is clean "
            f"({len(reserved)} IDs reserved, 0 collisions)"
        )


class OBCDiagnosticsClean(Procedure):
    """
    TC-RTOS-003 — No FreeRTOS fault events detected during nominal operation.

    Waits 10 s of sim-time, then asserts that the FreeRTOS diagnostic
    counters written by OBCEmulatorAdapter._on_obsw_freertos_diagnostic()
    are absent or zero.

    In stub mode these parameters are never written (no stderr stream), so
    their absence is treated as 0 events — the procedure passes correctly.
    In pipe/socket mode a real stack-overflow or IWDG reset would set the
    counter to ≥ 1 and fail the procedure.
    """

    id          = "TC-RTOS-003"
    title       = "No FreeRTOS fault events during nominal 10 s session"
    requirement = "MIS-RTOS-003"

    def run(self, ctx: ProcedureContext) -> None:
        self.step("Run nominal OBC operation for 10 s")
        ctx.wait(10.0)

        self.step("Assert no FreeRTOS stack overflow events")
        count = ctx.read_parameter("svf.obc.freertos.stack_overflow_count")
        if count is not None and count > 0.0:
            raise ProcedureError(
                f"FreeRTOS stack overflow detected: "
                f"svf.obc.freertos.stack_overflow_count = {count:.0f}"
            )

        self.step("Assert no FreeRTOS IWDG reset events")
        count = ctx.read_parameter("svf.obc.freertos.iwdg_reset_count")
        if count is not None and count > 0.0:
            raise ProcedureError(
                f"FreeRTOS IWDG reset detected: "
                f"svf.obc.freertos.iwdg_reset_count = {count:.0f}"
            )

        self.step("FreeRTOS diagnostics clean — no fault events in 10 s session")
