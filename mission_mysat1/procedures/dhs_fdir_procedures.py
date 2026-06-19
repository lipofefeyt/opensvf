"""
MySat-1 DHS & FDIR Validation Procedures

Validates OBC stub behaviour:
  - Boot state (SAFE mode)
  - Mode transitions (SAFE ↔ NOMINAL)
  - Watchdog nominal operation
  - OBC telemetry output (OBT, health, CPU load)
  - FDIR chain: RW stall detected by stub rule → SAFE + S5 event → recovery

Requirements covered: MIS-FDIR-001, MIS-FDIR-002, MIS-FDIR-003, OBC-001
"""
from __future__ import annotations

from svf.campaign.procedure import Procedure, ProcedureContext
from svf.models.dhs.obc import MODE_SAFE
from svf.models.dhs.obc_stub import ObcStub, Rule
from svf.stores.command_store import CommandStore


class OBCBootsInSafeMode(Procedure):
    id          = "TC-FDIR-001"
    title       = "OBC boots in SAFE mode"
    requirement = "MIS-FDIR-001"

    def run(self, ctx: ProcedureContext) -> None:
        self.step("Wait for OBC initialisation")
        ctx.wait(0.5)

        self.step("Verify OBC in SAFE mode at boot")
        ctx.assert_parameter("dhs.obc.mode", less_than=0.5)

        self.step("Verify OBT advancing")
        ctx.assert_parameter("dhs.obc.obt", greater_than=0.0)

        self.step("Verify health nominal at boot")
        ctx.assert_parameter("dhs.obc.health", less_than=0.5)


class SafeToNominalTransition(Procedure):
    id          = "TC-FDIR-002"
    title       = "Mode transition SAFE → NOMINAL via mode command"
    requirement = "MIS-FDIR-002"

    def run(self, ctx: ProcedureContext) -> None:
        self.step("Verify initial SAFE mode")
        ctx.wait(0.5)
        ctx.assert_parameter("dhs.obc.mode", less_than=0.5)

        self.step("Send mode command  -  NOMINAL")
        ctx.inject("dhs.obc.mode_cmd", 1.0)
        ctx.wait(1.0)

        self.step("Verify NOMINAL mode active")
        ctx.assert_parameter("dhs.obc.mode", greater_than=0.5)

        self.step("Verify health still nominal after transition")
        ctx.assert_parameter("dhs.obc.health", less_than=0.5)


class WatchdogNominal(Procedure):
    id          = "TC-FDIR-003"
    title       = "Watchdog nominal  -  kick resets counter"
    requirement = "OBC-001"

    def run(self, ctx: ProcedureContext) -> None:
        self.step("Verify watchdog status nominal at boot")
        ctx.wait(0.5)
        ctx.assert_parameter("dhs.obc.watchdog_status", less_than=0.5)

        self.step("Kick watchdog")
        ctx.inject("dhs.obc.watchdog_kick", 1.0)
        ctx.wait(0.5)

        self.step("Verify watchdog still nominal after kick")
        ctx.assert_parameter("dhs.obc.watchdog_status", less_than=0.5)

        self.step("Verify OBT still advancing")
        ctx.assert_parameter("dhs.obc.obt", greater_than=0.0)


class FdirChain(Procedure):
    """RW stall fault detected by OBC stub rule triggers SAFE mode + S5 event."""

    id          = "TC-FDIR-004"
    title       = "FDIR chain  -  RW stall triggers SAFE via OBC stub rule"
    requirement = "MIS-FDIR-003"

    def run(self, ctx: ProcedureContext) -> None:
        self.step("Transition to NOMINAL mode")
        ctx.inject("dhs.obc.mode_cmd", 1.0)
        ctx.wait(1.0)
        ctx.assert_parameter("dhs.obc.mode", greater_than=0.5)

        self.step("Spin up reaction wheel")
        ctx.inject("aocs.rw1.torque_cmd", 0.05)
        ctx.wait(5.0)
        ctx.assert_parameter("aocs.rw1.speed", greater_than=100.0)

        self.step("Arm OBC stub FDIR rule  -  RW stall detection")
        if ctx._master is not None:
            for model in ctx._master._models:
                if isinstance(model, ObcStub):
                    def _stall_action(cs: CommandStore, t: float) -> None:
                        cs.inject("dhs.obc.mode_cmd", float(MODE_SAFE), t=t,
                                  source_id="stub.fdir")
                    model.add_rule(Rule(
                        name="rw_stall_fdir",
                        watch="aocs.rw1.speed",
                        condition=lambda e: e is not None and e.value < 10.0,
                        action=_stall_action,
                        once=True,
                    ))
                    break

        self.step("Inject RW speed freeze fault")
        ctx.inject_equipment_fault(
            "rw1", "aocs.rw1.speed", fault_type="stuck", value=0.0, duration_s=30.0,
        )

        self.step("Verify OBC stub detects stall and transitions to SAFE")
        ctx.wait_until(
            lambda s: (e := s.read("dhs.obc.mode")) is not None and e.value < 0.5,
            timeout=10.0,
        )
        ctx.assert_parameter("dhs.obc.mode", less_than=0.5)

        self.step("Verify S5 anomaly event was generated on SAFE transition")
        ctx.assert_parameter("svf.tm.5.1.received", greater_than=0.0)

        self.step("Clear fault and recover to NOMINAL")
        ctx.clear_equipment_faults("rw1")
        ctx.inject("dhs.obc.mode_cmd", 1.0)
        ctx.wait(1.0)
        ctx.assert_parameter("dhs.obc.mode", greater_than=0.5)