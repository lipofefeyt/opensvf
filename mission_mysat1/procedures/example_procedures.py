"""
Example SVF test procedures for MySat-1.
Run with: svf campaign campaigns/example_campaign.yaml --report
"""
from svf.test.procedure import Procedure, ProcedureContext


class SensorPowerOn(Procedure):
    id          = "TC-SENS-001"
    title       = "Power on AOCS sensors"
    requirement = "MIS-SENS-001"

    def run(self, ctx: ProcedureContext) -> None:
        self.step("Power on magnetometer")
        ctx.inject("aocs.mag.power_enable", 1.0)

        self.step("Power on gyroscope")
        ctx.inject("aocs.gyro.power_enable", 1.0)

        self.step("Wait for sensor startup")
        ctx.wait(1.0)

        self.step("Verify magnetometer active")
        ctx.assert_parameter("aocs.mag.status", greater_than=0.5)

        self.step("Verify gyroscope active")
        ctx.assert_parameter("aocs.gyro.status", greater_than=0.5)


class MagnetometerSanity(Procedure):
    id          = "TC-MAG-001"
    title       = "Magnetometer output sanity check"
    requirement = "MIS-MAG-001"

    def run(self, ctx: ProcedureContext) -> None:
        self.step("Power on magnetometer")
        ctx.inject("aocs.mag.power_enable", 1.0)
        ctx.wait(0.5)

        self.step("Check field magnitude in range")
        # B-field at LEO: ~20-65 uT
        monitor = ctx.monitor(
            "aocs.mag.status", greater_than=0.5
        )
        ctx.wait(2.0)
        monitor.assert_no_violations()
