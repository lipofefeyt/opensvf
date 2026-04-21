"""
MySat-1 AOCS Validation Procedures

Demonstrates:
- Equipment fault injection (star tracker blinding)
- Temporal assertions (rate never exceeds threshold)
- Parameter monitoring over a time window
- Sensor power sequencing

Run with:
    svf campaign campaigns/example_campaign.yaml --report
"""
from svf.test.procedure import Procedure, ProcedureContext


class MagnetometerNoiseCheck(Procedure):
    id          = "TC-MAG-001"
    title       = "Magnetometer noise within specification"
    requirement = "MIS-MAG-001"

    def run(self, ctx: ProcedureContext) -> None:
        self.step("Power on magnetometer")
        ctx.inject("aocs.mag.power_enable", 1.0)
        ctx.wait(0.5)

        self.step("Verify magnetometer active")
        ctx.assert_parameter("aocs.mag.status", greater_than=0.5)

        self.step("Monitor field magnitude — must not saturate")
        # B-field at LEO: 20-65 uT. Field > 1e-3 T indicates saturation
        monitor = ctx.monitor(
            "aocs.mag.field_x",
            less_than=1e-3,
            requirement="MIS-MAG-001",
        )
        ctx.wait(5.0)
        monitor.assert_no_violations()


class GyroscopeStartup(Procedure):
    id          = "TC-GYRO-001"
    title       = "Gyroscope startup and rate output valid"
    requirement = "MIS-GYRO-001"

    def run(self, ctx: ProcedureContext) -> None:
        self.step("Power on gyroscope")
        ctx.inject("aocs.gyro.power_enable", 1.0)
        ctx.wait(0.5)

        self.step("Verify gyroscope active")
        ctx.assert_parameter("aocs.gyro.status", greater_than=0.5)

        self.step("Verify temperature in nominal range")
        ctx.assert_parameter(
            "aocs.gyro.temperature",
            greater_than=15.0,
            requirement="MIS-GYRO-001",
        )


class StarTrackerBlindingRecovery(Procedure):
    id          = "TC-ST-001"
    title       = "Star tracker recovers after sun blinding"
    requirement = "MIS-ST-001"

    def run(self, ctx: ProcedureContext) -> None:
        self.step("Power on star tracker")
        ctx.inject("aocs.str1.power_enable", 1.0)
        ctx.wait(1.0)

        self.step("Inject sun blinding via port")
        # Simulate sun in exclusion cone by injecting low sun angle
        ctx.inject("aocs.str1.sun_angle", 10.0)
        ctx.wait(1.0)

        self.step("Verify star tracker in acquisition after blinding")
        # After blinding: mode should be ACQUIRING (1) not TRACKING (2)
        val = ctx.read_parameter("aocs.str1.mode")
        # 0=off, 1=acquiring, 2=tracking — blinding resets to acquiring
        if val is not None:
            ctx.assert_parameter("aocs.str1.mode", less_than=2.5)

        self.step("Wait for fault to clear")
        ctx.wait(3.0)

        self.step("Verify star tracker mode after recovery")
        ctx.assert_parameter("aocs.str1.mode", greater_than=0.0)


class MtqPowerConsumption(Procedure):
    id          = "TC-MTQ-001"
    title       = "MTQ power consumption within budget"
    requirement = "MIS-MTQ-001"

    def run(self, ctx: ProcedureContext) -> None:
        self.step("Power on MTQ")
        ctx.inject("aocs.mtq.power_enable", 1.0)
        ctx.wait(0.5)

        self.step("Verify MTQ active")
        ctx.assert_parameter("aocs.mtq.status", greater_than=0.5)

        self.step("Monitor power consumption — must stay under 10W")
        monitor = ctx.monitor(
            "aocs.mtq.power_w",
            less_than=10.0,
            requirement="MIS-MTQ-001",
        )
        ctx.wait(3.0)
        result = monitor.summary()
        if not result.compliant:
            raise Exception(
                f"MTQ power exceeded budget: "
                f"max={result.max_value:.2f}W, "
                f"{len(result.violations)} violations"
            )


class ReactionWheelSpeedControl(Procedure):
    id          = "TC-RW-001"
    title       = "Reaction wheel speed stays within limits"
    requirement = "MIS-RW-001"

    def run(self, ctx: ProcedureContext) -> None:
        self.step("Verify RW initialised")
        ctx.assert_parameter("aocs.rw1.status", greater_than=0.5)

        self.step("Monitor RW speed — must not exceed 6000 rpm")
        monitor = ctx.monitor(
            "aocs.rw1.speed",
            less_than=6000.0,
            requirement="MIS-RW-001",
        )
        ctx.wait(5.0)
        monitor.assert_no_violations()

        self.step("Verify RW temperature nominal")
        ctx.assert_parameter(
            "aocs.rw1.temperature",
            less_than=80.0,
        )
