from svf.campaign.procedure import Procedure, ProcedureContext

class BatteryChargesInSunlight(Procedure):
    id = "TC-PWR-001"
    title = "Battery charges in sunlight"
    requirement = "EPS-011"

    def run(self, ctx: ProcedureContext) -> None:
        self.step("Inject sunlight and nominal load")
        ctx.inject("eps.solar_array.illumination", 1.0)
        ctx.inject("eps.load.power", 30.0)
        
        self.step("Wait for charge accumulation")
        ctx.wait(60.0)
        
        self.step("Verify SoC and charge current")
        ctx.assert_parameter("eps.battery.charge_current", greater_than=0.0)
        ctx.assert_parameter("eps.battery.soc", greater_than=0.85)

class BatteryDischargesInEclipse(Procedure):
    id = "TC-PWR-002"
    title = "Battery discharges in eclipse"
    requirement = "EPS-012"

    def run(self, ctx: ProcedureContext) -> None:
        self.step("Inject eclipse and nominal load")
        ctx.inject("eps.solar_array.illumination", 0.0)
        ctx.inject("eps.load.power", 30.0)
        
        self.step("Wait for discharge")
        ctx.wait(60.0)
        
        self.step("Verify SoC dropped")
        ctx.assert_parameter("eps.battery.charge_current", less_than=0.0)
        ctx.assert_parameter("eps.battery.soc", less_than=0.8)

class DeepEclipseDischarge(Procedure):
    id = "TC-PWR-005"
    title = "Deep eclipse discharge behavior"
    requirement = "EPS-013"

    def run(self, ctx: ProcedureContext) -> None:
        self.step("Inject eclipse and heavy load")
        ctx.inject("eps.solar_array.illumination", 0.0)
        ctx.inject("eps.load.power", 50.0)
        
        self.step("Wait for deep discharge")
        ctx.wait(120.0)
        
        self.step("Verify bus voltage stays above cutoff")
        ctx.assert_parameter("eps.bus.voltage", greater_than=3.0)
