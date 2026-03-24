"""
SVF Equipment Abstract Base Class
Defines the standard interface for all spacecraft equipment models.
Extends ModelAdapter so Equipment instances are directly driveable
by SimulationMaster without any adapter wrapping.

Implements: SVF-DEV-004, SVF-DEV-013
"""

from __future__ import annotations

import enum
import logging
from abc import abstractmethod
from dataclasses import dataclass
from typing import Optional, TYPE_CHECKING

from svf.abstractions import ModelAdapter, SyncProtocol
from svf.parameter_store import ParameterStore
from svf.command_store import CommandStore

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class PortDirection(enum.Enum):
    """Direction of an equipment port."""
    IN  = "IN"   # Input — receives values from other equipment or test procedures
    OUT = "OUT"  # Output — produces values read by other equipment or observables


@dataclass(frozen=True)
class PortDefinition:
    """
    Definition of a single equipment port.

    Attributes:
        name:        Port name, unique within the equipment.
                     Convention: subsystem.signal e.g. "bus.lcl1"
        direction:   IN (input) or OUT (output)
        unit:        Engineering unit, empty string for dimensionless
        dtype:       Data type of the port value
        description: Human-readable description
    """
    name: str
    direction: PortDirection
    unit: str = ""
    dtype: str = "float"
    description: str = ""


class Equipment(ModelAdapter):
    """
    Abstract base class for all spacecraft equipment models.

    Extends ModelAdapter so Equipment instances are directly driveable
    by SimulationMaster. Provides a port-based interface for inter-equipment
    data exchange via the WiringMap.

    on_tick() implements the standard ModelAdapter contract:
      1. Read CommandStore for each IN port and receive() into port
      2. Call do_step() — subclass implements physics here
      3. Write each OUT port value to ParameterStore
      4. Call sync_protocol.publish_ready()

    Subclasses must implement:
      - _declare_ports(): return list of PortDefinition
      - initialise(start_time): prepare for simulation
      - do_step(t, dt): advance physics, read IN ports, write OUT ports

    Usage:
        class ReactionWheel(Equipment):
            def _declare_ports(self):
                return [
                    PortDefinition("power_enable", PortDirection.IN),
                    PortDefinition("torque_cmd", PortDirection.IN, unit="Nm"),
                    PortDefinition("speed", PortDirection.OUT, unit="rpm"),
                ]

            def initialise(self, start_time=0.0):
                self._speed = 0.0

            def do_step(self, t, dt):
                if self.read_port("power_enable") > 0.5:
                    self._speed += self.read_port("torque_cmd") * dt * 100
                self.write_port("speed", self._speed)
    """

    def __init__(
        self,
        equipment_id: str,
        sync_protocol: SyncProtocol,
        store: ParameterStore,
        command_store: Optional[CommandStore] = None,
    ) -> None:
        self._equipment_id = equipment_id
        self._sync_protocol = sync_protocol
        self._store = store
        self._command_store = command_store
        self._ports: dict[str, PortDefinition] = {}
        self._port_values: dict[str, float] = {}

        for port in self._declare_ports():
            if port.name in self._ports:
                raise ValueError(
                    f"Equipment '{equipment_id}': "
                    f"duplicate port name '{port.name}'"
                )
            self._ports[port.name] = port
            self._port_values[port.name] = 0.0

        logger.debug(
            f"[{equipment_id}] Registered {len(self._ports)} ports: "
            f"{list(self._ports.keys())}"
        )

    # ── ModelAdapter interface ────────────────────────────────────────────────

    @property
    def model_id(self) -> str:
        """Unique identifier — satisfies ModelAdapter contract."""
        return self._equipment_id

    def on_tick(self, t: float, dt: float) -> None:
        """
        ModelAdapter tick implementation.
        Reads CommandStore into IN ports, calls do_step(),
        writes OUT ports to ParameterStore, acknowledges sync.
        """
        # Step 1: read CommandStore into IN ports
        if self._command_store is not None:
            for name, port in self._ports.items():
                if port.direction == PortDirection.IN:
                    entry = self._command_store.take(name)
                    if entry is not None:
                        self._port_values[name] = entry.value
                        logger.debug(
                            f"[{self._equipment_id}] IN {name} "
                            f"= {entry.value} from {entry.source_id}"
                        )

        # Step 2: advance physics
        self.do_step(t, dt)

        # Step 3: write OUT ports to ParameterStore
        stepped_t = round(t + dt, 9)
        for name, port in self._ports.items():
            if port.direction == PortDirection.OUT:
                self._store.write(
                    name=name,
                    value=self._port_values[name],
                    t=stepped_t,
                    model_id=self._equipment_id,
                )

        # Step 4: acknowledge sync
        self._sync_protocol.publish_ready(
            model_id=self._equipment_id, t=t
        )

    # ── Equipment interface ───────────────────────────────────────────────────

    @property
    def equipment_id(self) -> str:
        """Alias for model_id — equipment-specific terminology."""
        return self._equipment_id

    @property
    def ports(self) -> dict[str, PortDefinition]:
        """All declared ports keyed by port name."""
        return dict(self._ports)

    def in_ports(self) -> list[PortDefinition]:
        """All input ports."""
        return [p for p in self._ports.values()
                if p.direction == PortDirection.IN]

    def out_ports(self) -> list[PortDefinition]:
        """All output ports."""
        return [p for p in self._ports.values()
                if p.direction == PortDirection.OUT]

    @abstractmethod
    def _declare_ports(self) -> list[PortDefinition]:
        """Declare all ports. Called once during __init__."""
        ...

    @abstractmethod
    def do_step(self, t: float, dt: float) -> None:
        """
        Advance the equipment by one timestep.
        Read inputs via read_port(), write outputs via write_port().
        """
        ...

    def teardown(self) -> None:
        """Default teardown — no-op. Override if needed."""
        logger.debug(f"[{self._equipment_id}] Teardown")

    def write_port(self, name: str, value: float) -> None:
        """Write a value to an OUT port."""
        if name not in self._ports:
            raise ValueError(
                f"[{self._equipment_id}] Unknown port '{name}'"
            )
        if self._ports[name].direction != PortDirection.OUT:
            raise ValueError(
                f"[{self._equipment_id}] Cannot write to IN port '{name}'"
            )
        self._port_values[name] = value

    def read_port(self, name: str) -> float:
        """Read the current value of any port."""
        if name not in self._ports:
            raise ValueError(
                f"[{self._equipment_id}] Unknown port '{name}'"
            )
        return self._port_values[name]

    def receive(self, port_name: str, value: float) -> None:
        """
        Inject a value into an IN port.
        Called by SimulationMaster when applying wiring connections.
        """
        if port_name not in self._ports:
            raise ValueError(
                f"[{self._equipment_id}] Unknown port '{port_name}'"
            )
        if self._ports[port_name].direction != PortDirection.IN:
            raise ValueError(
                f"[{self._equipment_id}] Cannot receive into OUT port '{port_name}'"
            )
        self._port_values[port_name] = value

    def __repr__(self) -> str:
        return (
            f"Equipment(id={self._equipment_id!r}, "
            f"in={len(self.in_ports())}, out={len(self.out_ports())})"
        )
