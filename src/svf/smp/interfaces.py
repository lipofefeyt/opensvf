"""
SMP 2.0 IModel interface contract (ECSS-E-ST-40-07C §4.7).

Defines the five lifecycle states and the three Publication-phase methods
that every SMP 2.0 compliant model must expose. opensvf models implement
this contract via SmpEquipmentMixin rather than directly.

Implements: SVF-DEV-182
"""

from __future__ import annotations

import enum
from abc import ABC, abstractmethod
from dataclasses import dataclass


class SmpState(enum.Enum):
    """SMP 2.0 model lifecycle states (ECSS-E-ST-40-07C §4.5.1)."""
    CREATED     = "Created"
    PUBLISHING  = "Publishing"
    CONFIGURED  = "Configured"
    CONNECTED   = "Connected"
    INITIALISED = "Initialised"
    EXECUTING   = "Executing"
    TERMINATED  = "Terminated"


@dataclass(frozen=True)
class SmpField:
    """
    Typed, directional field exposed during the Publication phase.

    One SmpField is generated per PortDefinition. All opensvf ports carry
    floating-point engineering values, so kind is always "Float64".
    """
    name: str
    kind: str        # SMP primitive type name; always "Float64" in opensvf
    direction: str   # "Input" | "Output"
    unit: str = ""
    description: str = ""


class ISmpModel(ABC):
    """
    SMP 2.0 IModel interface (ECSS-E-ST-40-07C §4.7.1).

    Lifecycle contract - methods must be called in this order before the
    first simulation step::

        model.smp_publish()    # register fields
        model.smp_configure()  # apply configuration
        model.smp_connect()    # link to peer fields
        model.initialise()     # existing ModelAdapter call

    Concrete models gain this interface through SmpEquipmentMixin.
    """

    @property
    @abstractmethod
    def smp_state(self) -> SmpState:
        """Current SMP 2.0 lifecycle state."""
        ...

    @property
    @abstractmethod
    def smp_fields(self) -> dict[str, SmpField]:
        """All fields registered during Publication, keyed by SRDB name."""
        ...

    @abstractmethod
    def smp_publish(self) -> None:
        """Register fields with the simulation environment."""
        ...

    @abstractmethod
    def smp_configure(self) -> None:
        """Apply configuration parameters. No-op unless overridden."""
        ...

    @abstractmethod
    def smp_connect(self) -> None:
        """Link fields to peer models. Wiring is handled by WiringLoader."""
        ...
