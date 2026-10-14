"""
SmpEquipmentMixin - bridges Equipment ports to the SMP-aligned ISmpModel interface.

Usage::

    class MagnetometerModel(SmpEquipmentMixin, Equipment):
        def _declare_ports(self) -> list[PortDefinition]:
            return [PortDefinition("aocs.mag.field_x", PortDirection.OUT, unit="T")]

        def do_step(self, t: float, dt: float) -> None:
            self.write_port("aocs.mag.field_x", self._compute_x())

    model = MagnetometerModel(...)
    model.smp_publish()     # derives SmpFields from declared ports
    model.smp_configure()   # no-op; override to read config
    model.smp_connect()     # no-op; WiringLoader handles connections
    model.smp_disconnect()  # final state

Every transition is guarded: calling one from the wrong state raises
SmpStateError, as IComponent raises InvalidComponentState.

Implements: SVF-DEV-183, SVF-DEV-202
"""

from __future__ import annotations

from typing import cast

from svf.core.equipment import Equipment, PortDirection
from svf.smp.interfaces import ISmpModel, SmpField, SmpState, SmpStateError


class SmpEquipmentMixin(ISmpModel):
    """
    Implements ISmpModel by deriving SMP fields from Equipment.ports.

    Designed for multiple inheritance: ``class Foo(SmpEquipmentMixin, Equipment)``.
    smp_publish() must be called after Equipment.__init__ so that ports are
    already registered before the field catalogue is built.
    """

    # Instance variables set by the lifecycle methods; declared here for mypy.
    _smp_state: SmpState
    _smp_fields: dict[str, SmpField]

    @property
    def smp_state(self) -> SmpState:
        try:
            return self._smp_state
        except AttributeError:
            return SmpState.CREATED

    @property
    def smp_fields(self) -> dict[str, SmpField]:
        try:
            return self._smp_fields
        except AttributeError:
            return {}

    def _smp_transition(self, name: str, required: SmpState, target: SmpState) -> None:
        if self.smp_state is not required:
            raise SmpStateError(name, self.smp_state, required)
        self._smp_state = target

    def smp_publish(self) -> None:
        """
        Created -> Publishing: build the field catalogue from the port registry.

        Each PortDefinition maps to one SmpField(kind="Float64"). Calling
        this before Equipment.__init__ has run will produce an empty catalogue.
        """
        self._smp_transition("smp_publish", SmpState.CREATED, SmpState.PUBLISHING)
        eq = cast(Equipment, self)
        self._smp_fields = {
            name: SmpField(
                name=name,
                kind="Float64",
                direction="Output" if port.direction == PortDirection.OUT else "Input",
                unit=port.unit,
                description=port.description,
            )
            for name, port in eq.ports.items()
        }

    def smp_configure(self) -> None:
        """Publishing -> Configured. Override to apply equipment configuration."""
        self._smp_transition("smp_configure", SmpState.PUBLISHING, SmpState.CONFIGURED)

    def smp_connect(self) -> None:
        """Configured -> Connected. WiringLoader handles actual port linkage."""
        self._smp_transition("smp_connect", SmpState.CONFIGURED, SmpState.CONNECTED)

    def smp_disconnect(self) -> None:
        """Connected -> Disconnected. Final state; the model is not reusable."""
        self._smp_transition("smp_disconnect", SmpState.CONNECTED, SmpState.DISCONNECTED)
