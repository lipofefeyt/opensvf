"""
SMP 2.0 interface contract tests (M50).

Groups:
  G1  -  ISmpModel / SmpState definitions (SVF-DEV-182)
  G2  -  SmpEquipmentMixin lifecycle (SVF-DEV-183)
"""
from __future__ import annotations

import pytest

from svf.core.abstractions import SyncProtocol
from svf.core.equipment import Equipment, PortDefinition, PortDirection
from svf.smp import ISmpModel, SmpEquipmentMixin, SmpField, SmpState
from svf.stores.parameter_store import ParameterStore


class _NoSync(SyncProtocol):
    def reset(self) -> None: pass
    def publish_ready(self, model_id: str, t: float) -> None: pass
    def wait_for_ready(self, expected: list[str], timeout: float) -> bool: return True


class _SmpModel(SmpEquipmentMixin, Equipment):
    """Minimal SMP-aware equipment with one IN and one OUT port."""

    def __init__(self) -> None:
        super().__init__(
            equipment_id="test.smp_model",
            sync_protocol=_NoSync(),
            store=ParameterStore(),
        )

    def _declare_ports(self) -> list[PortDefinition]:
        return [
            PortDefinition("smp.in_val",  PortDirection.IN,  unit="V"),
            PortDefinition("smp.out_val", PortDirection.OUT, unit="W",
                           description="output power"),
        ]

    def initialise(self, start_time: float = 0.0) -> None:
        pass

    def do_step(self, t: float, dt: float) -> None:
        self.write_port("smp.out_val", self.read_port("smp.in_val") * 2.0)


@pytest.fixture
def model() -> _SmpModel:
    return _SmpModel()


# ── G1: ISmpModel / SmpState ──────────────────────────────────────────────────

class SmpInterfacesSuite:

    @pytest.mark.requirement("SVF-DEV-182")
    def test_smp_state_enum_has_required_values(self) -> None:
        """SmpState exposes the seven SMP 2.0 lifecycle states."""
        required = {
            "CREATED", "PUBLISHING", "CONFIGURED",
            "CONNECTED", "INITIALISED", "EXECUTING", "TERMINATED",
        }
        assert {s.name for s in SmpState} == required

    @pytest.mark.requirement("SVF-DEV-182")
    def test_ismp_model_is_abstract(self) -> None:
        """ISmpModel cannot be instantiated directly."""
        with pytest.raises(TypeError):
            ISmpModel()  # type: ignore[abstract]

    @pytest.mark.requirement("SVF-DEV-182")
    def test_smp_field_is_frozen(self) -> None:
        """SmpField is immutable."""
        f = SmpField(name="x", kind="Float64", direction="Output", unit="T")
        with pytest.raises((AttributeError, TypeError)):
            f.name = "y"  # type: ignore[misc]


# ── G2: SmpEquipmentMixin lifecycle ──────────────────────────────────────────

class SmpMixinSuite:

    @pytest.mark.requirement("SVF-DEV-183")
    def test_initial_state_is_created(self, model: _SmpModel) -> None:
        """State is CREATED before smp_publish() is called."""
        assert model.smp_state == SmpState.CREATED

    @pytest.mark.requirement("SVF-DEV-183")
    def test_fields_empty_before_publish(self, model: _SmpModel) -> None:
        """smp_fields returns empty dict before smp_publish()."""
        assert model.smp_fields == {}

    @pytest.mark.requirement("SVF-DEV-183")
    def test_publish_advances_state(self, model: _SmpModel) -> None:
        """smp_publish() transitions state to PUBLISHING."""
        model.smp_publish()
        assert model.smp_state == SmpState.PUBLISHING

    @pytest.mark.requirement("SVF-DEV-183")
    def test_publish_builds_field_catalogue(self, model: _SmpModel) -> None:
        """smp_publish() generates one SmpField per declared port."""
        model.smp_publish()
        assert set(model.smp_fields.keys()) == {"smp.in_val", "smp.out_val"}

    @pytest.mark.requirement("SVF-DEV-183")
    def test_publish_maps_port_direction_to_input(self, model: _SmpModel) -> None:
        """IN ports map to SmpField direction='Input'."""
        model.smp_publish()
        assert model.smp_fields["smp.in_val"].direction == "Input"

    @pytest.mark.requirement("SVF-DEV-183")
    def test_publish_maps_port_direction_to_output(self, model: _SmpModel) -> None:
        """OUT ports map to SmpField direction='Output'."""
        model.smp_publish()
        assert model.smp_fields["smp.out_val"].direction == "Output"

    @pytest.mark.requirement("SVF-DEV-183")
    def test_publish_preserves_unit(self, model: _SmpModel) -> None:
        """Engineering unit from PortDefinition is carried into SmpField."""
        model.smp_publish()
        assert model.smp_fields["smp.in_val"].unit == "V"

    @pytest.mark.requirement("SVF-DEV-183")
    def test_publish_preserves_description(self, model: _SmpModel) -> None:
        """Description from PortDefinition is carried into SmpField."""
        model.smp_publish()
        assert model.smp_fields["smp.out_val"].description == "output power"

    @pytest.mark.requirement("SVF-DEV-183")
    def test_all_fields_are_float64(self, model: _SmpModel) -> None:
        """All generated SmpFields have kind='Float64'."""
        model.smp_publish()
        assert all(f.kind == "Float64" for f in model.smp_fields.values())

    @pytest.mark.requirement("SVF-DEV-183")
    def test_configure_advances_state(self, model: _SmpModel) -> None:
        """smp_configure() transitions state to CONFIGURED."""
        model.smp_publish()
        model.smp_configure()
        assert model.smp_state == SmpState.CONFIGURED

    @pytest.mark.requirement("SVF-DEV-183")
    def test_connect_advances_state(self, model: _SmpModel) -> None:
        """smp_connect() transitions state to CONNECTED."""
        model.smp_publish()
        model.smp_configure()
        model.smp_connect()
        assert model.smp_state == SmpState.CONNECTED

    @pytest.mark.requirement("SVF-DEV-183")
    def test_smp_mixin_is_ismp_model(self, model: _SmpModel) -> None:
        """SmpEquipmentMixin subclass satisfies the ISmpModel interface."""
        assert isinstance(model, ISmpModel)
