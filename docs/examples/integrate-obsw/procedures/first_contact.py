from svf.campaign.procedure import Procedure, ProcedureContext

MODE_NOMINAL = 2.0  # housekeeping mode encoding: 0 STANDBY, 1 SAFE, 2 NOMINAL


class FirstContact(Procedure):
    id = "TC-INT-001"
    title = "The OBSW answers a ping and reports its mode"
    requirement = "INT-001"

    def run(self, ctx: ProcedureContext) -> None:
        self.step("Ping: TC(17,1) is answered by TM(17,2)")
        ctx.tc(17, 1)
        ctx.expect_tm(17, 2, timeout=10.0)

        self.step("Housekeeping arrives: TM(3,25)")
        ctx.expect_tm(3, 25, timeout=10.0)

        self.step("Command NOMINAL and read it back from housekeeping")
        ctx.ensure_nominal(timeout=10.0)
        ctx.assert_parameter("dhs.obc.mode", equals=MODE_NOMINAL)
