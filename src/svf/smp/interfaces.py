"""
SMP-aligned component lifecycle contract (ECSS-E-ST-40-07C §5.2.3.1).

Mirrors the IComponent lifecycle of the ECSS SMP standard: five component
states (ComponentStateKind, Table 5-2) and the four state transitions
Publish, Configure, Connect and Disconnect. opensvf models implement this
contract via SmpEquipmentMixin rather than directly.

Scope: this is a Python-level alignment with the SMP lifecycle semantics.
It is not the SMP C++ ABI, so opensvf models cannot be loaded by an SMP
simulation environment (SIMSAT, EuroSim, BASILES) as-is.

Implements: SVF-DEV-182, SVF-DEV-202
"""

from __future__ import annotations

import enum
from abc import ABC, abstractmethod
from dataclasses import dataclass

# XML namespace of the generated .smpcat / .smpconf artefacts. Deliberately
# not the ESA SMP namespace: the documents are SMP-style, not SMDL-conformant.
SMP_ALIGNED_NS = "urn:opensvf:smp-aligned:1"


class SmpState(enum.Enum):
    """
    Component lifecycle states (ECSS-E-ST-40-07C Table 5-2, ComponentStateKind).

    Simulator phases (initialising, executing, ...) are not component states
    and are deliberately absent; opensvf runs those through ModelAdapter.
    """
    CREATED      = "Created"
    PUBLISHING   = "Publishing"
    CONFIGURED   = "Configured"
    CONNECTED    = "Connected"
    DISCONNECTED = "Disconnected"


class SmpStateError(RuntimeError):
    """
    Lifecycle transition requested from the wrong state.

    Python counterpart of the SMP InvalidComponentState exception.
    """

    def __init__(self, transition: str, actual: SmpState, required: SmpState) -> None:
        super().__init__(
            f"{transition}() requires state {required.value}, "
            f"component is {actual.value}"
        )
        self.transition = transition
        self.actual = actual
        self.required = required


@dataclass(frozen=True)
class SmpField:
    """
    Typed, directional field exposed during the Publishing state.

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
    SMP-aligned component interface (ECSS-E-ST-40-07C §5.2.3.1).

    Lifecycle contract - each transition raises SmpStateError unless the
    component is in the state shown on its left::

        Created     --smp_publish()-->    Publishing
        Publishing  --smp_configure()-->  Configured
        Configured  --smp_connect()-->    Connected
        Connected   --smp_disconnect()--> Disconnected

    model.initialise() (ModelAdapter) runs once the model is Connected.
    Concrete models gain this interface through SmpEquipmentMixin.
    """

    @property
    @abstractmethod
    def smp_state(self) -> SmpState:
        """Current component lifecycle state."""
        ...

    @property
    @abstractmethod
    def smp_fields(self) -> dict[str, SmpField]:
        """All fields registered during Publishing, keyed by SRDB name."""
        ...

    @abstractmethod
    def smp_publish(self) -> None:
        """Created -> Publishing: register fields."""
        ...

    @abstractmethod
    def smp_configure(self) -> None:
        """Publishing -> Configured: apply configuration."""
        ...

    @abstractmethod
    def smp_connect(self) -> None:
        """Configured -> Connected: link to the simulator and peer fields."""
        ...

    @abstractmethod
    def smp_disconnect(self) -> None:
        """Connected -> Disconnected: release simulator references (final)."""
        ...
