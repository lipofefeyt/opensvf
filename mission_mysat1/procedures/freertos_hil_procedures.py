"""
MySat-1 FreeRTOS HIL Integration Procedures

Validates the full SVF ↔ openobsw wire-protocol round-trip when connected to
a real obsw_sim binary (pipe mode) or an STM32H750 via Renode (socket mode).

All procedures raise ProcedureInconclusiveError when no OBCEmulatorAdapter
is present (i.e. the campaign was run against the stub spacecraft config).
Use spacecraft_hil.yaml as the campaign spacecraft:

  svf campaign mission_mysat1/campaigns/freertos_hil_campaign.yaml

Requirements covered: MIS-HIL-001, MIS-HIL-002, MIS-HIL-003, MIS-HIL-004
"""
from __future__ import annotations

import struct
import time

from svf.campaign.procedure import (
    Procedure,
    ProcedureContext,
    ProcedureError,
    ProcedureInconclusiveError,
)
from svf.models.dhs.obc_emulator import OBCEmulatorAdapter

# OBC HK set IDs (openobsw srdb/data/dhs.yaml)
_HK_SID_DHS_OBC = 3   # DHS_OBC_HK: mode, obt, watchdog, mem, health, reset, cpu

# PUS service/subservice shorthand
_S3_ENABLE_HK  = (3, 5)
_S17_PING      = (17, 1)

# IWDG margin (STM32H750 timeout 4 000 ms, 500 ms headroom)
_IWDG_P95_LIMIT_MS = 3_500.0


def _get_emulator(ctx: ProcedureContext) -> OBCEmulatorAdapter:
    """
    Return the OBCEmulatorAdapter from the running simulation, or raise
    ProcedureInconclusiveError if the spacecraft is in stub mode.
    """
    if ctx._master is None:
        raise ProcedureInconclusiveError(
            "SimulationMaster not available — cannot run HIL procedure"
        )
    for model in ctx._master._models:
        if isinstance(model, OBCEmulatorAdapter):
            return model
    raise ProcedureInconclusiveError(
        "No OBCEmulatorAdapter found — run this campaign with "
        "spacecraft_hil.yaml (obsw.type: pipe or socket), not the stub config"
    )


class PingPong(Procedure):
    """
    TC-HIL-001 — TC(17,1) Are-You-Alive → TM(17,2) pong within 2 s.

    The most basic HIL smoke test: confirms wire-protocol framing, TC delivery,
    and TM parsing are all working end-to-end on the first connection tick.
    """

    id          = "TC-HIL-001"
    title       = "TC(17,1) ping → TM(17,2) pong within 2 s"
    requirement = "MIS-HIL-001"

    def run(self, ctx: ProcedureContext) -> None:
        self.step("Verify OBCEmulatorAdapter is active (pipe or socket mode)")
        _get_emulator(ctx)   # raises INCONCLUSIVE if stub

        self.step("Wait for OBSW to boot and first tick to complete")
        ctx.wait(1.0)

        self.step("Send TC(17,1) Are-You-Alive")
        ctx.tc(*_S17_PING)

        self.step("Expect TM(17,2) pong within 2 s")
        ctx.expect_tm(17, 2, timeout=2.0)


class HkTelemetryReception(Procedure):
    """
    TC-HIL-002 — Enable DHS_OBC_HK (S3, SID 3) and verify OBT advances.

    Sends TC(3,5) to enable HK reporting at 1-tick intervals, then polls the
    ParameterStore for obc.obt to confirm the OBSW is advancing on-board time
    and that SVF is correctly parsing the TM(3,25) DHS_OBC_HK report.
    """

    id          = "TC-HIL-002"
    title       = "DHS_OBC_HK received and OBT advancing within 5 s"
    requirement = "MIS-HIL-002"

    def run(self, ctx: ProcedureContext) -> None:
        self.step("Verify OBCEmulatorAdapter is active")
        _get_emulator(ctx)

        self.step("Wait for OBSW boot")
        ctx.wait(1.0)

        self.step("Enable DHS_OBC_HK reporting (TC(3,5), SID=3, interval=1)")
        # TC(3,5) app_data: set_id (u8) + interval_ticks (u32 BE)
        app_data = struct.pack(">BI", _HK_SID_DHS_OBC, 1)
        ctx.tc(*_S3_ENABLE_HK, data=app_data)

        self.step("Wait up to 5 s for OBT to appear and advance")
        obt_start: list[float] = []

        def _obt_advancing(store: "object") -> bool:  # type: ignore[type-arg]
            from svf.stores.parameter_store import ParameterStore
            if not isinstance(store, ParameterStore):
                return False
            e = store.read("dhs.obc.obt")
            if e is None:
                return False
            if not obt_start:
                obt_start.append(e.value)
                return False
            return e.value > obt_start[0]

        ctx.wait_until(_obt_advancing, timeout=5.0)

        self.step("Verify OBC mode is SAFE (0) at boot")
        ctx.assert_parameter("dhs.obc.mode", less_than=0.5)

        self.step("Verify OBC health is nominal (0)")
        ctx.assert_parameter("dhs.obc.health", less_than=0.5)


class TickSyncStability(Procedure):
    """
    TC-HIL-003 — 30 s of continuous tick sync + p95 within IWDG margin.

    Runs the simulation for 30 sim-seconds and asserts:
      - SimulationMaster has not raised a desync error (implicit: still running)
      - tick_stats().p95_ms < 3 500 ms (500 ms margin before STM32H750 IWDG fires)

    In pipe mode each tick waits for the OBSW 0xFF sync byte; a missed sync
    increments the consecutive desync counter and raises RuntimeError at 3.
    If this procedure completes, sync was never lost for 300 consecutive ticks.
    """

    id          = "TC-HIL-003"
    title       = "30 s tick sync stability + p95 latency within IWDG budget"
    requirement = "MIS-HIL-003"

    def run(self, ctx: ProcedureContext) -> None:
        self.step("Verify OBCEmulatorAdapter is active")
        _get_emulator(ctx)

        self.step("Run 30 s of nominal HIL operation")
        ctx.wait(30.0)

        self.step("Read tick timing statistics")
        if ctx._master is None:
            raise ProcedureError("SimulationMaster not available")
        stats = ctx._master.tick_stats()
        if stats is None:
            raise ProcedureError("tick_stats() returned None — too few ticks")

        self.step(
            f"Assert p95 tick latency < {_IWDG_P95_LIMIT_MS:.0f} ms "
            f"(p95={stats.p95_ms:.1f} ms, p99={stats.p99_ms:.1f} ms, "
            f"mean={stats.mean_ms:.1f} ms, n={stats.count})"
        )
        if stats.p95_ms >= _IWDG_P95_LIMIT_MS:
            raise ProcedureError(
                f"Tick p95 {stats.p95_ms:.1f} ms exceeds "
                f"IWDG budget {_IWDG_P95_LIMIT_MS:.0f} ms"
            )


class FreeRTOSDiagnosticsClean(Procedure):
    """
    TC-HIL-004 — No FreeRTOS fault events in a 30 s HIL session.

    Monitors svf.obc.freertos.stack_overflow_count and
    svf.obc.freertos.iwdg_reset_count for the full 30-second session.
    Any non-zero value means the OBSW emitted a fault diagnostic on stderr
    (vApplicationStackOverflowHook or IWDG reset at boot).

    A FAIL here means the openobsw binary has a real FreeRTOS fault; fix
    the firmware before running further HIL campaigns.
    """

    id          = "TC-HIL-004"
    title       = "No FreeRTOS fault events in 30 s HIL session"
    requirement = "MIS-HIL-004"

    def run(self, ctx: ProcedureContext) -> None:
        self.step("Verify OBCEmulatorAdapter is active")
        emulator = _get_emulator(ctx)

        self.step("Run 30 s nominal HIL session under FreeRTOS diagnostic watch")
        ctx.wait(30.0)

        self.step("Assert no stack overflow events")
        overflow = emulator._freertos_stack_overflow_count
        if overflow > 0:
            raise ProcedureError(
                f"FreeRTOS stack overflow(s) detected: count={overflow}. "
                "Check task stack sizes in openobsw (obsw/task/*.h)."
            )

        self.step("Assert no IWDG reset events")
        iwdg = emulator._freertos_iwdg_reset_count
        if iwdg > 0:
            raise ProcedureError(
                f"FreeRTOS IWDG reset(s) detected: count={iwdg}. "
                "Tick latency may be exceeding the 4 000 ms watchdog timeout."
            )

        self.step(
            f"FreeRTOS diagnostics clean over 30 s "
            f"(stack_overflow=0, iwdg_reset=0)"
        )
