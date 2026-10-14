"""
SMP-aligned ISmpModel contract tests for all native simulation models (M50).

Parametrizes the full SMP-aligned lifecycle (publish -> configure -> connect)
over every NativeEquipment, OrbitalEnvironment, and Bus subclass, verifying
each satisfies the ISmpModel interface contract.

Implements: SVF-DEV-186
"""
from __future__ import annotations

from typing import Callable

import pytest

from svf.bus.can import CanBus, CanMessage
from svf.bus.mil1553 import Mil1553Bus, SubaddressMapping
from svf.bus.spw import RmapMapping, SpwBus, SpwNode
from svf.core.abstractions import SyncProtocol
from svf.core.equipment import Equipment
from svf.models.aocs.bdot_controller import make_bdot_controller
from svf.models.aocs.css import make_css
from svf.models.aocs.gps import make_gps
from svf.models.aocs.gyroscope import make_gyroscope
from svf.models.aocs.magnetometer import make_magnetometer
from svf.models.aocs.magnetorquer import make_magnetorquer
from svf.models.aocs.reaction_wheel import make_reaction_wheel
from svf.models.aocs.star_tracker import make_star_tracker
from svf.models.aocs.thruster import make_thruster
from svf.models.dynamics.rigid_body import make_rigid_body_dynamics
from svf.models.environment.orbital_environment import OrbitalEnvironment
from svf.models.eps.battery import make_battery
from svf.models.eps.pcdu import make_pcdu
from svf.models.eps.solar_array import make_solar_array
from svf.models.thermal.thermal import make_thermal
from svf.models.ttc.sbt import make_sbt
from svf.smp import ISmpModel, SmpState
from svf.stores.command_store import CommandStore
from svf.stores.parameter_store import ParameterStore


class _NoSync(SyncProtocol):
    def reset(self) -> None: pass
    def publish_ready(self, model_id: str, t: float) -> None: pass
    def wait_for_ready(self, expected: list[str], timeout: float) -> bool: return True


ModelFactory = Callable[[SyncProtocol, ParameterStore, CommandStore], Equipment]

_TLE1 = "1 25544U 98067A   26001.50000000  .00002182  00000-0  40084-4 0  9995"
_TLE2 = "2 25544  51.6416  87.8613 0006828  93.5613  23.7542 15.49499526431108"


def _all_models() -> list[tuple[str, ModelFactory]]:
    """Return (label, factory) pairs for every SMP-wrapped model."""
    def orbital(s: SyncProtocol, st: ParameterStore, c: CommandStore) -> Equipment:
        return OrbitalEnvironment(_TLE1, _TLE2, sync_protocol=s, store=st,
                                  command_store=c)

    def can_bus(s: SyncProtocol, st: ParameterStore, c: CommandStore) -> Equipment:
        msgs = [
            CanMessage(can_id=0x100, parameter="aocs.rw1.torque_cmd",
                       direction="rx", node_id="rw1"),
            CanMessage(can_id=0x101, parameter="aocs.rw1.speed",
                       direction="tx", node_id="rw1"),
        ]
        return CanBus("can0", messages=msgs, sync_protocol=s, store=st,
                      command_store=c)

    def mil1553(s: SyncProtocol, st: ParameterStore, c: CommandStore) -> Equipment:
        mappings = [
            SubaddressMapping(rt_address=5, subaddress=1,
                              parameter="aocs.rw1.torque_cmd", direction="BC_to_RT"),
            SubaddressMapping(rt_address=5, subaddress=2,
                              parameter="aocs.rw1.speed", direction="RT_to_BC"),
        ]
        return Mil1553Bus("bus1553", rt_count=8, mappings=mappings,
                          sync_protocol=s, store=st, command_store=c)

    def spw(s: SyncProtocol, st: ParameterStore, c: CommandStore) -> Equipment:
        nodes    = [SpwNode(logical_address=0x20, node_id="str1",
                            description="Star tracker")]
        mappings = [RmapMapping(logical_address=0x20, register_address=0x0100,
                                parameter="aocs.str1.quaternion_w",
                                transaction_type="read")]
        return SpwBus("spw0", nodes=nodes, mappings=mappings,
                      sync_protocol=s, store=st, command_store=c)

    return [
        # AOCS sensors
        ("magnetometer",        lambda s, st, c: make_magnetometer(s, st, c)),
        ("gyroscope",           lambda s, st, c: make_gyroscope(s, st, c)),
        ("css",                 lambda s, st, c: make_css(s, st, c)),
        ("star_tracker",        lambda s, st, c: make_star_tracker(s, st, c)),
        ("gps",                 lambda s, st, c: make_gps(s, st, c)),
        # AOCS actuators
        ("reaction_wheel",      lambda s, st, c: make_reaction_wheel(s, st, c)),
        ("magnetorquer",        lambda s, st, c: make_magnetorquer(s, st, c)),
        ("thruster",            lambda s, st, c: make_thruster(s, st, c)),
        # AOCS algorithms
        ("bdot_controller",     lambda s, st, c: make_bdot_controller(s, st, c)),
        # Dynamics
        ("rigid_body_dynamics", lambda s, st, c: make_rigid_body_dynamics(s, st, c)),
        # EPS
        ("battery",             lambda s, st, c: make_battery(s, st, c)),
        ("pcdu",                lambda s, st, c: make_pcdu(s, st, c)),
        ("solar_array",         lambda s, st, c: make_solar_array(s, st, c)),
        # Thermal
        ("thermal",             lambda s, st, c: make_thermal(s, st, c)),
        # TTC
        ("sbt",                 lambda s, st, c: make_sbt(s, st, c)),
        # Environment
        ("orbital_environment", orbital),
        # Bus adapters
        ("can_bus",             can_bus),
        ("mil1553_bus",         mil1553),
        ("spw_bus",             spw),
    ]


_MODELS = _all_models()


class SmpContractsSuite:

    @pytest.mark.requirement("SVF-DEV-186")
    @pytest.mark.parametrize("label,factory", _MODELS,
                             ids=[m[0] for m in _MODELS])
    def test_implements_ismp_model(
        self, label: str, factory: ModelFactory
    ) -> None:
        """Every wrapped model is an instance of ISmpModel."""
        model = factory(_NoSync(), ParameterStore(), CommandStore())
        assert isinstance(model, ISmpModel), (
            f"{label}: expected ISmpModel, got {type(model)}"
        )

    @pytest.mark.requirement("SVF-DEV-186")
    @pytest.mark.parametrize("label,factory", _MODELS,
                             ids=[m[0] for m in _MODELS])
    def test_initial_state_is_created(
        self, label: str, factory: ModelFactory
    ) -> None:
        """State is CREATED before smp_publish() is called."""
        model = factory(_NoSync(), ParameterStore(), CommandStore())
        assert model.smp_state == SmpState.CREATED, (  # type: ignore[union-attr]
            f"{label}: expected CREATED, got {model.smp_state}"  # type: ignore[union-attr]
        )

    @pytest.mark.requirement("SVF-DEV-186")
    @pytest.mark.parametrize("label,factory", _MODELS,
                             ids=[m[0] for m in _MODELS])
    def test_publish_registers_non_empty_field_catalogue(
        self, label: str, factory: ModelFactory
    ) -> None:
        """smp_publish() registers at least one SmpField per model."""
        model = factory(_NoSync(), ParameterStore(), CommandStore())
        model.smp_publish()  # type: ignore[union-attr]
        fields = model.smp_fields  # type: ignore[union-attr]
        assert len(fields) > 0, f"{label}: no fields after smp_publish()"

    @pytest.mark.requirement("SVF-DEV-186")
    @pytest.mark.parametrize("label,factory", _MODELS,
                             ids=[m[0] for m in _MODELS])
    def test_all_fields_are_float64(
        self, label: str, factory: ModelFactory
    ) -> None:
        """Every SmpField exposed by publish has kind='Float64'."""
        model = factory(_NoSync(), ParameterStore(), CommandStore())
        model.smp_publish()  # type: ignore[union-attr]
        bad = [
            f.name for f in model.smp_fields.values()  # type: ignore[union-attr]
            if f.kind != "Float64"
        ]
        assert not bad, f"{label}: non-Float64 fields: {bad}"

    @pytest.mark.requirement("SVF-DEV-186")
    @pytest.mark.parametrize("label,factory", _MODELS,
                             ids=[m[0] for m in _MODELS])
    def test_full_lifecycle_advances_state(
        self, label: str, factory: ModelFactory
    ) -> None:
        """publish -> configure -> connect advances state to CONNECTED."""
        model = factory(_NoSync(), ParameterStore(), CommandStore())
        model.smp_publish()    # type: ignore[union-attr]
        assert model.smp_state == SmpState.PUBLISHING  # type: ignore[union-attr]
        model.smp_configure()  # type: ignore[union-attr]
        assert model.smp_state == SmpState.CONFIGURED  # type: ignore[union-attr]
        model.smp_connect()    # type: ignore[union-attr]
        assert model.smp_state == SmpState.CONNECTED   # type: ignore[union-attr]
