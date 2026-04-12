"""Tests for Thermal Equipment model."""
from __future__ import annotations
import pytest
from svf.abstractions import SyncProtocol
from svf.parameter_store import ParameterStore
from svf.command_store import CommandStore
from svf.models.thermal import make_thermal
from svf.native_equipment import NativeEquipment


class _NoSync(SyncProtocol):
    def reset(self) -> None: pass
    def publish_ready(self, model_id: str, t: float) -> None: pass
    def wait_for_ready(self, expected: list[str], timeout: float) -> bool:
        return True


@pytest.fixture
def thermal() -> NativeEquipment:
    eq = make_thermal(_NoSync(), ParameterStore(), CommandStore())
    eq.initialise()
    return eq


class TestThermalSuite:

    @pytest.mark.requirement("SVF-DEV-082")
    def test_sun_facing_panel_heats_up(self, thermal: NativeEquipment) -> None:
        """Sun-facing panel temperature increases in sunlight."""
        initial = thermal.read_port("thermal.panel_plus_x.temp_degc")
        thermal.receive("thermal.solar_illumination", 1.0)
        thermal.receive("thermal.equipment_power_w",  0.0)
        for i in range(100):
            thermal.do_step(t=i * 10.0, dt=10.0)
        final = thermal.read_port("thermal.panel_plus_x.temp_degc")
        assert final > initial

    @pytest.mark.requirement("SVF-DEV-082")
    def test_eclipse_panel_cools(self, thermal: NativeEquipment) -> None:
        """Panel cools in eclipse (no solar input)."""
        # First heat up
        thermal.receive("thermal.solar_illumination", 1.0)
        thermal.receive("thermal.equipment_power_w",  0.0)
        for i in range(100):
            thermal.do_step(t=i * 10.0, dt=10.0)
        hot_temp = thermal.read_port("thermal.panel_plus_x.temp_degc")

        # Then eclipse
        thermal.receive("thermal.solar_illumination", 0.0)
        for i in range(100, 200):
            thermal.do_step(t=i * 10.0, dt=10.0)
        cold_temp = thermal.read_port("thermal.panel_plus_x.temp_degc")
        assert cold_temp < hot_temp

    @pytest.mark.requirement("SVF-DEV-082")
    def test_equipment_dissipation_heats_internal(
        self, thermal: NativeEquipment
    ) -> None:
        """Equipment power dissipation raises internal node temperature above no-power baseline."""
        # Run with zero power to get baseline
        thermal.receive("thermal.solar_illumination", 0.0)
        thermal.receive("thermal.equipment_power_w",  0.0)
        for i in range(100):
            thermal.do_step(t=i * 10.0, dt=10.0)
        baseline = thermal.read_port("thermal.internal.temp_degc")

        # Reset and run with power
        thermal2 = make_thermal(_NoSync(), ParameterStore(), CommandStore())
        thermal2.initialise()
        thermal2.receive("thermal.solar_illumination", 0.0)
        thermal2.receive("thermal.equipment_power_w",  10.0)
        for i in range(100):
            thermal2.do_step(t=i * 10.0, dt=10.0)
        powered = thermal2.read_port("thermal.internal.temp_degc")
        assert powered > baseline

    @pytest.mark.requirement("SVF-DEV-082")
    def test_cavity_temp_equals_internal(self, thermal: NativeEquipment) -> None:
        """Cavity temperature tracks internal node."""
        thermal.receive("thermal.solar_illumination", 0.0)
        thermal.receive("thermal.equipment_power_w",  5.0)
        thermal.do_step(t=0.0, dt=10.0)
        internal = thermal.read_port("thermal.internal.temp_degc")
        cavity   = thermal.read_port("thermal.cavity.temp_degc")
        assert internal == pytest.approx(cavity)

    @pytest.mark.requirement("SVF-DEV-082")
    def test_min_max_temps(self, thermal: NativeEquipment) -> None:
        """Min/max temperatures span all nodes."""
        thermal.receive("thermal.solar_illumination", 1.0)
        thermal.receive("thermal.equipment_power_w",  0.0)
        for i in range(50):
            thermal.do_step(t=i * 10.0, dt=10.0)
        t_min = thermal.read_port("thermal.min_temp_degc")
        t_max = thermal.read_port("thermal.max_temp_degc")
        assert t_min <= t_max

    @pytest.mark.requirement("SVF-DEV-082")
    def test_radiator_panel_cooler_than_sun_panel(
        self, thermal: NativeEquipment
    ) -> None:
        """Low-absorptivity radiator panel stays cooler than sun-facing panel."""
        thermal.receive("thermal.solar_illumination", 1.0)
        thermal.receive("thermal.equipment_power_w",  0.0)
        for i in range(500):
            thermal.do_step(t=i * 10.0, dt=10.0)
        sun_panel = thermal.read_port("thermal.panel_plus_x.temp_degc")
        radiator  = thermal.read_port("thermal.panel_minus_x.temp_degc")
        assert radiator < sun_panel
