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

    Subclass this to implement a sensor, actuator, bus adapter, or any
    other spacecraft component. Each Equipment instance declares a set of
    typed ports and implements ``do_step()`` to advance its physics by one
    simulation timestep.

    **Port contract:**

    - Declare all ports in ``_declare_ports()``. Duplicate port names raise
      ``ValueError`` at construction time.
    - OUT ports are written by the model in ``do_step()`` via ``write_port()``.
      Their values are mirrored to ``ParameterStore`` after each tick so test
      procedures can read them via ``ctx.assert_parameter()``.
    - IN ports receive values from other equipment via the ``WiringMap``, or
      from test procedures via ``CommandStore`` injection (``ctx.inject()``).

    **Tick lifecycle** (driven by ``SimulationMaster`` each timestep)::

        CommandStore → receive IN ports
        do_step(t, dt)           ← subclass physics here
        write OUT ports → ParameterStore
        sync_protocol.publish_ready()

    **Fault injection:** Attach an ``EquipmentFaultEngine`` via
    ``attach_fault_engine()`` to intercept port reads/writes and apply
    stuck/noise/bias/scale/fail faults without modifying the model code.

    Example::

        class Magnetometer(Equipment):
            def _declare_ports(self) -> list[PortDefinition]:
                return [
                    PortDefinition("aocs.mag.field_x", PortDirection.OUT, unit="T"),
                    PortDefinition("aocs.mag.field_y", PortDirection.OUT, unit="T"),
                    PortDefinition("aocs.mag.field_z", PortDirection.OUT, unit="T"),
                    PortDefinition("aocs.mag.status",  PortDirection.OUT),
                ]

            def do_step(self, t: float, dt: float) -> None:
                b = self._compute_field()
                self.write_port("aocs.mag.field_x", b.x)
                self.write_port("aocs.mag.field_y", b.y)
                self.write_port("aocs.mag.field_z", b.z)
                self.write_port("aocs.mag.status", 1.0)

    Implements: SVF-DEV-004, SVF-DEV-013, SVF-DEV-038
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
        """
        Declare all ports for this equipment. Called once during ``__init__``.

        Override to return the complete list of ``PortDefinition`` objects.
        Duplicate port names raise ``ValueError``. Ports cannot be added after
        construction.

        Returns:
            List of ``PortDefinition`` objects for this equipment.
        """
        ...

    @abstractmethod
    def do_step(self, t: float, dt: float) -> None:
        """
        Advance the equipment by one simulation timestep.

        Primary physics method — implement sensor noise, actuator dynamics,
        bus routing, or any time-varying behaviour here. Read IN ports with
        ``read_port()`` and write OUT ports with ``write_port()``.

        Args:
            t:  Current simulation time in seconds.
            dt: Timestep duration in seconds.
        """
        ...

    def teardown(self) -> None:
        """
        Clean up resources. Called by ``SimulationMaster`` after simulation ends.

        Override to close file handles, stop threads, or release hardware.
        Default is a no-op.
        """
        logger.debug(f"[{self._equipment_id}] Teardown")

    def write_port(self, name: str, value: float) -> None:
        """
        Write a value to an OUT port.

        Call from within ``do_step()``. The value is mirrored to
        ``ParameterStore`` so ``ctx.assert_parameter()`` sees it immediately.
        If a fault engine is attached, the fault transform is applied first.

        Args:
            name:  Port name. Must be ``PortDirection.OUT``.
            value: New value in engineering units.

        Raises:
            ValueError: If port is unknown or not an OUT port.
        """
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
        """
        Attach an ``EquipmentFaultEngine`` to intercept port reads/writes.

        Once attached, active faults are applied transparently in
        ``read_port()`` and ``write_port()``. The model's ``do_step()``
        code is unaware. Faults are injected via ``ctx.inject_equipment_fault()``.

        Args:
            engine: Fault engine to attach.
        """
        self._fault_engine = engine

    def read_port(self, name: str) -> float:
        """
        Read the current value of any port (IN or OUT).

        If a fault engine is attached and the port has an active read fault,
        the fault transform is applied to the returned value.

        Args:
            name: Declared port name.

        Returns:
            Current port value in engineering units.

        Raises:
            ValueError: If the port is unknown.
        """
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

        Called by ``SimulationMaster`` when propagating wiring connections.
        Test procedures should use ``ctx.inject()`` instead.

        Args:
            port_name: Must be ``PortDirection.IN``.
            value:     Value in engineering units.

        Raises:
            ValueError: If port is unknown or not an IN port.
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
