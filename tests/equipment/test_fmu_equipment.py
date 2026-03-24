"""
Tests for FmuEquipment.
Implements: SVF-DEV-004, SVF-DEV-014
"""

import pytest
from pathlib import Path
from svf.fmu_equipment import FmuEquipment
from svf.equipment import PortDirection

EPS_FMU = Path(__file__).parent.parent.parent / "models" / "EpsFmu.fmu"

EPS_MAP = {
    "battery_soc":        "eps.battery.soc",
    "battery_voltage":    "eps.battery.voltage",
    "bus_voltage":        "eps.bus.voltage",
    "generated_power":    "eps.solar_array.generated_power",
    "charge_current":     "eps.battery.charge_current",
    "solar_illumination": "eps.solar_array.illumination",
    "load_power":         "eps.load.power",
}


def test_fmu_equipment_ports_declared() -> None:
    """FmuEquipment declares ports from FMU model description."""
    eq = FmuEquipment(EPS_FMU, "eps", EPS_MAP)
    port_names = list(eq.ports.keys())
    assert "eps.battery.soc" in port_names
    assert "eps.solar_array.illumination" in port_names


def test_fmu_equipment_port_directions() -> None:
    """Output FMU variables are OUT ports, inputs are IN ports."""
    eq = FmuEquipment(EPS_FMU, "eps", EPS_MAP)
    assert eq.ports["eps.battery.soc"].direction == PortDirection.OUT
    assert eq.ports["eps.solar_array.illumination"].direction == PortDirection.IN


def test_fmu_equipment_missing_fmu() -> None:
    """FileNotFoundError raised for missing FMU."""
    with pytest.raises(FileNotFoundError, match="FMU not found"):
        FmuEquipment("nonexistent.fmu", "bad")


def test_fmu_equipment_step() -> None:
    """FmuEquipment steps correctly and OUT ports update."""
    eq = FmuEquipment(EPS_FMU, "eps", EPS_MAP)
    eq.initialise()

    # Set inputs
    eq.receive("eps.solar_array.illumination", 1.0)
    eq.receive("eps.load.power", 30.0)

    # Step
    eq.do_step(t=0.0, dt=1.0)

    # Check outputs
    soc = eq.read_port("eps.battery.soc")
    gen = eq.read_port("eps.solar_array.generated_power")
    assert soc > 0.0
    assert gen == pytest.approx(90.0, abs=1.0)

    eq.teardown()


def test_fmu_equipment_no_map() -> None:
    """FmuEquipment works without parameter_map using raw FMU names."""
    eq = FmuEquipment(EPS_FMU, "eps")
    assert "battery_soc" in eq.ports
    assert "solar_illumination" in eq.ports
    eq.teardown()
