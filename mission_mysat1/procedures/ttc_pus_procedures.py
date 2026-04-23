from svf.campaign.procedure import Procedure, ProcedureContext

class ContactPassNominal(Procedure):
    id = "TC-CONT-001"
    title = "Ground contact pass nominal acquisition"
    requirement = "SBT-001"

    def run(self, ctx: ProcedureContext) -> None:
        self.step("Power on SBT and simulate ground station rise")
        ctx.inject("ttc.sbt.power_enable", 1.0)
        ctx.inject("ttc.sbt.uplink_signal_level", -90.0) # Strong signal
        
        self.step("Wait for carrier lock")
        ctx.wait(4.0)
        ctx.assert_parameter("ttc.sbt.uplink_lock", greater_than=0.5)

class PusAreYouAlive(Procedure):
    id = "TC-PUS-001"
    title = "S17 Are-You-Alive Roundtrip"
    requirement = "PUS-007"

    def run(self, ctx: ProcedureContext) -> None:
        self.step("Send TC(17,1)")
        ctx.tc(service=17, subservice=1)
        
        self.step("Expect TM(17,2) response")
        ctx.expect_tm(service=17, subservice=2, timeout=5.0)

class SbtLossOfSignal(Procedure):
    id = "TC-SBT-FAIL-001"
    title = "Carrier lock lost when signal drops"
    requirement = "SBT-003"

    def run(self, ctx: ProcedureContext) -> None:
        self.step("Acquire Lock")
        ctx.inject("ttc.sbt.power_enable", 1.0)
        ctx.inject("ttc.sbt.uplink_signal_level", -90.0)
        ctx.wait(4.0)
        ctx.assert_parameter("ttc.sbt.uplink_lock", greater_than=0.5)
        
        self.step("Simulate Loss of Signal (LOS)")
        ctx.inject("ttc.sbt.uplink_signal_level", -130.0)
        ctx.wait(2.0)
        
        self.step("Verify lock lost")
        ctx.assert_parameter("ttc.sbt.uplink_lock", less_than=0.5)
