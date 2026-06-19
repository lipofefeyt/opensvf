"""
MySat-1 Safe Mode Recovery Demo

Three self-contained procedures showing the FDIR chain:

  Act 1  -  Nominal ops: sensors powered, OBC healthy, ST acquired
  Act 2  -  Fault cascade: ST sun blinding + RW over-temperature detected
  Act 3  -  Ground recovery: mode command restores NOMINAL, health confirmed

Each procedure runs on a fresh simulation instance.

Run with:
    svf campaign mission_mysat1/campaigns/demo_campaign.yaml --report
"""
from __future__ import annotations

from svf.campaign.procedure import Procedure, ProcedureContext


class Act1_NominalOps(Procedure):
    """Nominal spacecraft operations  -  all sensors healthy."""

    id          = "TC-DEMO-001"
    title       = "Nominal ops  -  sensors powered, ST acquired, OBC healthy"
    requirement = "MIS-FDIR-001"

    def run(self, ctx: ProcedureContext) -> None:
        self.step("Power on AOCS sensors")
        ctx.inject("aocs.mag.power_enable",  1.0)
        ctx.inject("aocs.gyro.power_enable", 1.0)
        ctx.inject("aocs.str1.power_enable", 1.0)
        ctx.inject("aocs.str1.sun_angle",    90.0)
        ctx.wait(1.0)

        self.step("Verify OBC in SAFE mode at boot")
        ctx.assert_parameter("dhs.obc.mode", less_than=0.5)

        self.step("Verify OBT advancing")
        ctx.assert_parameter("dhs.obc.obt", greater_than=0.0)

        self.step("Kick watchdog")
        ctx.inject("dhs.obc.watchdog_kick", 1.0)
        ctx.wait(0.5)
        ctx.assert_parameter("dhs.obc.watchdog_status", less_than=0.5)

        self.step("Command NOMINAL mode")
        ctx.inject("dhs.obc.mode_cmd", 1.0)
        ctx.wait(1.0)
        ctx.assert_parameter("dhs.obc.mode", greater_than=0.5)

        self.step("Wait for star tracker acquisition (12s)")
        ctx.wait(13.0)
        ctx.assert_parameter("aocs.str1.validity", greater_than=0.5)

        self.step("Verify magnetometer nominal")
        ctx.assert_parameter("aocs.mag.status", greater_than=0.5)


class Act2_DualFaultCascade(Procedure):
    """Star tracker sun blinding + RW over-temperature detected simultaneously."""

    id          = "TC-DEMO-002"
    title       = "Dual fault cascade  -  ST blinded + RW over-temperature"
    requirement = "MIS-FDIR-003"

    def run(self, ctx: ProcedureContext) -> None:
        self.step("Setup  -  power sensors and acquire ST lock")
        ctx.inject("aocs.str1.power_enable", 1.0)
        ctx.inject("aocs.str1.sun_angle",    90.0)
        ctx.inject("aocs.mag.power_enable",  1.0)
        ctx.wait(14.0)
        ctx.assert_parameter("aocs.str1.validity", greater_than=0.5)

        self.step("FAULT 1  -  Star tracker sun blinding (10° inside exclusion zone)")
        ctx.inject("aocs.str1.sun_angle", 10.0)
        ctx.wait(2.0)
        ctx.assert_parameter("aocs.str1.validity", less_than=0.5)
        ctx.assert_parameter("aocs.str1.mode",     less_than=1.5)  # ACQUIRING

        self.step("FAULT 2  -  Reaction wheel over-temperature fault (90°C, threshold 80°C)")
        ctx.inject_equipment_fault(
            equipment_id="rw1",
            port="aocs.rw1.temperature",
            fault_type="stuck",
            value=90.0,
            duration_s=10.0,
        )
        ctx.wait(1.0)
        ctx.assert_parameter("aocs.rw1.temperature", greater_than=80.0)
        ctx.assert_parameter("aocs.rw1.status",      less_than=0.5)

        self.step("Monitor angular rate bounded during fault (b-dot active)")
        rate_monitor = ctx.monitor(
            "aocs.truth.rate_x",
            less_than=5.0,
        )
        ctx.wait(5.0)
        rate_monitor.assert_no_violations()

        self.step("Verify magnetometer still nominal  -  single-point fault isolation")
        ctx.assert_parameter("aocs.mag.status", greater_than=0.5)


class Act3_GroundRecovery(Procedure):
    """Ground uplinks mode recovery command after clearing fault conditions."""

    id          = "TC-DEMO-003"
    title       = "Ground recovery  -  clear faults, command NOMINAL, verify health"
    requirement = "MIS-FDIR-002"

    def run(self, ctx: ProcedureContext) -> None:
        self.step("Setup  -  start in SAFE mode (boot state)")
        ctx.inject("aocs.str1.power_enable", 1.0)
        ctx.inject("aocs.str1.sun_angle",    10.0)  # Fault condition active
        ctx.wait(1.0)
        ctx.assert_parameter("dhs.obc.mode", less_than=0.5)  # SAFE

        self.step("Ground station: clear star tracker fault condition")
        ctx.inject("aocs.str1.sun_angle", 90.0)   # Rotate away from sun
        ctx.wait(14.0)                             # Wait for re-acquisition
        ctx.assert_parameter("aocs.str1.validity", greater_than=0.5)

        self.step("Ground uplinks mode recovery command  -  TC(8,1) recover_nominal")
        ctx.inject("dhs.obc.mode_cmd", 1.0)
        ctx.inject("dhs.obc.watchdog_kick", 1.0)
        ctx.wait(2.0)

        self.step("Verify OBSW transitioned to NOMINAL mode")
        ctx.assert_parameter("dhs.obc.mode", greater_than=0.5)

        self.step("Final health check  -  spacecraft fully recovered")
        ctx.assert_parameter("dhs.obc.watchdog_status", less_than=0.5)
        ctx.assert_parameter("aocs.str1.validity",      greater_than=0.5)
        ctx.assert_parameter("dhs.obc.obt",             greater_than=0.0)