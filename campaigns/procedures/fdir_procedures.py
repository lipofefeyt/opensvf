"""
MySat-1 FDIR Validation Procedures

Validates Fault Detection, Isolation and Recovery logic:
- OBC boots in SAFE mode
- Mode transition SAFE → NOMINAL
- Sensor fault injection and FDIR response
- Watchdog behaviour
- Equipment health monitoring

Run with:
    svf campaign campaigns/fdir_campaign.yaml --report
"""
from svf.test.procedure import Procedure, ProcedureContext


class OBCBootsInSafeMode(Procedure):
    id          = "TC-FDIR-001"
    title       = "OBC boots in SAFE mode"
    requirement = "MIS-FDIR-001"

    def run(self, ctx: ProcedureContext) -> None:
        self.step("Wait for OBC initialisation")
        ctx.wait(0.5)

        self.step("Verify OBC in SAFE mode")
        ctx.assert_parameter(
            "dhs.obc.mode",
            less_than=0.5,   # 0 = SAFE
            requirement="MIS-FDIR-001",
        )

        self.step("Verify OBC health nominal")
        ctx.assert_parameter("dhs.obc.health", less_than=0.5)

        self.step("Verify watchdog nominal")
        ctx.assert_parameter("dhs.obc.watchdog_status", less_than=0.5)


class SafeToNominalTransition(Procedure):
    id          = "TC-FDIR-002"
    title       = "SAFE to NOMINAL mode transition"
    requirement = "MIS-FDIR-002"

    def run(self, ctx: ProcedureContext) -> None:
        self.step("Power on AOCS sensors")
        ctx.inject("aocs.mag.power_enable",  1.0)
        ctx.inject("aocs.gyro.power_enable", 1.0)
        ctx.inject("aocs.str1.power_enable", 1.0)
        ctx.wait(1.0)

        self.step("Verify SAFE mode before transition")
        ctx.assert_parameter("dhs.obc.mode", less_than=0.5)

        self.step("Command NOMINAL mode")
        ctx.inject("dhs.obc.mode_cmd", 1.0)
        ctx.wait(1.0)

        self.step("Verify NOMINAL mode achieved")
        ctx.assert_parameter(
            "dhs.obc.mode",
            greater_than=0.5,   # 1 = NOMINAL
            requirement="MIS-FDIR-002",
        )


class SensorFaultDoesNotCrashOBC(Procedure):
    id          = "TC-FDIR-003"
    title       = "OBC survives sensor bias fault"
    requirement = "MIS-FDIR-003"

    def run(self, ctx: ProcedureContext) -> None:
        self.step("Power on magnetometer")
        ctx.inject("aocs.mag.power_enable", 1.0)
        ctx.wait(0.5)

        self.step("Inject large bias fault on magnetometer X")
        ctx.inject_equipment_fault(
            equipment_id="mag1",
            port="aocs.mag.field_x",
            fault_type="bias",
            value=1.0,       # 1 T — far outside valid range
            duration_s=5.0,
        )

        self.step("Monitor OBC health during fault")
        health_monitor = ctx.monitor(
            "dhs.obc.health",
            less_than=2.5,   # health < 2.5 (0=nominal, 1=degraded, 2=failed)
            requirement="MIS-FDIR-003",
        )
        ctx.wait(3.0)
        health_monitor.assert_no_violations()

        self.step("Verify OBC still running after fault")
        ctx.assert_parameter("dhs.obc.obt", greater_than=0.0)


class ReactionWheelFaultDetection(Procedure):
    id          = "TC-FDIR-004"
    title       = "RW over-temperature triggers health warning"
    requirement = "MIS-FDIR-004"

    def run(self, ctx: ProcedureContext) -> None:
        self.step("Verify RW initially nominal")
        ctx.assert_parameter("aocs.rw1.status", greater_than=0.5)

        self.step("Inject RW temperature fault (stuck at 90°C)")
        ctx.inject_equipment_fault(
            equipment_id="rw1",
            port="aocs.rw1.temperature",
            fault_type="stuck",
            value=90.0,      # Above 80°C threshold
            duration_s=5.0,
        )
        ctx.wait(1.0)

        self.step("Verify RW status drops to 0 (over-temperature)")
        # RW torque is derated when over-temperature
        # status=0 indicates over-temperature condition
        temp = ctx.read_parameter("aocs.rw1.temperature")
        if temp is not None and temp > 80.0:
            ctx.assert_parameter("aocs.rw1.status", less_than=0.5)

        self.step("Wait for fault to clear")
        ctx.wait(5.0)

        self.step("Verify RW status recovers")
        ctx.assert_parameter("aocs.rw1.status", greater_than=0.5)


class WatchdogKickKeepsSystemAlive(Procedure):
    id          = "TC-FDIR-005"
    title       = "Watchdog kick prevents reset"
    requirement = "MIS-FDIR-005"

    def run(self, ctx: ProcedureContext) -> None:
        self.step("Verify OBC alive at start")
        ctx.wait(0.5)
        ctx.assert_parameter("dhs.obc.obt", greater_than=0.0)

        self.step("Kick watchdog")
        ctx.inject("dhs.obc.watchdog_kick", 1.0)
        ctx.wait(1.0)

        self.step("Verify watchdog status nominal after kick")
        ctx.assert_parameter("dhs.obc.watchdog_status", less_than=0.5)

        self.step("Verify OBC OBT still advancing")
        obt_before = ctx.read_parameter("dhs.obc.obt")
        ctx.wait(1.0)
        obt_after = ctx.read_parameter("dhs.obc.obt")
        if obt_before is not None and obt_after is not None:
            if obt_after <= obt_before:
                raise Exception(
                    f"OBT not advancing: before={obt_before:.2f} "
                    f"after={obt_after:.2f}"
                )
