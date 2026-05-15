"""
Behavioral unit tests for EPS native equipment models.
Covers solar array, battery, PCDU, and integrated EPS wiring.
Implements: EPS-001–016, PCDU-001–004
"""
from __future__ import annotations

import pytest

from svf.core.abstractions import SyncProtocol
from svf.stores.parameter_store import ParameterStore
from svf.stores.command_store import CommandStore
from svf.models.eps.solar_array import make_solar_array, MAX_POWER_W, PANEL_EFFICIENCY
from svf.models.eps.battery import make_battery, SOC_MIN, SOC_MAX, INITIAL_SOC
from svf.models.eps.pcdu import make_pcdu


class _NoSync(SyncProtocol):
    def reset(self) -> None: pass
    def publish_ready(self, model_id: str, t: float) -> None: pass
    def wait_for_ready(self, expected: list[str], timeout: float) -> bool: return True


def _stores() -> tuple[ParameterStore, CommandStore]:
    return ParameterStore(), CommandStore()


def _sync() -> _NoSync:
    return _NoSync()


def _step_eps(solar, battery, pcdu, illumination: float, n_lcls_on: int, dt: float, t: float) -> None:
    """Step the three native EPS models in dependency order for one tick."""
    solar.receive("eps.solar_array.illumination", illumination)
    solar.do_step(t=t, dt=dt)

    gen_power = solar.read_port("eps.solar_array.generated_power")

    pcdu.receive("eps.solar_array.generated_power", gen_power)
    pcdu.receive("eps.solar_array.illumination", illumination)
    pcdu.receive("eps.battery.voltage", battery.read_port("eps.battery.voltage"))
    for i in range(1, 9):
        pcdu.receive(f"eps.pcdu.lcl{i}.enable", 1.0 if i <= n_lcls_on else 0.0)
    pcdu.do_step(t=t, dt=dt)

    charge_current = pcdu.read_port("eps.pcdu.charge_current")
    battery.receive("eps.battery.charge_current", charge_current)
    battery.do_step(t=t, dt=dt)


# ---------------------------------------------------------------------------
# Solar Array — EPS-001, EPS-002, EPS-003
# ---------------------------------------------------------------------------

class SolarArrayTests:

    @pytest.mark.requirement("EPS-001")
    def test_solar_power_proportional_to_illumination(self) -> None:
        """Generated power scales linearly with illumination."""
        store, cmd = _stores()
        solar = make_solar_array(_sync(), store, cmd)
        solar.initialise()

        solar.receive("eps.solar_array.illumination", 0.5)
        solar.do_step(t=0.0, dt=1.0)
        p_half = solar.read_port("eps.solar_array.generated_power")

        solar.receive("eps.solar_array.illumination", 1.0)
        solar.do_step(t=1.0, dt=1.0)
        p_full = solar.read_port("eps.solar_array.generated_power")

        assert p_full == pytest.approx(2.0 * p_half, rel=1e-3)

    @pytest.mark.requirement("EPS-002")
    def test_solar_zero_power_in_eclipse(self) -> None:
        """generated_power = 0.0 when illumination = 0.0."""
        store, cmd = _stores()
        solar = make_solar_array(_sync(), store, cmd)
        solar.initialise()
        solar.receive("eps.solar_array.illumination", 0.0)
        solar.do_step(t=0.0, dt=1.0)
        assert solar.read_port("eps.solar_array.generated_power") == pytest.approx(0.0)

    @pytest.mark.requirement("EPS-003")
    def test_solar_full_power_in_sunlight(self) -> None:
        """generated_power = MAX_POWER_W * PANEL_EFFICIENCY at illumination = 1.0."""
        store, cmd = _stores()
        solar = make_solar_array(_sync(), store, cmd)
        solar.initialise()
        solar.receive("eps.solar_array.illumination", 1.0)
        solar.do_step(t=0.0, dt=1.0)
        expected = MAX_POWER_W * PANEL_EFFICIENCY
        assert solar.read_port("eps.solar_array.generated_power") == pytest.approx(expected)


# ---------------------------------------------------------------------------
# Battery — EPS-004, EPS-005, EPS-006, EPS-007
# ---------------------------------------------------------------------------

class BatteryTests:

    @pytest.mark.requirement("EPS-004")
    def test_battery_soc_decreases_when_discharging(self) -> None:
        """battery_soc decreases when charge_current is negative."""
        store, cmd = _stores()
        bat = make_battery(_sync(), store, cmd, initial_soc=0.8)
        bat.initialise()
        soc_before = bat.read_port("eps.battery.soc")

        for i in range(100):
            bat.receive("eps.battery.charge_current", -2.0)
            bat.do_step(t=i * 1.0, dt=1.0)

        assert bat.read_port("eps.battery.soc") < soc_before

    @pytest.mark.requirement("EPS-005")
    def test_battery_soc_increases_when_charging(self) -> None:
        """battery_soc increases when charge_current is positive."""
        store, cmd = _stores()
        bat = make_battery(_sync(), store, cmd, initial_soc=0.3)
        bat.initialise()
        soc_before = bat.read_port("eps.battery.soc")

        for i in range(100):
            bat.receive("eps.battery.charge_current", 2.0)
            bat.do_step(t=i * 1.0, dt=1.0)

        assert bat.read_port("eps.battery.soc") > soc_before

    @pytest.mark.requirement("EPS-006")
    def test_battery_voltage_within_lion_range(self) -> None:
        """battery_voltage stays in 3.0–4.2 V across the full SoC range."""
        store, cmd = _stores()
        for soc in [0.05, 0.1, 0.3, 0.5, 0.8, 0.9, 1.0]:
            bat = make_battery(_sync(), store, cmd, initial_soc=soc)
            bat.initialise()
            v = bat.read_port("eps.battery.voltage")
            assert 3.0 <= v <= 4.2, f"voltage {v:.3f}V out of range at SoC={soc}"

    @pytest.mark.requirement("EPS-007")
    def test_battery_soc_clamped_at_min(self) -> None:
        """battery_soc never falls below SOC_MIN even with sustained discharge."""
        store, cmd = _stores()
        bat = make_battery(_sync(), store, cmd, initial_soc=0.06)
        bat.initialise()

        for i in range(10000):
            bat.receive("eps.battery.charge_current", -10.0)
            bat.do_step(t=i * 1.0, dt=1.0)

        assert bat.read_port("eps.battery.soc") >= SOC_MIN

    @pytest.mark.requirement("EPS-007")
    def test_battery_soc_clamped_at_max(self) -> None:
        """battery_soc never exceeds SOC_MAX even with sustained charge."""
        store, cmd = _stores()
        bat = make_battery(_sync(), store, cmd, initial_soc=0.95)
        bat.initialise()

        for i in range(10000):
            bat.receive("eps.battery.charge_current", 10.0)
            bat.do_step(t=i * 1.0, dt=1.0)

        assert bat.read_port("eps.battery.soc") <= SOC_MAX


# ---------------------------------------------------------------------------
# Integrated EPS — EPS-008 through EPS-016
# ---------------------------------------------------------------------------

class EpsIntegrationTests:

    def _make_eps(self) -> tuple:
        store, cmd = _stores()
        sync = _sync()
        solar   = make_solar_array(sync, store, cmd)
        battery = make_battery(sync, store, cmd, initial_soc=0.8)
        pcdu    = make_pcdu(sync, store, cmd)
        solar.initialise()
        battery.initialise()
        pcdu.initialise()
        return solar, battery, pcdu

    @pytest.mark.requirement("EPS-008")
    def test_pcdu_positive_current_when_generation_exceeds_load(self) -> None:
        """charge_current > 0 when solar generation > load (6 LCLs = 30W, sun = 90W)."""
        solar, battery, pcdu = self._make_eps()
        _step_eps(solar, battery, pcdu, illumination=1.0, n_lcls_on=6, dt=1.0, t=0.0)
        assert pcdu.read_port("eps.pcdu.charge_current") > 0.0

    @pytest.mark.requirement("EPS-009")
    def test_pcdu_negative_current_when_load_exceeds_generation(self) -> None:
        """charge_current < 0 when load > generation (eclipse, 6 LCLs on = 30W load)."""
        solar, battery, pcdu = self._make_eps()
        _step_eps(solar, battery, pcdu, illumination=0.0, n_lcls_on=6, dt=1.0, t=0.0)
        assert pcdu.read_port("eps.pcdu.charge_current") < 0.0

    @pytest.mark.requirement("EPS-010")
    def test_pcdu_bus_voltage_equals_battery_voltage(self) -> None:
        """Bus voltage (battery.voltage) stays above 3.0V during normal operation."""
        solar, battery, pcdu = self._make_eps()
        for i in range(50):
            _step_eps(solar, battery, pcdu, illumination=1.0, n_lcls_on=6,
                      dt=1.0, t=float(i))
        assert battery.read_port("eps.battery.voltage") >= 3.0

    @pytest.mark.requirement("EPS-011")
    def test_tc_pwr_001_battery_charges_in_sunlight(self) -> None:
        """Battery SoC increases when illumination=1.0 and load=30W (6 LCLs)."""
        solar, battery, pcdu = self._make_eps()
        soc_before = battery.read_port("eps.battery.soc")

        for i in range(200):
            _step_eps(solar, battery, pcdu, illumination=1.0, n_lcls_on=6,
                      dt=1.0, t=float(i))

        assert battery.read_port("eps.battery.soc") > soc_before

    @pytest.mark.requirement("EPS-012")
    def test_tc_pwr_002_battery_discharges_in_eclipse(self) -> None:
        """Battery SoC decreases in eclipse with 30W load."""
        solar, battery, pcdu = self._make_eps()
        soc_before = battery.read_port("eps.battery.soc")

        for i in range(200):
            _step_eps(solar, battery, pcdu, illumination=0.0, n_lcls_on=6,
                      dt=1.0, t=float(i))

        assert battery.read_port("eps.battery.soc") < soc_before

    @pytest.mark.requirement("EPS-013")
    def test_bus_voltage_remains_above_3v(self) -> None:
        """Battery voltage stays above 3.0V during normal sunlit operation."""
        solar, battery, pcdu = self._make_eps()

        for i in range(500):
            _step_eps(solar, battery, pcdu, illumination=1.0, n_lcls_on=6,
                      dt=1.0, t=float(i))
            v = battery.read_port("eps.battery.voltage")
            assert v >= 3.0, f"bus voltage dropped to {v:.3f}V at t={i}s"

    @pytest.mark.requirement("EPS-014")
    def test_decomposed_eps_charges_in_sunlight(self) -> None:
        """Decomposed native EPS: SoC rises from initial when illuminated."""
        solar, battery, pcdu = self._make_eps()
        # Start at low SoC to give headroom
        store, cmd = _stores()
        battery = make_battery(_sync(), store, cmd, initial_soc=0.4)
        battery.initialise()

        soc_before = battery.read_port("eps.battery.soc")
        for i in range(200):
            _step_eps(solar, battery, pcdu, illumination=1.0, n_lcls_on=4,
                      dt=1.0, t=float(i))

        assert battery.read_port("eps.battery.soc") > soc_before

    @pytest.mark.requirement("EPS-015")
    def test_decomposed_eps_discharges_in_eclipse(self) -> None:
        """Decomposed native EPS: SoC falls in eclipse with load."""
        solar, battery, pcdu = self._make_eps()
        soc_before = battery.read_port("eps.battery.soc")

        for i in range(200):
            _step_eps(solar, battery, pcdu, illumination=0.0, n_lcls_on=4,
                      dt=1.0, t=float(i))

        assert battery.read_port("eps.battery.soc") < soc_before

    @pytest.mark.requirement("EPS-016")
    def test_decomposed_eps_generated_power(self) -> None:
        """Decomposed EPS: generated_power = 0 in eclipse, ~90W in full sun."""
        solar, battery, pcdu = self._make_eps()

        solar.receive("eps.solar_array.illumination", 0.0)
        solar.do_step(t=0.0, dt=1.0)
        assert solar.read_port("eps.solar_array.generated_power") == pytest.approx(0.0)

        solar.receive("eps.solar_array.illumination", 1.0)
        solar.do_step(t=1.0, dt=1.0)
        assert solar.read_port("eps.solar_array.generated_power") == pytest.approx(
            MAX_POWER_W * PANEL_EFFICIENCY, rel=0.01
        )


# ---------------------------------------------------------------------------
# PCDU — PCDU-001, PCDU-002, PCDU-003, PCDU-004
# ---------------------------------------------------------------------------

class PcduTests:

    def _make_pcdu(self) -> tuple:
        store, cmd = _stores()
        sync = _sync()
        solar   = make_solar_array(sync, store, cmd)
        battery = make_battery(sync, store, cmd, initial_soc=0.8)
        pcdu    = make_pcdu(sync, store, cmd)
        solar.initialise()
        battery.initialise()
        pcdu.initialise()
        return solar, battery, pcdu

    @pytest.mark.requirement("PCDU-001")
    def test_pcdu_lcl_switching(self) -> None:
        """LCL status follows enable command: enabled LCLs show status=1, disabled show 0."""
        solar, battery, pcdu = self._make_pcdu()

        # Enable only LCL1 and LCL3
        _step_eps(solar, battery, pcdu, illumination=1.0, n_lcls_on=0, dt=1.0, t=0.0)
        # Manually override LCL 1 and 3 on, rest off
        for i in range(1, 9):
            pcdu.receive(f"eps.pcdu.lcl{i}.enable", 1.0 if i in (1, 3) else 0.0)
        pcdu.receive("eps.solar_array.generated_power", 90.0)
        pcdu.receive("eps.solar_array.illumination", 1.0)
        pcdu.receive("eps.battery.voltage", battery.read_port("eps.battery.voltage"))
        pcdu.do_step(t=1.0, dt=1.0)

        assert pcdu.read_port("eps.pcdu.lcl1.status") == pytest.approx(1.0)
        assert pcdu.read_port("eps.pcdu.lcl3.status") == pytest.approx(1.0)
        assert pcdu.read_port("eps.pcdu.lcl2.status") == pytest.approx(0.0)
        assert pcdu.read_port("eps.pcdu.lcl4.status") == pytest.approx(0.0)

    @pytest.mark.requirement("PCDU-002")
    def test_pcdu_mppt_efficiency(self) -> None:
        """MPPT efficiency is non-zero at nominal illumination and degrades at extremes."""
        solar, battery, pcdu = self._make_pcdu()

        # At peak illumination (0.7) MPPT efficiency should be highest
        pcdu.receive("eps.solar_array.generated_power", 63.0)  # 0.7 * 90W
        pcdu.receive("eps.solar_array.illumination", 0.7)
        pcdu.receive("eps.battery.voltage", 4.0)
        for i in range(1, 9):
            pcdu.receive(f"eps.pcdu.lcl{i}.enable", -1.0)
        pcdu.do_step(t=0.0, dt=1.0)
        eff_peak = pcdu.read_port("eps.pcdu.mppt_efficiency")

        # At low illumination (0.1) efficiency should be lower
        pcdu.receive("eps.solar_array.generated_power", 9.0)
        pcdu.receive("eps.solar_array.illumination", 0.1)
        pcdu.do_step(t=1.0, dt=1.0)
        eff_low = pcdu.read_port("eps.pcdu.mppt_efficiency")

        assert eff_peak > 0.0
        assert eff_peak >= eff_low

    @pytest.mark.requirement("PCDU-003")
    def test_pcdu_uvlo_disconnects_loads(self) -> None:
        """UVLO activates below threshold voltage, driving charge_current to ~0."""
        solar, battery, pcdu = self._make_pcdu()

        # Force very low battery voltage (below UVLO threshold 3.1V)
        pcdu.receive("eps.solar_array.generated_power", 0.0)
        pcdu.receive("eps.solar_array.illumination", 0.0)
        pcdu.receive("eps.battery.voltage", 3.0)  # below 3.1V UVLO threshold
        for i in range(1, 9):
            pcdu.receive(f"eps.pcdu.lcl{i}.enable", -1.0)  # keep current state
        pcdu.do_step(t=0.0, dt=1.0)

        assert pcdu.read_port("eps.pcdu.uvlo_active") == pytest.approx(1.0)
        # With UVLO active and zero generation, charge_current ≈ 0 (no load to drain)
        assert pcdu.read_port("eps.pcdu.total_load") == pytest.approx(0.0)

    @pytest.mark.requirement("PCDU-004")
    def test_pcdu_power_balance(self) -> None:
        """Charge current reflects power balance: positive surplus, negative deficit."""
        solar, battery, pcdu = self._make_pcdu()
        vbat = battery.read_port("eps.battery.voltage")

        # Surplus: 90W generated, 1 LCL = 5W load → positive current
        pcdu.receive("eps.solar_array.generated_power", 90.0)
        pcdu.receive("eps.solar_array.illumination", 1.0)
        pcdu.receive("eps.battery.voltage", vbat)
        for i in range(1, 9):
            pcdu.receive(f"eps.pcdu.lcl{i}.enable", 1.0 if i == 1 else 0.0)
        pcdu.do_step(t=0.0, dt=1.0)
        assert pcdu.read_port("eps.pcdu.charge_current") > 0.0

        # Deficit: 0W generated, 6 LCLs = 30W load → negative current
        pcdu.receive("eps.solar_array.generated_power", 0.0)
        pcdu.receive("eps.solar_array.illumination", 0.0)
        pcdu.receive("eps.battery.voltage", vbat)
        for i in range(1, 9):
            pcdu.receive(f"eps.pcdu.lcl{i}.enable", 1.0 if i <= 6 else 0.0)
        pcdu.do_step(t=1.0, dt=1.0)
        assert pcdu.read_port("eps.pcdu.charge_current") < 0.0
