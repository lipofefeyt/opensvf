"""
Tests for B-dot detumbling controller.
Implements: SVF-DEV-038
"""

import pytest
import math
from svf.abstractions import SyncProtocol
from svf.parameter_store import ParameterStore
from svf.command_store import CommandStore
from svf.models.bdot_controller import make_bdot_controller, DEFAULT_GAIN, MAX_DIPOLE


class _NoSync(SyncProtocol):
    def reset(self) -> None: pass
    def publish_ready(self, model_id: str, t: float) -> None: pass
    def wait_for_ready(self, expected: list[str], timeout: float) -> bool:
        return True


@pytest.fixture
def bdot() -> object:
    eq = make_bdot_controller(_NoSync(), ParameterStore(), CommandStore())
    eq.initialise()
    return eq


@pytest.mark.requirement("SVF-DEV-038")
def test_bdot_inactive_when_disabled(bdot: object) -> None:
    """No dipole output when controller disabled."""
    from svf.native_equipment import NativeEquipment
    assert isinstance(bdot, NativeEquipment)
    bdot.receive("aocs.bdot.enable", 0.0)
    bdot.do_step(t=0.0, dt=1.0)
    assert bdot.read_port("aocs.mtq.dipole_x") == pytest.approx(0.0)
    assert bdot.read_port("aocs.bdot.active") == pytest.approx(0.0)


@pytest.mark.requirement("SVF-DEV-038")
def test_bdot_zero_dipole_on_first_tick(bdot: object) -> None:
    """First tick produces zero dipole (no B-dot yet)."""
    from svf.native_equipment import NativeEquipment
    assert isinstance(bdot, NativeEquipment)
    bdot.receive("aocs.bdot.enable", 1.0)
    bdot.receive("aocs.mag.field_x", 3e-5)
    bdot.receive("aocs.mag.field_y", 1e-5)
    bdot.receive("aocs.mag.field_z", -4e-5)
    bdot.do_step(t=0.0, dt=1.0)
    assert bdot.read_port("aocs.mtq.dipole_x") == pytest.approx(0.0)
    assert bdot.read_port("aocs.bdot.active") == pytest.approx(1.0)


@pytest.mark.requirement("SVF-DEV-038")
def test_bdot_opposes_field_change(bdot: object) -> None:
    """Dipole opposes B-dot — m = -k * dB/dt."""
    from svf.native_equipment import NativeEquipment
    assert isinstance(bdot, NativeEquipment)
    bdot.receive("aocs.bdot.enable", 1.0)

    # First tick — initialise
    bdot.receive("aocs.mag.field_x", 3e-5)
    bdot.do_step(t=0.0, dt=1.0)

    # Second tick — field increases in X → B-dot positive → dipole negative
    bdot.receive("aocs.mag.field_x", 4e-5)
    bdot.do_step(t=1.0, dt=1.0)

    dipole_x = bdot.read_port("aocs.mtq.dipole_x")
    bdot_x   = bdot.read_port("aocs.bdot.bdot_x")

    assert bdot_x > 0.0, "B-dot X should be positive (field increasing)"
    assert dipole_x < 0.0, "Dipole X should oppose B-dot (negative)"


@pytest.mark.requirement("SVF-DEV-038")
def test_bdot_dipole_saturated(bdot: object) -> None:
    """Dipole saturated at MAX_DIPOLE for large B-dot."""
    from svf.native_equipment import NativeEquipment
    assert isinstance(bdot, NativeEquipment)
    bdot.receive("aocs.bdot.enable", 1.0)

    # First tick
    bdot.receive("aocs.mag.field_x", 0.0)
    bdot.do_step(t=0.0, dt=1.0)

    # Huge field change → saturated dipole
    bdot.receive("aocs.mag.field_x", 1.0)  # 1T change in 1s
    bdot.do_step(t=1.0, dt=1.0)

    assert abs(bdot.read_port("aocs.mtq.dipole_x")) == pytest.approx(
        MAX_DIPOLE, abs=0.01
    )


@pytest.mark.requirement("SVF-DEV-038")
def test_bdot_zero_dipole_when_field_constant(bdot: object) -> None:
    """Zero dipole when magnetic field is constant (no rotation)."""
    from svf.native_equipment import NativeEquipment
    assert isinstance(bdot, NativeEquipment)
    bdot.receive("aocs.bdot.enable", 1.0)
    bdot.receive("aocs.mag.field_x", 3e-5)
    bdot.receive("aocs.mag.field_y", 1e-5)
    bdot.receive("aocs.mag.field_z", -4e-5)

    for i in range(5):
        bdot.do_step(t=float(i), dt=1.0)

    assert bdot.read_port("aocs.mtq.dipole_x") == pytest.approx(0.0, abs=1e-10)
    assert bdot.read_port("aocs.mtq.dipole_y") == pytest.approx(0.0, abs=1e-10)
    assert bdot.read_port("aocs.mtq.dipole_z") == pytest.approx(0.0, abs=1e-10)
