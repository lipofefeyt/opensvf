"""
SVF Equipment Contract Tests
Verifies the generic Equipment contract that all equipment must satisfy.
Implements: EQP-001 through EQP-012
"""

import pytest
from svf.core.abstractions import SyncProtocol
from svf.stores.parameter_store import ParameterStore
from svf.stores.command_store import CommandStore
from svf.core.equipment import Equipment, PortDefinition, PortDirection
from svf.core.fmu_equipment import FmuEquipment
from svf.core.native_equipment import NativeEquipment
from pathlib import Path

EPS_FMU = Path(__file__).parent.parent.parent / "models" / "fmu" / "EpsFmu.fmu"

EPS_MAP = {
    "battery_soc":        "eps.battery.soc",
    "solar_illumination": "eps.solar_array.illumination",
    "load_power":         "eps.load.power",
    "bus_voltage":        "eps.bus.voltage",
    "generated_power":    "eps.solar_array.generated_power",
    "battery_voltage":    "eps.battery.voltage",
    "charge_current":     "eps.battery.charge_current",
}


class _NoSync(SyncProtocol):
    def reset(self) -> None: pass
    def publish_ready(self, model_id: str, t: float) -> None: pass
    def wait_for_ready(self, expected: list[str], timeout: float) -> bool: return True


@pytest.fixture
def sync() -> _NoSync:
    return _NoSync()


@pytest.fixture
def store() -> ParameterStore:
    return ParameterStore()


@pytest.fixture
def cmd_store() -> CommandStore:
    return CommandStore()


class _SimpleSource(Equipment):
    def __init__(self, equipment_id: str, sync_protocol: SyncProtocol,
                 store: ParameterStore) -> None:
        super().__init__(equipment_id, sync_protocol=sync_protocol, store=store)

    def _declare_ports(self) -> list[PortDefinition]:
        return [PortDefinition("power_out", PortDirection.OUT, unit="W")]

    def initialise(self, start_time: float = 0.0) -> None:
        pass

    def do_step(self, t: float, dt: float) -> None:
        self.write_port("power_out", 10.0)


class _SimpleSink(Equipment):
    def __init__(self, equipment_id: str, sync_protocol: SyncProtocol,
                 store: ParameterStore) -> None:
        super().__init__(equipment_id, sync_protocol=sync_protocol, store=store)

    def _declare_ports(self) -> list[PortDefinition]:
        return [PortDefinition("power_in", PortDirection.IN, unit="W")]

    def initialise(self, start_time: float = 0.0) -> None:
        pass

    def do_step(self, t: float, dt: float) -> None:
        pass


class _BidirectionalEquipment(Equipment):
    def __init__(self, equipment_id: str, sync_protocol: SyncProtocol,
                 store: ParameterStore) -> None:
        super().__init__(equipment_id, sync_protocol=sync_protocol, store=store)

    def _declare_ports(self) -> list[PortDefinition]:
        return [
            PortDefinition("enable", PortDirection.IN),
            PortDefinition("speed", PortDirection.OUT, unit="rpm"),
            PortDefinition("status", PortDirection.OUT),
        ]

    def initialise(self, start_time: float = 0.0) -> None:
        self._speed = 0.0

    def do_step(self, t: float, dt: float) -> None:
        enabled = self.read_port("enable")
        if enabled > 0.5:
            self._speed += 100.0 * dt
        self.write_port("speed", self._speed)
        self.write_port("status", 1.0 if enabled > 0.5 else 0.0)


# ── EQP-001: Port declaration ─────────────────────────────────────────────────

@pytest.mark.requirement("EQP-001")
def test_equipment_construction(sync: _NoSync, store: ParameterStore) -> None:
    eq = _SimpleSource("source_1", sync_protocol=sync, store=store)
    assert eq.equipment_id == "source_1"
    assert "power_out" in eq.ports


@pytest.mark.requirement("EQP-001")
def test_equipment_port_directions(sync: _NoSync, store: ParameterStore) -> None:
    eq = _BidirectionalEquipment("bi_eq", sync_protocol=sync, store=store)
    assert len(eq.in_ports()) == 1
    assert len(eq.out_ports()) == 2


@pytest.mark.requirement("EQP-001")
def test_equipment_duplicate_port_raises(
    sync: _NoSync, store: ParameterStore
) -> None:
    class _DuplicatePort(Equipment):
        def __init__(self, equipment_id: str, sync_protocol: SyncProtocol,
                     store: ParameterStore) -> None:
            super().__init__(equipment_id, sync_protocol=sync_protocol, store=store)

        def _declare_ports(self) -> list[PortDefinition]:
            return [
                PortDefinition("power", PortDirection.OUT),
                PortDefinition("power", PortDirection.IN),
            ]
        def initialise(self, start_time: float = 0.0) -> None: pass
        def do_step(self, t: float, dt: float) -> None: pass

    with pytest.raises(ValueError, match="duplicate port"):
        _DuplicatePort("bad", sync_protocol=sync, store=store)


# ── EQP-002: write_port on IN port raises ─────────────────────────────────────

@pytest.mark.requirement("EQP-002", "EQP-011")
def test_write_port_out(sync: _NoSync, store: ParameterStore) -> None:
    eq = _SimpleSource("src", sync_protocol=sync, store=store)
    eq.initialise()
    eq.do_step(0.0, 0.1)
    assert eq.read_port("power_out") == pytest.approx(10.0)


@pytest.mark.requirement("EQP-002")
def test_write_port_to_in_raises(sync: _NoSync, store: ParameterStore) -> None:
    eq = _SimpleSink("sink", sync_protocol=sync, store=store)
    eq.initialise()
    with pytest.raises(ValueError, match="Cannot write to IN port"):
        eq.write_port("power_in", 5.0)


# ── EQP-003: read unknown port raises ────────────────────────────────────────

@pytest.mark.requirement("EQP-003")
def test_read_port_unknown_raises(sync: _NoSync, store: ParameterStore) -> None:
    eq = _SimpleSource("src", sync_protocol=sync, store=store)
    with pytest.raises(ValueError, match="Unknown port"):
        eq.read_port("nonexistent")


# ── EQP-004: receive into IN port ────────────────────────────────────────────

@pytest.mark.requirement("EQP-004")
def test_receive_into_in_port(sync: _NoSync, store: ParameterStore) -> None:
    eq = _SimpleSink("sink", sync_protocol=sync, store=store)
    eq.initialise()
    eq.receive("power_in", 42.0)
    assert eq.read_port("power_in") == pytest.approx(42.0)


@pytest.mark.requirement("EQP-004")
def test_receive_into_out_port_raises(sync: _NoSync, store: ParameterStore) -> None:
    eq = _SimpleSource("src", sync_protocol=sync, store=store)
    with pytest.raises(ValueError, match="Cannot receive into OUT port"):
        eq.receive("power_out", 1.0)


@pytest.mark.requirement("EQP-003")
def test_receive_unknown_port_raises(sync: _NoSync, store: ParameterStore) -> None:
    eq = _SimpleSource("src", sync_protocol=sync, store=store)
    with pytest.raises(ValueError, match="Unknown port"):
        eq.receive("nonexistent", 1.0)


# ── EQP-005, EQP-006: on_tick reads IN, writes OUT ───────────────────────────

@pytest.mark.requirement("EQP-005", "EQP-006")
def test_source_to_sink_wiring(sync: _NoSync, store: ParameterStore) -> None:
    source = _SimpleSource("src", sync_protocol=sync, store=store)
    sink = _SimpleSink("sink", sync_protocol=sync, store=store)
    source.initialise()
    sink.initialise()
    source.do_step(0.0, 0.1)
    sink.receive("power_in", source.read_port("power_out"))
    sink.do_step(0.1, 0.1)
    assert source.read_port("power_out") == pytest.approx(10.0)


@pytest.mark.requirement("EQP-005", "EQP-006")
def test_bidirectional_equipment_step(
    sync: _NoSync, store: ParameterStore
) -> None:
    eq = _BidirectionalEquipment("rw", sync_protocol=sync, store=store)
    eq.initialise()
    eq.do_step(0.0, 0.1)
    assert eq.read_port("speed") == pytest.approx(0.0)
    eq.receive("enable", 1.0)
    eq.do_step(0.1, 0.1)
    assert eq.read_port("speed") == pytest.approx(10.0)
    assert eq.read_port("status") == pytest.approx(1.0)


# ── EQP-007: parameter_map translation ───────────────────────────────────────

@pytest.mark.requirement("EQP-007")
def test_parameter_map_translates_port_names(
    sync: _NoSync, store: ParameterStore, cmd_store: CommandStore
) -> None:
    """FmuEquipment translates FMU variable names to canonical port names."""
    eq = FmuEquipment(
        fmu_path=EPS_FMU,
        equipment_id="eps",
        sync_protocol=sync,
        store=store,
        command_store=cmd_store,
        parameter_map=EPS_MAP,
    )
    assert "eps.battery.soc" in eq.ports
    assert "battery_soc" not in eq.ports


@pytest.mark.requirement("EQP-007")
def test_parameter_map_fallback_to_raw_name(
    sync: _NoSync, store: ParameterStore, cmd_store: CommandStore
) -> None:
    """Without parameter_map, raw FMU variable names are used as port names."""
    eq = FmuEquipment(
        fmu_path=EPS_FMU,
        equipment_id="eps",
        sync_protocol=sync,
        store=store,
        command_store=cmd_store,
    )
    assert "battery_soc" in eq.ports
    assert "eps.battery.soc" not in eq.ports


# ── EQP-011: default port value is 0.0 ───────────────────────────────────────

@pytest.mark.requirement("EQP-011")
def test_port_default_value_is_zero(sync: _NoSync, store: ParameterStore) -> None:
    eq = _SimpleSink("sink", sync_protocol=sync, store=store)
    assert eq.read_port("power_in") == pytest.approx(0.0)


# ── EQP-012: teardown safe without initialise ─────────────────────────────────

@pytest.mark.requirement("EQP-012")
def test_teardown_safe_without_initialise(
    sync: _NoSync, store: ParameterStore, cmd_store: CommandStore
) -> None:
    """teardown() is safe to call even if initialise() was never called."""
    eq = FmuEquipment(
        fmu_path=EPS_FMU,
        equipment_id="eps",
        sync_protocol=sync,
        store=store,
        command_store=cmd_store,
    )
    eq.teardown()  # should not raise


@pytest.mark.requirement("EQP-012")
def test_native_teardown_safe_without_initialise(
    sync: _NoSync, store: ParameterStore, cmd_store: CommandStore
) -> None:
    """NativeEquipment teardown() is safe without initialise()."""
    def step(eq: NativeEquipment, t: float, dt: float) -> None:
        pass

    eq = NativeEquipment(
        equipment_id="test",
        ports=[PortDefinition("out", PortDirection.OUT)],
        step_fn=step,
        sync_protocol=sync,
        store=store,
        command_store=cmd_store,
    )
    eq.teardown()  # should not raise
