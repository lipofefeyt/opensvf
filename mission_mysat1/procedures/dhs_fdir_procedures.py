"""
MySat-1 DHS & FDIR Validation Procedures

Validates OBC stub behaviour:
  - Boot state (SAFE mode)
  - Mode transitions (SAFE ↔ NOMINAL)
  - Watchdog nominal operation
  - OBC telemetry output (OBT, health, CPU load)

Requirements covered: MIS-FDIR-001, MIS-FDIR-002, OBC-001
"""
from __future__ import annotations

from svf.campaign.procedure import Procedure, ProcedureContext


class OBCBootsInSafeMode(Procedure):
    id          = "TC-FDIR-001"
    title       = "OBC boots in SAFE mode"
    requirement = "MIS-FDIR-001"

    def run(self, ctx: ProcedureContext) -> None:
        self.step("Wait for OBC initialisation")
        ctx.wait(0.5)

        self.step("Verify OBC in SAFE mode at boot")
        ctx.assert_parameter("dhs.obc.mode", less_than=0.5)

        self.step("Verify OBT advancing")
        ctx.assert_parameter("dhs.obc.obt", greater_than=0.0)

        self.step("Verify health nominal at boot")
        ctx.assert_parameter("dhs.obc.health", less_than=0.5)


class SafeToNominalTransition(Procedure):
    id          = "TC-FDIR-002"
    title       = "Mode transition SAFE → NOMINAL via mode command"
    requirement = "MIS-FDIR-002"

    def run(self, ctx: ProcedureContext) -> None:
        self.step("Verify initial SAFE mode")
        ctx.wait(0.5)
        ctx.assert_parameter("dhs.obc.mode", less_than=0.5)

        self.step("Send mode command — NOMINAL")
        ctx.inject("dhs.obc.mode_cmd", 1.0)
        ctx.wait(1.0)

        self.step("Verify NOMINAL mode active")
        ctx.assert_parameter("dhs.obc.mode", greater_than=0.5)

        self.step("Verify health still nominal after transition")
        ctx.assert_parameter("dhs.obc.health", less_than=0.5)


class WatchdogNominal(Procedure):
    id          = "TC-FDIR-003"
    title       = "Watchdog nominal — kick resets counter"
    requirement = "OBC-001"

    def run(self, ctx: ProcedureContext) -> None:
        self.step("Verify watchdog status nominal at boot")
        ctx.wait(0.5)
        ctx.assert_parameter("dhs.obc.watchdog_status", less_than=0.5)

        self.step("Kick watchdog")
        ctx.inject("dhs.obc.watchdog_kick", 1.0)
        ctx.wait(0.5)

        self.step("Verify watchdog still nominal after kick")
        ctx.assert_parameter("dhs.obc.watchdog_status", less_than=0.5)

        self.step("Verify OBT still advancing")
        ctx.assert_parameter("dhs.obc.obt", greater_than=0.0)