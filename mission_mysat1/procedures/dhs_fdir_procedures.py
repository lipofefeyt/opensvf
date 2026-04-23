from svf.campaign.procedure import Procedure, ProcedureContext

class WatchdogResetToSafeMode(Procedure):
    id = "TC-OBC-FAIL-001"
    title = "Watchdog reset forces SAFE mode"
    requirement = "OBC-005"

    def run(self, ctx: ProcedureContext) -> None:
        self.step("Ensure OBC starts")
        ctx.wait(2.0)
        
        self.step("Wait for watchdog timeout (no kicks)")
        ctx.wait(25.0) # Assume 20s watchdog period
        
        self.step("Verify reset to SAFE mode")
        ctx.assert_parameter("dhs.obc.watchdog_status", equals=2.0) # WDG_RESET
        ctx.assert_parameter("dhs.obc.mode", equals=0.0) # MODE_SAFE

class Mil1553BusErrorSwitchover(Procedure):
    id = "TC-1553-FAIL-003"
    title = "BUS_ERROR triggers switchover"
    requirement = "1553-006"

    def run(self, ctx: ProcedureContext) -> None:
        self.step("Inject BUS_ERROR fault")
        ctx.inject_equipment_fault("aocs_bus", "bus.platform_1553.fault.all.bus_error", "stuck", 0.0, 5.0)
        
        self.step("Verify switchover to Bus B")
        ctx.wait(2.0)
        ctx.assert_parameter("bus.platform_1553.active_bus", equals=2.0)

class RwFaultTriggersSafeMode(Procedure):
    id = "TC-FDIR-001"
    title = "RW NO_RESPONSE triggers SAFE mode via Stub"
    requirement = "SVF-DEV-051"

    def run(self, ctx: ProcedureContext) -> None:
        self.step("Inject RW NO_RESPONSE fault")
        ctx.inject_equipment_fault("aocs_bus", "bus.platform_1553.fault.rt5.no_response", "stuck", 0.0, 10.0)
        
        self.step("Wait for Stub FDIR to react")
        ctx.wait(5.0)
        
        self.step("Verify fallback to SAFE mode")
        ctx.assert_parameter("dhs.obc.mode", equals=0.0)
