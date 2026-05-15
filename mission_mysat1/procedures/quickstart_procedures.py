"""
MySat-1 quickstart validation procedures.

Four procedures that run without any compiled binaries (stub OBC mode, no FMU).
Each maps to a requirement in requirements.md.

Classes are prefixed P1_–P4_ so the campaign runner executes them in order.
Run with:
    svf campaign mission_mysat1/campaigns/quickstart_campaign.yaml --report
"""
from svf.campaign.procedure import Procedure, ProcedureContext


class P1_SensorPowerOn(Procedure):
    """MIS-AOCS-001: magnetometer and gyroscope reach status=1.0 within 5s."""

    id          = "TC-AOCS-001"
    title       = "AOCS sensor power-on verification"
    requirement = "MIS-AOCS-001"

    def run(self, ctx: ProcedureContext) -> None:
        self.step("Send power-enable to magnetometer and gyroscope")
        ctx.inject("aocs.mag1.power_enable",  1.0)
        ctx.inject("aocs.gyro1.power_enable", 1.0)

        self.step("Wait 2 s for sensor initialisation")
        ctx.wait(2.0)

        self.step("Verify magnetometer status nominal")
        ctx.assert_parameter("aocs.mag1.status", equals=1.0)

        self.step("Verify gyroscope status nominal")
        ctx.assert_parameter("aocs.gyro1.status", equals=1.0)


class P2_StarTrackerAcquisition(Procedure):
    """MIS-AOCS-002: star tracker acquires valid attitude within 15s."""

    id          = "TC-AOCS-002"
    title       = "Star tracker cold-start acquisition"
    requirement = "MIS-AOCS-002"

    def run(self, ctx: ProcedureContext) -> None:
        self.step("Power on star tracker — sun at 90° (outside 30° exclusion)")
        ctx.inject("aocs.str1.power_enable", 1.0)
        ctx.inject("aocs.str1.sun_angle",    90.0)

        self.step("Wait 12 s for acquisition (nominal: 10 s)")
        ctx.wait(12.0)

        self.step("Verify attitude valid")
        ctx.assert_parameter("aocs.str1.validity", equals=1.0)


class P3_ReactionWheelSpinUp(Procedure):
    """MIS-AOCS-003: reaction wheel reaches positive speed within 10s."""

    id          = "TC-AOCS-003"
    title       = "Reaction wheel spin-up under positive torque"
    requirement = "MIS-AOCS-003"

    def run(self, ctx: ProcedureContext) -> None:
        self.step("Command positive torque (0.05 Nm)")
        # 0.05 Nm / 0.001 kg·m² * (60/2π) ≈ 477 rpm/s², minus 5 rpm/s Coulomb
        # → net ~472 rpm/s → well above 100 rpm after 5 s
        ctx.inject("aocs.rw1.torque_cmd", 0.05)

        self.step("Wait 5 s for speed accumulation")
        ctx.wait(5.0)

        self.step("Verify wheel is spinning (> 100 rpm)")
        ctx.assert_parameter("aocs.rw1.speed", greater_than=100.0)


class P4_ReactionWheelThermalProtection(Procedure):
    """MIS-AOCS-004: RW status clears to 0.0 when temperature exceeds 80°C."""

    id          = "TC-FAULT-001"
    title       = "Reaction wheel thermal protection activation"
    requirement = "MIS-AOCS-004"

    def run(self, ctx: ProcedureContext) -> None:
        self.step("Verify reaction wheel in nominal state")
        ctx.wait(1.0)
        ctx.assert_parameter("aocs.rw1.status", equals=1.0)

        self.step("Inject over-temperature fault (stuck at 90°C, limit 80°C)")
        ctx.inject_equipment_fault(
            "rw1", "aocs.rw1.temperature",
            fault_type="stuck", value=90.0, duration_s=30.0,
        )

        self.step("Wait 2 s for thermal protection to activate")
        ctx.wait(2.0)

        self.step("Verify thermal protection de-asserted status flag")
        ctx.assert_parameter("aocs.rw1.status", equals=0.0)
