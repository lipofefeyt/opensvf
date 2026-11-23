"""Tests for universal equipment fault engine."""
from __future__ import annotations
import pytest
from svf.core.equipment_fault import (
    EquipmentFaultEngine, EquipmentFault, FaultMode
)
from svf.stores.parameter_store import ParameterStore
from svf.stores.command_store import CommandStore
from svf.core.abstractions import SyncProtocol
from svf.models.aocs.magnetometer import make_magnetometer


class _NoSync(SyncProtocol):
    def reset(self) -> None: pass
    def publish_ready(self, model_id: str, t: float) -> None: pass
    def wait_for_ready(self, e: list[str], t: float) -> bool: return True


def make_mag():
    store     = ParameterStore()
    cmd_store = CommandStore()
    eq = make_magnetometer(_NoSync(), store, cmd_store)
    eq.initialise()
    return eq, store, cmd_store


class TestEquipmentFaultEngineSuite:

    @pytest.mark.requirement("SVF-DEV-132")
    def test_stuck_fault_returns_fixed_value(self) -> None:
        """STUCK fault returns fixed value regardless of physics."""
        engine = EquipmentFaultEngine("mag1")
        engine.inject(EquipmentFault(
            port="aocs.mag.field_x",
            fault_type=FaultMode.STUCK,
            value=99.0,
            duration_s=10.0,
            injected_at=0.0,
        ))
        result = engine.apply_read("aocs.mag.field_x", raw_value=0.001, t=1.0)
        assert result == pytest.approx(99.0)

    @pytest.mark.requirement("SVF-DEV-132")
    def test_bias_fault_adds_offset(self) -> None:
        """BIAS fault adds constant offset to value."""
        engine = EquipmentFaultEngine("mag1")
        engine.inject(EquipmentFault(
            port="aocs.mag.field_x",
            fault_type=FaultMode.BIAS,
            value=1e-5,
            duration_s=10.0,
            injected_at=0.0,
        ))
        result = engine.apply_read("aocs.mag.field_x", raw_value=1e-4, t=1.0)
        assert result == pytest.approx(1e-4 + 1e-5)

    @pytest.mark.requirement("SVF-DEV-132")
    def test_scale_fault_multiplies_value(self) -> None:
        """SCALE fault multiplies value by factor."""
        engine = EquipmentFaultEngine("rw1")
        engine.inject(EquipmentFault(
            port="aocs.rw1.torque_cmd",
            fault_type=FaultMode.SCALE,
            value=0.5,
            duration_s=10.0,
            injected_at=0.0,
        ))
        result = engine.apply_read("aocs.rw1.torque_cmd", raw_value=0.1, t=1.0)
        assert result == pytest.approx(0.05)

    @pytest.mark.requirement("SVF-DEV-132")
    def test_fail_fault_returns_zero(self) -> None:
        """FAIL fault returns 0.0 regardless of input."""
        engine = EquipmentFaultEngine("str1")
        engine.inject(EquipmentFault(
            port="aocs.str1.quaternion_w",
            fault_type=FaultMode.FAIL,
            value=0.0,
            duration_s=10.0,
            injected_at=0.0,
        ))
        result = engine.apply_read(
            "aocs.str1.quaternion_w", raw_value=1.0, t=1.0
        )
        assert result == pytest.approx(0.0)

    @pytest.mark.requirement("SVF-DEV-132")
    def test_noise_fault_adds_gaussian_noise(self) -> None:
        """NOISE fault adds reproducible Gaussian noise."""
        engine = EquipmentFaultEngine("mag1", seed=42)
        engine.inject(EquipmentFault(
            port="aocs.mag.field_x",
            fault_type=FaultMode.NOISE,
            value=1e-6,  # std_dev
            duration_s=10.0,
            injected_at=0.0,
        ))
        results = [
            engine.apply_read("aocs.mag.field_x", raw_value=0.0, t=float(i))
            for i in range(10)
        ]
        # Values should differ from raw (0.0) and from each other
        assert any(abs(r) > 0 for r in results)

    @pytest.mark.requirement("SVF-DEV-132")
    def test_fault_expires_after_duration(self) -> None:
        """Fault expires after duration_s and no longer applies."""
        engine = EquipmentFaultEngine("mag1")
        engine.inject(EquipmentFault(
            port="aocs.mag.field_x",
            fault_type=FaultMode.STUCK,
            value=99.0,
            duration_s=5.0,
            injected_at=0.0,
        ))
        # Before expiry
        assert engine.apply_read("aocs.mag.field_x", 0.001, t=4.0) == pytest.approx(99.0)
        # After expiry
        assert engine.apply_read("aocs.mag.field_x", 0.001, t=6.0) == pytest.approx(0.001)

    @pytest.mark.requirement("SVF-DEV-132")
    def test_clear_removes_fault(self) -> None:
        """clear() removes fault and value passes through."""
        engine = EquipmentFaultEngine("mag1")
        engine.inject(EquipmentFault(
            port="aocs.mag.field_x",
            fault_type=FaultMode.STUCK,
            value=99.0,
            duration_s=0.0,
            injected_at=0.0,
        ))
        engine.clear("aocs.mag.field_x")
        result = engine.apply_read("aocs.mag.field_x", raw_value=0.001, t=1.0)
        assert result == pytest.approx(0.001)

    @pytest.mark.requirement("SVF-DEV-132")
    def test_fault_only_affects_specified_port(self) -> None:
        """Fault on one port does not affect other ports."""
        engine = EquipmentFaultEngine("mag1")
        engine.inject(EquipmentFault(
            port="aocs.mag.field_x",
            fault_type=FaultMode.STUCK,
            value=99.0,
            duration_s=10.0,
            injected_at=0.0,
        ))
        x = engine.apply_read("aocs.mag.field_x", raw_value=0.001, t=1.0)
        y = engine.apply_read("aocs.mag.field_y", raw_value=0.002, t=1.0)
        assert x == pytest.approx(99.0)
        assert y == pytest.approx(0.002)

    @pytest.mark.requirement("SVF-DEV-132")
    def test_engine_attached_to_equipment(self) -> None:
        """EquipmentFaultEngine attached to Equipment intercepts read_port."""
        eq, store, _ = make_mag()
        engine = EquipmentFaultEngine("mag1")
        engine.inject(EquipmentFault(
            port="aocs.mag.field_x",
            fault_type=FaultMode.STUCK,
            value=42.0,
            duration_s=0.0,
            injected_at=0.0,
        ))
        eq.attach_fault_engine(engine)
        eq._port_values["aocs.mag.field_x"] = 0.001
        result = eq.read_port("aocs.mag.field_x")
        assert result == pytest.approx(42.0)

    @pytest.mark.requirement("SVF-DEV-132")
    def test_duration_fault_expires_on_equipment_tick(self) -> None:
        """A duration_s fault on an attached engine expires as ticks advance."""
        eq, store, _ = make_mag()
        engine = EquipmentFaultEngine("mag1")
        engine.inject(EquipmentFault(
            port="aocs.mag.field_x",
            fault_type=FaultMode.STUCK,
            value=42.0,
            duration_s=1.0,
            injected_at=0.0,
        ))
        eq.attach_fault_engine(engine)
        # Unpowered magnetometer writes 0.0 to field_x every tick.
        eq.on_tick(0.0, 0.5)
        assert store.read("aocs.mag.field_x").value == pytest.approx(42.0)
        eq.on_tick(0.5, 0.5)
        assert store.read("aocs.mag.field_x").value == pytest.approx(42.0)
        eq.on_tick(1.0, 0.5)
        assert store.read("aocs.mag.field_x").value == pytest.approx(0.0)
        assert engine.active_faults(1.0) == []

    @pytest.mark.requirement("SVF-DEV-132")
    def test_read_fault_uses_tick_time(self) -> None:
        """read_port inside a tick sees fault time equal to the tick time."""
        eq, _, _ = make_mag()
        engine = EquipmentFaultEngine("mag1")
        engine.inject(EquipmentFault(
            port="aocs.mag.power_enable",
            fault_type=FaultMode.STUCK,
            value=0.0,
            duration_s=2.0,
            injected_at=10.0,
        ))
        eq.attach_fault_engine(engine)
        eq._port_values["aocs.mag.power_enable"] = 1.0
        eq.on_tick(11.0, 0.5)
        assert eq.read_port("aocs.mag.power_enable") == pytest.approx(0.0)
        eq.on_tick(12.0, 0.5)
        assert eq.read_port("aocs.mag.power_enable") == pytest.approx(1.0)
