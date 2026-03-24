"""
SVF Equipment Abstract Base Class
Defines the standard interface for all spacecraft equipment models.
Every equipment model inherits from Equipment and implements its ports.

Implements: SVF-DEV-004
"""

from __future__ import annotations

import enum
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


class PortDirection(enum.Enum):
    """Direction of an equipment port."""
    IN  = "IN"   # Input — receives commands/values from other equipment
    OUT = "OUT"  # Output — produces values read by other equipment


@dataclass(frozen=True)
class PortDefinition:
    """
    Definition of a single equipment port.

    Attributes:
        name:      Port name, unique within the equipment.
                   Convention: subsystem.signal e.g. "bus.lcl1", "power_enable"
        direction: IN (input) or OUT (output)
        unit:      Engineering unit, empty string for dimensionless
        dtype:     Data type of the port value
        description: Human-readable description
    """
    name: str
    direction: PortDirection
    unit: str = ""
    dtype: str = "float"
    description: str = ""


class Equipment(ABC):
    """
    Abstract base class for all spacecraft equipment models.

    Every equipment model inherits from Equipment and:
      - Declares its ports via _declare_ports()
      - Implements initialise(), do_step()
      - Uses write_port() and read_port() for inter-equipment data exchange

    The SimulationMaster drives Equipment instances via the standard
    lifecycle: initialise() once, then do_step() on every tick.
    Inter-equipment connections are applied by the master between ticks
    via write_port() calls according to the wiring map.

    Usage:
        class MyEquipment(Equipment):
            def _declare_ports(self) -> list[PortDefinition]:
                return [
                    PortDefinition("power_enable", PortDirection.IN),
                    PortDefinition("speed", PortDirection.OUT, unit="rpm"),
                ]

            def initialise(self, start_time: float = 0.0) -> None:
                self._speed = 0.0

            def do_step(self, t: float, dt: float) -> None:
                enabled = self.read_port("power_enable")
                if enabled and enabled > 0.5:
                    self._speed += 10.0 * dt
                self.write_port("speed", self._speed)
    """

    def __init__(self, equipment_id: str) -> None:
        self._equipment_id = equipment_id
        self._ports: dict[str, PortDefinition] = {}
        self._port_values: dict[str, float] = {}

        # Register all declared ports
        for port in self._declare_ports():
            if port.name in self._ports:
                raise ValueError(
                    f"Equipment '{equipment_id}': duplicate port name '{port.name}'"
                )
            self._ports[port.name] = port
            self._port_values[port.name] = 0.0

        logger.debug(
            f"[{equipment_id}] Registered {len(self._ports)} ports: "
            f"{list(self._ports.keys())}"
        )

    @property
    def equipment_id(self) -> str:
        """Unique identifier for this equipment instance."""
        return self._equipment_id

    @property
    def ports(self) -> dict[str, PortDefinition]:
        """All declared ports keyed by port name."""
        return dict(self._ports)

    def in_ports(self) -> list[PortDefinition]:
        """All input ports."""
        return [p for p in self._ports.values() if p.direction == PortDirection.IN]

    def out_ports(self) -> list[PortDefinition]:
        """All output ports."""
        return [p for p in self._ports.values() if p.direction == PortDirection.OUT]

    @abstractmethod
    def _declare_ports(self) -> list[PortDefinition]:
        """
        Declare all ports for this equipment.
        Called once during __init__ before initialise().
        """
        ...

    @abstractmethod
    def initialise(self, start_time: float = 0.0) -> None:
        """
        Prepare the equipment for simulation.
        Called once before the first tick.
        """
        ...

    @abstractmethod
    def do_step(self, t: float, dt: float) -> None:
        """
        Advance the equipment by one timestep.
        Read inputs via read_port(), write outputs via write_port().

        Args:
            t:  Current simulation time in seconds.
            dt: Timestep size in seconds.
        """
        ...

    def teardown(self) -> None:
        """
        Clean up equipment resources.
        Default implementation is a no-op. Override if needed.
        """
        logger.debug(f"[{self._equipment_id}] Teardown")

    def write_port(self, name: str, value: float) -> None:
        """
        Write a value to an output port.
        Raises ValueError if port does not exist or is not an OUT port.

        Args:
            name:  Port name
            value: Value to write
        """
        if name not in self._ports:
            raise ValueError(
                f"[{self._equipment_id}] Unknown port '{name}'"
            )
        if self._ports[name].direction != PortDirection.OUT:
            raise ValueError(
                f"[{self._equipment_id}] Cannot write to IN port '{name}'"
            )
        self._port_values[name] = value
        logger.debug(f"[{self._equipment_id}] {name} = {value}")

    def read_port(self, name: str) -> float:
        """
        Read the current value of a port.
        Raises ValueError if port does not exist.

        Args:
            name: Port name

        Returns:
            Current port value. Defaults to 0.0 until written.
        """
        if name not in self._ports:
            raise ValueError(
                f"[{self._equipment_id}] Unknown port '{name}'"
            )
        return self._port_values[name]

    def receive(self, port_name: str, value: float) -> None:
        """
        Receive an externally-driven value into an IN port.
        Called by the SimulationMaster when applying wiring connections.
        Raises ValueError if port is not an IN port.

        Args:
            port_name: Target IN port name
            value:     Value to inject
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
        logger.debug(
            f"[{self._equipment_id}] Received {port_name} = {value}"
        )

    def __repr__(self) -> str:
        in_count = len(self.in_ports())
        out_count = len(self.out_ports())
        return (
            f"Equipment(id={self._equipment_id!r}, "
            f"in={in_count}, out={out_count})"
        )
