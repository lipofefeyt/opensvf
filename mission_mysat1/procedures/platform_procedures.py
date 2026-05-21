"""
MySat-1 full platform validation procedures.

Two closed-loop scenarios covering SVF-DEV-050 and SVF-DEV-051:
  - SafeModeRecovery:     ST acquisition → PUS S20 mode transition → NOMINAL
  - NominalOperationsLoop: S17 ping, S20 parameter set, RW speed verification

Run with:
    svf campaign mission_mysat1/campaigns/platform_campaign.yaml --report
"""
from __future__ import annotations

import struct

from svf.campaign.procedure import Procedure, ProcedureContext
from svf.models.dhs.obc import ObcEquipment


def _configure_obc(ctx: ProcedureContext) -> None:
    """Patch param_id_map so TC(20,1) can address equipment parameters."""
    if ctx._master is None:
        return
    for model in ctx._master._models:
        if isinstance(model, ObcEquipment) and model.model_id == "obc":
            model._config.param_id_map.update({
                0x2021: "aocs.rw1.torque_cmd",
                0x2022: "aocs.rw1.speed",
                0x4002: "dhs.obc.mode_cmd",
            })
            return


class SafeModeRecovery(Procedure):
    """OBC starts in SAFE, ST acquires attitude, S20 commands NOMINAL."""

    id          = "TC-SMR-001"
    title       = "Safe mode recovery closed-loop scenario"
    requirement = "SVF-DEV-050"

    def run(self, ctx: ProcedureContext) -> None:
        _configure_obc(ctx)

        self.step("Verify OBC boots in SAFE mode")
        ctx.wait(0.5)
        ctx.assert_parameter("dhs.obc.mode", equals=0.0)

        self.step("Power on ST and wait for attitude acquisition")
        ctx.inject("aocs.str1.power_enable", 1.0)
        ctx.inject("aocs.str1.sun_angle", 90.0)  # outside 30° exclusion zone
        ctx.wait_until(
            lambda s: (e := s.read("aocs.str1.validity")) is not None and e.value == 1.0,
            timeout=15.0,
        )

        self.step("Command transition to NOMINAL via PUS TC(20,1)")
        ctx.tc(service=20, subservice=1, data=struct.pack(">Hf", 0x4002, 1.0))

        self.step("Verify OBC transitions to NOMINAL")
        ctx.wait_until(
            lambda s: (e := s.read("dhs.obc.mode")) is not None and e.value == 1.0,
            timeout=10.0,
        )
        ctx.assert_parameter("dhs.obc.mode", equals=1.0)


class NominalOperationsLoop(Procedure):
    """S17 roundtrip, S20 parameter set, RW spin-up verification."""

    id          = "TC-NOM-001"
    title       = "Nominal operations loop"
    requirement = "SVF-DEV-051"

    def run(self, ctx: ProcedureContext) -> None:
        _configure_obc(ctx)

        self.step("Send S17 Are-You-Alive ping and verify TM(17,2) response")
        ctx.tc(service=17, subservice=1)
        ctx.expect_tm(service=17, subservice=2, timeout=5.0)

        self.step("Send S20 parameter set — command RW torque 0.1 Nm")
        ctx.tc(service=20, subservice=1, data=struct.pack(">Hf", 0x2021, 0.1))

        self.step("Verify RW spins up following torque command")
        ctx.wait_until(
            lambda s: (e := s.read("aocs.rw1.speed")) is not None and e.value > 10.0,
            timeout=10.0,
        )
        ctx.assert_parameter("aocs.rw1.speed", greater_than=10.0)
