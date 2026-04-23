from svf.campaign.procedure import Procedure, ProcedureContext
import struct

def configure_obc(ctx: ProcedureContext):
    """Ensure the OBC Stub knows about the PUS parameter mapping."""
    if ctx._master is None: return
    obc = next((m for m in ctx._master._models if m.model_id == "obc"), None)
    if obc is not None:
        # Map the parameters so TC(20,1) works
        obc._config.param_id_map.update({
            0x2021: "aocs.rw1.torque_cmd",
            0x2022: "aocs.rw1.speed",
            0x4002: "dhs.obc.mode_cmd"
        })

class SafeModeRecovery(Procedure):
    id = "TC-SMR-001"
    title = "Safe mode recovery closed-loop scenario"
    requirement = "SVF-DEV-050"

    def run(self, ctx: ProcedureContext) -> None:
        configure_obc(ctx)
        
        self.step("Ensure system starts in SAFE mode")
        ctx.assert_parameter("dhs.obc.mode", equals=0.0) # 0 = SAFE
        
        self.step("Wait for Star Tracker Acquisition")
        ctx.inject("aocs.str1.power_enable", 1.0)
        ctx.wait_until(lambda s: s.read("aocs.str1.validity") is not None and s.read("aocs.str1.validity").value == 1.0, timeout=15.0)
        
        self.step("Command transition to NOMINAL via PUS S20")
        ctx.tc(service=20, subservice=1, data=struct.pack(">Hf", 0x4002, 1.0))
        
        self.step("Verify transition to NOMINAL")
        ctx.wait_until(lambda s: s.read("dhs.obc.mode") is not None and s.read("dhs.obc.mode").value == 1.0, timeout=10.0)
        ctx.assert_parameter("dhs.obc.mode", equals=1.0) 

class NominalOperationsLoop(Procedure):
    id = "TC-NOM-001"
    title = "Nominal operations loop"
    requirement = "SVF-DEV-051"

    def run(self, ctx: ProcedureContext) -> None:
        configure_obc(ctx)
        
        self.step("Set Invariants")
        # Ensure that during this whole test, the battery never drops below 3.0V
        ctx.expect_always("eps.battery.voltage", greater_than=10.0)
        
        self.step("Send S17 Are-You-Alive Ping")
        ctx.tc(service=17, subservice=1)
        ctx.expect_tm(service=17, subservice=2, timeout=5.0)

        self.step("Send S20 Parameter Set to RW")
        ctx.tc(service=20, subservice=1, data=struct.pack(">Hf", 0x2021, 0.1))
        
        self.step("Verify RW speed changes via 1553 Bus")
        ctx.wait_until(lambda s: s.read("aocs.rw1.speed") is not None and s.read("aocs.rw1.speed").value > 10.0, timeout=10.0)
        ctx.assert_parameter("aocs.rw1.speed", greater_than=10.0)
