"""
HIL Adapter  -  plug-in point for the OBC model.

Defines the interface that all OBC implementations must satisfy.
Swapping from software stub to a real hardware-in-the-loop binary
is a single-line change at the composition root (spacecraft.yaml obsw.type).

Implementations:
  - ObcEquipment / ObcStub: rule-based OBSW simulator, no binary required
  - OBCEmulatorAdapter:     connects to the real openobsw binary via pipe or socket

Implements: SVF-DEV-038
"""
from __future__ import annotations

from abc import abstractmethod

from svf.core.equipment import Equipment
from svf.pus.tm import PusTmPacket


class HilAdapter(Equipment):
    """
    Abstract base class for all OBC model implementations.

    Extends Equipment with the connection lifecycle (connect / disconnect /
    is_connected) and the PUS TC/TM routing interface that campaign procedures
    and the TTC model depend on.

    Usage:
        def _find_obc(master: SimulationMaster) -> HilAdapter | None:
            for m in master._models:
                if isinstance(m, HilAdapter):
                    return m
            return None
    """

    @abstractmethod
    def connect(self) -> None:
        """Establish connection to the OBSW. No-op for software stub."""

    @abstractmethod
    def disconnect(self) -> None:
        """Cleanly shut down the OBSW connection."""

    @abstractmethod
    def is_connected(self) -> bool:
        """Return True if the OBSW is reachable and accepting TCs."""

    @abstractmethod
    def receive_tc(self, raw_tc: bytes, t: float = 0.0) -> list[PusTmPacket]:
        """Route a raw PUS TC to the OBSW. Returns any immediate TM responses."""

    @abstractmethod
    def get_tm_queue(self) -> list[PusTmPacket]:
        """Drain and return all queued TM packets generated since the last call."""
