"""
SVF Equipment Abstract Base Class
Defines the standard interface for all spacecraft equipment models.
Extends ModelAdapter so Equipment instances are directly driveable
by SimulationMaster without any adapter wrapping.

Implements: SVF-DEV-004, SVF-DEV-013, SVF-DEV-038
"""

from __future__ import annotations
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from svf.core.equipment_fault import EquipmentFaultEngine

import enum
import logging
from abc import abstractmethod
from dataclasses import dataclass
from typing import Optional, TYPE_CHECKING

from svf.core.abstractions import ModelAdapter, SyncProtocol
from svf.stores.parameter_store import ParameterStore
from svf.stores.command_store import CommandStore

logger = logging.getLogger(__name__)


class PortDirection(enum.Enum):
    """Direction of an equipment port."""
    IN  = "IN"   # Input — receives values from other equipment or test procedures
    OUT = "OUT"  # Output — produces values read by other equipment or observables


class InterfaceType(enum.Enum):
    """
    Physical or logical interface type of an equipment port.

    FLOAT is the default — a plain engineering value with no bus semantics.
    Bus interface types enforce compatibility checking in WiringLoader:
    only ports with matching interface types can be connected.

    This mirrors how spacecraft ICDs work — an interface type defines
    what can connect to what before any wiring is defined.
    """
    FLOAT       = "float"        # Default — plain engineering value
    MIL1553_BC  = "mil1553_bc"   # MIL-STD-1553 Bus Controller
    MIL1553_RT  = "mil1553_rt"   # MIL-STD-1553 Remote Terminal
    SPACEWIRE   = "spacewire"    # SpaceWire node
    CAN         = "can"          # CAN node
    UART        = "uart"         # UART
    ANALOG      = "analog"       # Analog signal
    DIGITAL     = "digital"      # Digital signal (0/1)


@dataclass(frozen=True)
class PortDefinition:
    """
    Definition of a single equipment port.

    Attributes:
        name:           Port name, unique within the equipment.
                        Convention: subsystem.signal e.g. "bus.lcl1"
        direction:      IN (input) or OUT (output)
        interface_type: Physical/logical interface type (default: FLOAT)
        unit:           Engineering unit, empty string for dimensionless
        description:    Human-readable description
    """
    name: str
    direction: PortDirection
    interface_type: InterfaceType = InterfaceType.FLOAT
    unit: str = ""
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
        self._fault_engine: Optional["EquipmentFaultEngine"] = None
        self._fault_t: float = 0.0

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
        return self._equipment_id

    def on_tick(self, t: float, dt: float) -> None:
        """
        ModelAdapter tick implementation.
        Reads CommandStore into IN ports, calls do_step(),
        writes OUT ports to ParameterStore, acknowledges sync.
        """
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

        self.do_step(t, dt)

        stepped_t = round(t + dt, 9)
        for name, port in self._ports.items():
            if port.direction == PortDirection.OUT:
                self._store.write(
                    name=name,
                    value=self._port_values[name],
                    t=stepped_t,
                    model_id=self._equipment_id,
                )

        self._sync_protocol.publish_ready(
            model_id=self._equipment_id, t=t
        )

    # ── Equipment interface ───────────────────────────────────────────────────

    @property
    def equipment_id(self) -> str:
        return self._equipment_id

    @property
    def ports(self) -> dict[str, PortDefinition]:
        return dict(self._ports)

    def in_ports(self) -> list[PortDefinition]:
        return [p for p in self._ports.values()
                if p.direction == PortDirection.IN]

    def out_ports(self) -> list[PortDefinition]:
        return [p for p in self._ports.values()
                if p.direction == PortDirection.OUT]

    def ports_by_interface(
        self, interface_type: InterfaceType
    ) -> list[PortDefinition]:
        """All ports with the given interface type."""
        return [
            p for p in self._ports.values()
            if p.interface_type == interface_type
        ]

    @abstractmethod
    def _declare_ports(self) -> list[PortDefinition]:
        """Declare all ports. Called once during __init__."""
        ...

    @abstractmethod
    def do_step(self, t: float, dt: float) -> None:
        """Advance the equipment by one timestep."""
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
        if self._fault_engine is not None:
            value = self._fault_engine.apply_write(name, value, self._fault_t)
        self._port_values[name] = value
        # Mirror OUT port values to ParameterStore for procedure assertions
        if self._store is not None:
            self._store.write(
                name=name,
                value=value,
                t=self._fault_t,
                model_id=self._equipment_id,
            )

    def attach_fault_engine(self, engine: "EquipmentFaultEngine") -> None:
        """Attach a fault engine to intercept read/write port calls."""
        self._fault_engine = engine

    def read_port(self, name: str) -> float:
        """Read the current value of any port."""
        if name not in self._ports:
            raise ValueError(
                f"[{self._equipment_id}] Unknown port '{name}'"
            )
        raw = self._port_values[name]
        if self._fault_engine is not None:
            return self._fault_engine.apply_read(name, raw, self._fault_t)
        return raw

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
