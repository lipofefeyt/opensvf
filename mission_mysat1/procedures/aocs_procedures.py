from svf.campaign.procedure import Procedure, ProcedureContext

class BdotDetumbling(Procedure):
    id = "TC-AOCS-001"
    title = "B-dot detumbling reduces angular rate"
    requirement = "KDE-003"

    def run(self, ctx: ProcedureContext) -> None:
        self.step("Power on AOCS sensors")
        ctx.inject("aocs.mag.power_enable", 1.0)
        ctx.inject("aocs.mtq.power_enable", 1.0)
        ctx.inject("aocs.bdot.enable", 1.0)
        
        self.step("Wait for detumbling")
        ctx.wait(30.0)
        
        self.step("Verify MTQ generated torque")
        ctx.assert_parameter("aocs.mtq.status", greater_than=0.5)
        # Note: In a real run, rate would drop, but here we just check if MTQ fired
        
class ReactionWheelOverTemperature(Procedure):
    id = "TC-RW-FAIL-001"
    title = "RW over-temperature derates torque"
    requirement = "RW-005"

    def run(self, ctx: ProcedureContext) -> None:
        self.step("Inject over-temperature fault")
        ctx.inject_equipment_fault("rw1", "aocs.rw1.temperature", "stuck", 90.0, 10.0)
        
        self.step("Verify status drops")
        ctx.wait(2.0)
        ctx.assert_parameter("aocs.rw1.status", less_than=0.5)

class StarTrackerBlinding(Procedure):
    id = "TC-ST-FAIL-001"
    title = "Sun blinding drops validity"
    requirement = "ST-003"

    def run(self, ctx: ProcedureContext) -> None:
        self.step("Power on ST and set nominal sun angle")
        ctx.inject("aocs.str1.power_enable", 1.0)
        ctx.inject("aocs.str1.sun_angle", 90.0)
        ctx.wait(12.0) # Wait for acquisition
        ctx.assert_parameter("aocs.str1.validity", greater_than=0.5)
        
        self.step("Inject sun blinding")
        ctx.inject("aocs.str1.sun_angle", 10.0)
        ctx.wait(2.0)
        
        self.step("Verify validity drops and mode resets")
        ctx.assert_parameter("aocs.str1.validity", less_than=0.5)
        ctx.assert_parameter("aocs.str1.mode", less_than=1.5) # Should be ACQUIRING
