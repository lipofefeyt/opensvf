"""
SmpEquipmentMixin - bridges Equipment ports to the SMP 2.0 ISmpModel interface.

Usage::

    class MagnetometerModel(SmpEquipmentMixin, Equipment):
        def _declare_ports(self) -> list[PortDefinition]:
            return [PortDefinition("aocs.mag.field_x", PortDirection.OUT, unit="T")]

        def do_step(self, t: float, dt: float) -> None:
            self.write_port("aocs.mag.field_x", self._compute_x())

    model = MagnetometerModel(...)
    model.smp_publish()    # derives SmpFields from declared ports
    model.smp_configure()  # no-op; override to read config
    model.smp_connect()    # no-op; WiringLoader handles connections

Implements: SVF-DEV-183
"""

from __future__ import annotations

from typing import cast

from svf.core.equipment import Equipment, PortDirection
from svf.smp.interfaces import ISmpModel, SmpField, SmpState


class SmpEquipmentMixin(ISmpModel):
    """
    Implements ISmpModel by deriving SMP 2.0 fields from Equipment.ports.

    Designed for multiple inheritance: ``class Foo(SmpEquipmentMixin, Equipment)``.
    smp_publish() must be called after Equipment.__init__ so that ports are
    already registered before the SMP field catalogue is built.
    """

    # Instance variables set by smp_publish(); declared here for mypy.
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

    def smp_publish(self) -> None:
        """
        Build the SMP 2.0 field catalogue from the Equipment port registry.

        Each PortDefinition maps to one SmpField(kind="Float64"). Calling
        this before Equipment.__init__ has run will produce an empty catalogue.
        """
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
        self._smp_state = SmpState.PUBLISHING

    def smp_configure(self) -> None:
        """Advance to Configured. Override to apply equipment configuration."""
        self._smp_state = SmpState.CONFIGURED

    def smp_connect(self) -> None:
        """Advance to Connected. WiringLoader handles actual port linkage."""
        self._smp_state = SmpState.CONNECTED
