"""Tests for Thruster Equipment model."""
from __future__ import annotations
import pytest
from svf.abstractions import SyncProtocol
from svf.parameter_store import ParameterStore
from svf.command_store import CommandStore
from svf.models.thruster import (
    make_thruster, STATUS_NOMINAL, STATUS_OFF,
    STATUS_EMPTY, INITIAL_PROPELLANT_KG, AMBIENT_TEMP_C
)
from svf.native_equipment import NativeEquipment


class _NoSync(SyncProtocol):
    def reset(self) -> None: pass
    def publish_ready(self, model_id: str, t: float) -> None: pass
    def wait_for_ready(self, expected: list[str], timeout: float) -> bool:
        return True


@pytest.fixture
def thr() -> NativeEquipment:
    eq = make_thruster(_NoSync(), ParameterStore(), CommandStore())
    eq.initialise()
    return eq


class TestThrusterSuite:

    @pytest.mark.requirement("SVF-DEV-080")
    def test_thrust_when_enabled(self, thr: NativeEquipment) -> None:
        """Thruster produces thrust when enabled with propellant."""
        thr.receive("aocs.thr1.enable",     1.0)
        thr.receive("aocs.thr1.thrust_cmd", 0.5)
        thr.do_step(t=0.0, dt=0.1)
        assert thr.read_port("aocs.thr1.thrust") == pytest.approx(0.5, abs=0.01)

    @pytest.mark.requirement("SVF-DEV-080")
    def test_no_thrust_when_disabled(self, thr: NativeEquipment) -> None:
        """Thruster produces no thrust when disabled."""
        thr.receive("aocs.thr1.enable",     0.0)
        thr.receive("aocs.thr1.thrust_cmd", 1.0)
        thr.do_step(t=0.0, dt=0.1)
        assert thr.read_port("aocs.thr1.thrust") == pytest.approx(0.0)

    @pytest.mark.requirement("SVF-DEV-080")
    def test_propellant_decreases_when_firing(self, thr: NativeEquipment) -> None:
        """Propellant mass decreases when thruster fires."""
        thr.receive("aocs.thr1.enable",     1.0)
        thr.receive("aocs.thr1.thrust_cmd", 1.0)
        for i in range(10):
            thr.receive("aocs.thr1.enable",     1.0)
            thr.receive("aocs.thr1.thrust_cmd", 1.0)
            thr.do_step(t=i*0.1, dt=0.1)
        assert thr.read_port("aocs.thr1.propellant") < INITIAL_PROPELLANT_KG

    @pytest.mark.requirement("SVF-DEV-080")
    def test_status_empty_when_no_propellant(self, thr: NativeEquipment) -> None:
        """Status becomes EMPTY when propellant exhausted."""
        for i in range(4000):
            thr.receive("aocs.thr1.enable",     1.0)
            thr.receive("aocs.thr1.thrust_cmd", 1.0)
            thr.do_step(t=i*0.1, dt=0.1)
            if thr.read_port("aocs.thr1.propellant") <= 0.0:
                break
        assert thr.read_port("aocs.thr1.status") == STATUS_EMPTY

    @pytest.mark.requirement("SVF-DEV-080")
    def test_temperature_rises_when_firing(self, thr: NativeEquipment) -> None:
        """Thruster temperature increases during firing."""
        initial_temp = thr.read_port("aocs.thr1.temperature")
        for i in range(10):
            thr.receive("aocs.thr1.enable",     1.0)
            thr.receive("aocs.thr1.thrust_cmd", 1.0)
            thr.do_step(t=i*0.1, dt=0.1)
        assert thr.read_port("aocs.thr1.temperature") > initial_temp

    @pytest.mark.requirement("SVF-DEV-080")
    def test_status_off_when_not_firing(self, thr: NativeEquipment) -> None:
        """Status is OFF when thruster disabled."""
        thr.receive("aocs.thr1.enable", 0.0)
        thr.do_step(t=0.0, dt=0.1)
        assert thr.read_port("aocs.thr1.status") == STATUS_OFF
