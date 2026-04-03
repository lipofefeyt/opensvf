"""
Tests for PCDU model — nominal and failure cases.
Implements: PCDU-001, PCDU-002, PCDU-003, PCDU-004
"""

import pytest
from svf.abstractions import SyncProtocol
from svf.parameter_store import ParameterStore
from svf.command_store import CommandStore
from svf.models.pcdu import (
    make_pcdu, UVLO_THRESHOLD_V, MPPT_BASE_EFF,
    LCL_NOMINAL_LOAD_W, N_LCLS,
)
from svf.native_equipment import NativeEquipment


class _NoSync(SyncProtocol):
    def reset(self) -> None: pass
    def publish_ready(self, model_id: str, t: float) -> None: pass
    def wait_for_ready(self, expected: list[str], timeout: float) -> bool:
        return True


@pytest.fixture
def pcdu() -> NativeEquipment:
    eq = make_pcdu(_NoSync(), ParameterStore(), CommandStore())
    eq.initialise()
    # Set nominal inputs
    eq._port_values["eps.solar_array.generated_power"] = 90.0
    eq._port_values["eps.battery.voltage"]             = 3.8
    eq._port_values["eps.solar_array.illumination"]    = 0.7
    return eq


# ── LCL switching ─────────────────────────────────────────────────────────────

@pytest.mark.requirement("PCDU-001")
def test_pcdu_all_lcls_on_by_default(pcdu: NativeEquipment) -> None:
    """All LCLs are on by default."""
    pcdu.do_step(t=0.0, dt=1.0)
    for i in range(1, N_LCLS + 1):
        assert pcdu.read_port(f"eps.pcdu.lcl{i}.status") == pytest.approx(1.0)


@pytest.mark.requirement("PCDU-001")
def test_pcdu_lcl_switch_off(pcdu: NativeEquipment) -> None:
    """LCL turns off when commanded."""
    pcdu.receive("eps.pcdu.lcl1.enable", 0.0)
    pcdu.do_step(t=0.0, dt=1.0)
    assert pcdu.read_port("eps.pcdu.lcl1.status") == pytest.approx(0.0)


@pytest.mark.requirement("PCDU-001")
def test_pcdu_lcl_switch_on(pcdu: NativeEquipment) -> None:
    """LCL turns back on when commanded."""
    pcdu.receive("eps.pcdu.lcl1.enable", 0.0)
    pcdu.do_step(t=0.0, dt=1.0)
    assert pcdu.read_port("eps.pcdu.lcl1.status") == pytest.approx(0.0)

    pcdu.receive("eps.pcdu.lcl1.enable", 1.0)
    pcdu.do_step(t=1.0, dt=1.0)
    assert pcdu.read_port("eps.pcdu.lcl1.status") == pytest.approx(1.0)


@pytest.mark.requirement("PCDU-001")
def test_pcdu_load_reduces_when_lcl_off(pcdu: NativeEquipment) -> None:
    """Total load decreases when LCL switched off."""
    pcdu.do_step(t=0.0, dt=1.0)
    full_load = pcdu.read_port("eps.pcdu.total_load")

    pcdu.receive("eps.pcdu.lcl1.enable", 0.0)
    pcdu.do_step(t=1.0, dt=1.0)
    reduced_load = pcdu.read_port("eps.pcdu.total_load")

    assert reduced_load < full_load
    assert reduced_load == pytest.approx(full_load - LCL_NOMINAL_LOAD_W)


@pytest.mark.requirement("PCDU-004")
def test_pcdu_lcl_status_reported_per_channel(pcdu: NativeEquipment) -> None:
    """Each LCL reports its own status independently."""
    pcdu.receive("eps.pcdu.lcl3.enable", 0.0)
    pcdu.do_step(t=0.0, dt=1.0)

    assert pcdu.read_port("eps.pcdu.lcl3.status") == pytest.approx(0.0)
    assert pcdu.read_port("eps.pcdu.lcl1.status") == pytest.approx(1.0)
    assert pcdu.read_port("eps.pcdu.lcl5.status") == pytest.approx(1.0)


# ── MPPT ──────────────────────────────────────────────────────────────────────

@pytest.mark.requirement("PCDU-002")
def test_pcdu_mppt_efficiency_at_peak_illumination(
    pcdu: NativeEquipment,
) -> None:
    """MPPT efficiency is near base efficiency at peak illumination."""
    pcdu._port_values["eps.solar_array.illumination"] = 0.7
    pcdu.do_step(t=0.0, dt=1.0)
    assert pcdu.read_port("eps.pcdu.mppt_efficiency") == pytest.approx(
        MPPT_BASE_EFF, abs=0.01
    )


@pytest.mark.requirement("PCDU-002")
def test_pcdu_mppt_efficiency_zero_in_eclipse(
    pcdu: NativeEquipment,
) -> None:
    """MPPT efficiency is 0 in eclipse."""
    pcdu._port_values["eps.solar_array.illumination"] = 0.0
    pcdu._port_values["eps.solar_array.generated_power"] = 0.0
    pcdu.do_step(t=0.0, dt=1.0)
    assert pcdu.read_port("eps.pcdu.mppt_efficiency") == pytest.approx(0.0)


@pytest.mark.requirement("PCDU-002")
def test_pcdu_charge_current_positive_when_generation_exceeds_load(
    pcdu: NativeEquipment,
) -> None:
    """Positive charge current when solar power exceeds load."""
    pcdu._port_values["eps.solar_array.generated_power"] = 90.0
    pcdu._port_values["eps.solar_array.illumination"]    = 0.7
    pcdu.do_step(t=0.0, dt=1.0)
    assert pcdu.read_port("eps.pcdu.charge_current") > 0.0


@pytest.mark.requirement("PCDU-002")
def test_pcdu_charge_current_negative_in_eclipse(
    pcdu: NativeEquipment,
) -> None:
    """Negative charge current in eclipse — loads drain battery."""
    pcdu._port_values["eps.solar_array.generated_power"] = 0.0
    pcdu._port_values["eps.solar_array.illumination"]    = 0.0
    pcdu.do_step(t=0.0, dt=1.0)
    assert pcdu.read_port("eps.pcdu.charge_current") < 0.0


# ── UVLO ──────────────────────────────────────────────────────────────────────

@pytest.mark.requirement("PCDU-003")
def test_pcdu_uvlo_activates_below_threshold(
    pcdu: NativeEquipment,
) -> None:
    """UVLO activates when battery voltage drops below threshold."""
    pcdu._port_values["eps.battery.voltage"] = UVLO_THRESHOLD_V - 0.1
    pcdu.do_step(t=0.0, dt=1.0)
    assert pcdu.read_port("eps.pcdu.uvlo_active") == pytest.approx(1.0)


@pytest.mark.requirement("PCDU-003")
def test_pcdu_uvlo_disconnects_all_loads(pcdu: NativeEquipment) -> None:
    """UVLO disconnects all loads — total_load = 0."""
    pcdu._port_values["eps.battery.voltage"] = UVLO_THRESHOLD_V - 0.1
    pcdu.do_step(t=0.0, dt=1.0)
    assert pcdu.read_port("eps.pcdu.total_load") == pytest.approx(0.0)


@pytest.mark.requirement("PCDU-003")
def test_pcdu_uvlo_clears_above_threshold(pcdu: NativeEquipment) -> None:
    """UVLO clears when battery voltage recovers above threshold."""
    pcdu._port_values["eps.battery.voltage"] = UVLO_THRESHOLD_V - 0.1
    pcdu.do_step(t=0.0, dt=1.0)
    assert pcdu.read_port("eps.pcdu.uvlo_active") == pytest.approx(1.0)

    pcdu._port_values["eps.battery.voltage"] = UVLO_THRESHOLD_V + 0.1
    pcdu.do_step(t=1.0, dt=1.0)
    assert pcdu.read_port("eps.pcdu.uvlo_active") == pytest.approx(0.0)
    assert pcdu.read_port("eps.pcdu.total_load") > 0.0
