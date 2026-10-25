"""
MySat-1 EPS validation procedures.

Bus load is set through the PCDU's eight LCLs (5 W each, all on at boot),
so "nominal load" here means six LCLs on (30 W). Requires the EPS models in
mission_mysat1/spacecraft.yaml (solar_array, battery, pcdu).

Run with:
    svf campaign mission_mysat1/campaigns/eps_campaign.yaml --report
"""
from svf.campaign.procedure import Procedure, ProcedureContext

_N_LCLS = 8


def _set_load(ctx: ProcedureContext, lcls_on: int) -> None:
    """Switch the first `lcls_on` LCLs on and the rest off (5 W per LCL)."""
    for i in range(1, _N_LCLS + 1):
        ctx.inject(f"eps.pcdu.lcl{i}.enable", 1.0 if i <= lcls_on else 0.0)


def _soc(ctx: ProcedureContext) -> float:
    value = ctx.read_parameter("eps.battery.soc")
    assert value is not None, "eps.battery.soc not published"
    return value


class P1_BatteryChargesInSunlight(Procedure):
    id = "TC-PWR-001"
    title = "Battery charges in sunlight"
    requirement = "MIS-EPS-001"

    def run(self, ctx: ProcedureContext) -> None:
        self.step("Full sun, 20 W load (well below array output)")
        ctx.inject("eps.solar_array.illumination", 1.0)
        _set_load(ctx, 4)
        ctx.wait(5.0)
        soc_start = _soc(ctx)

        self.step("Charge for 60 s")
        ctx.wait(60.0)

        self.step("Verify positive charge current and rising SoC")
        ctx.assert_parameter("eps.pcdu.charge_current", greater_than=0.0)
        soc_end = _soc(ctx)
        assert soc_end > soc_start, (
            f"SoC did not increase: {soc_start:.4f} -> {soc_end:.4f}"
        )


class P2_BatteryDischargesInEclipse(Procedure):
    id = "TC-PWR-002"
    title = "Battery discharges monotonically in eclipse"
    requirement = "MIS-EPS-002"

    def run(self, ctx: ProcedureContext) -> None:
        self.step("Full eclipse, nominal 30 W load")
        ctx.inject("eps.solar_array.illumination", 0.0)
        _set_load(ctx, 6)
        ctx.wait(5.0)

        self.step("Sample SoC every 10 s for 60 s")
        samples = [_soc(ctx)]
        for _ in range(6):
            ctx.wait(10.0)
            samples.append(_soc(ctx))

        self.step("Verify negative charge current and strictly falling SoC")
        ctx.assert_parameter("eps.pcdu.charge_current", less_than=0.0)
        for before, after in zip(samples, samples[1:]):
            assert after < before, f"SoC not decreasing: {samples}"


class P3_BusVoltageInDeepEclipse(Procedure):
    id = "TC-PWR-005"
    title = "Bus voltage holds through deep eclipse"
    requirement = "MIS-EPS-003"

    def run(self, ctx: ProcedureContext) -> None:
        self.step("Full eclipse, nominal 30 W load")
        ctx.inject("eps.solar_array.illumination", 0.0)
        _set_load(ctx, 6)
        ctx.wait(1.0)

        self.step("Monitor bus voltage > 3.0 V for 120 s")
        monitor = ctx.monitor("eps.bus.voltage", greater_than=3.0)
        ctx.wait(120.0)
        monitor.assert_no_violations()
        ctx.assert_parameter("eps.pcdu.uvlo_active", less_than=0.5)
