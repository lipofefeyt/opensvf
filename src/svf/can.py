"""
SVF CAN Bus Adapter (ECSS-E-ST-50-15C compliant).

Models a CAN 2.0B bus with:
- Standard (11-bit) and extended (29-bit) identifiers
- ECSS CAN node addressing
- Message routing by CAN identifier
- Error injection: bus-off, error-passive, ACK error

CAN uses message-based broadcast — every node sees every message.
The adapter routes by CAN identifier to the correct parameter.

Port naming convention:
    controller_in   — CAN controller port (OBC)
    node{n}_out     — CAN node ports (equipment)

Message routing:
    TX (controller→nodes): value from ParameterStore → CommandStore
    RX (nodes→controller): value from ParameterStore → OBC telemetry

Implements: SVF-DEV-038
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from svf.abstractions import SyncProtocol
from svf.bus import Bus, BusFault, FaultType
from svf.equipment import PortDefinition, PortDirection
from svf.parameter_store import ParameterStore
from svf.command_store import CommandStore

logger = logging.getLogger(__name__)

MAX_STD_ID = 0x7FF    # 11-bit standard identifier
MAX_EXT_ID = 0x1FFFFFFF  # 29-bit extended identifier


@dataclass(frozen=True)
class CanMessage:
    """
    Maps a CAN message identifier to a parameter.

    Attributes:
        can_id:      CAN message identifier
        extended:    True for 29-bit extended ID, False for 11-bit standard
        parameter:   SRDB canonical parameter name
        direction:   "tx" (controller→nodes) or "rx" (nodes→controller)
        dlc:         Data length code (0-8 bytes)
        node_id:     Target/source node identifier string
    """
    can_id:    int
    parameter: str
    direction: str      # "tx" or "rx"
    node_id:   str
    extended:  bool = False
    dlc:       int = 4

    def __post_init__(self) -> None:
        max_id = MAX_EXT_ID if self.extended else MAX_STD_ID
        if not (0 <= self.can_id <= max_id):
            raise ValueError(
                f"CAN ID 0x{self.can_id:X} out of range for "
                f"{'extended' if self.extended else 'standard'} frame"
            )
        if self.direction not in ("tx", "rx"):
            raise ValueError(
                f"direction must be 'tx' or 'rx', got {self.direction}"
            )
        if not (0 <= self.dlc <= 8):
            raise ValueError(f"DLC must be 0-8, got {self.dlc}")

    @property
    def id_str(self) -> str:
        bits = 29 if self.extended else 11
        return f"0x{self.can_id:0{(bits+3)//4}X}"


class CanBus(Bus):
    """
    CAN bus adapter (ECSS-E-ST-50-15C).

    Models a CAN 2.0B bus with message-ID routing.
    Supports standard and extended frame formats.

    Bus error states modelled:
    - BUS_ERROR fault → bus-off state (no transmission)
    - NO_RESPONSE fault on node → ACK error / error-passive for that node
    - BAD_PARITY fault → message corruption (value not routed)

    Usage:
        messages = [
            CanMessage(can_id=0x100, parameter="aocs.rw1.torque_cmd",
                       direction="tx", node_id="rw1"),
            CanMessage(can_id=0x101, parameter="aocs.rw1.speed",
                       direction="rx", node_id="rw1"),
            CanMessage(can_id=0x200, parameter="eps.pcdu.bus_voltage",
                       direction="rx", node_id="pcdu", extended=True),
        ]
        bus = CanBus("platform_can", messages=messages, ...)
    """

    def __init__(
        self,
        bus_id:        str,
        messages:      list[CanMessage],
        sync_protocol: SyncProtocol,
        store:         ParameterStore,
        command_store: Optional[CommandStore] = None,
    ) -> None:
        self._messages = list(messages)
        self._tx_msgs  = [m for m in messages if m.direction == "tx"]
        self._rx_msgs  = [m for m in messages if m.direction == "rx"]

        # Track bus-off state
        self._bus_off = False

        super().__init__(
            bus_id=bus_id,
            sync_protocol=sync_protocol,
            store=store,
            command_store=command_store,
        )

    def _declare_ports(self) -> list[PortDefinition]:
        """Controller port + one port per unique node."""
        node_ids = sorted({m.node_id for m in self._messages})
        ports = [
            PortDefinition(
                "controller_in",
                PortDirection.IN,
                description="CAN controller (OBC)",
            )
        ]
        for node_id in node_ids:
            ports.append(PortDefinition(
                f"node_{node_id}_out",
                PortDirection.OUT,
                description=f"CAN node: {node_id}",
            ))
        return ports

    def initialise(self, start_time: float = 0.0) -> None:
        node_ids = {m.node_id for m in self._messages}
        logger.info(
            f"[{self._bus_id}] CAN initialised: "
            f"{len(node_ids)} nodes, {len(self._messages)} messages"
        )

    def do_step(self, t: float, dt: float) -> None:
        # Check bus-off state
        if self.has_fault(FaultType.BUS_ERROR, "all", t):
            if not self._bus_off:
                logger.warning(
                    f"[{self._bus_id}] Bus-off state — "
                    f"all CAN transmission suspended"
                )
                self._bus_off = True
            return
        else:
            if self._bus_off:
                logger.info(f"[{self._bus_id}] Bus recovered from bus-off")
                self._bus_off = False

        # TX messages: controller → nodes
        for msg in self._tx_msgs:
            if self._is_node_error(msg.node_id, t):
                logger.debug(
                    f"[{self._bus_id}] TX 0x{msg.can_id:03X} "
                    f"to {msg.node_id} BLOCKED"
                )
                continue
            if self._has_corruption(t):
                logger.warning(
                    f"[{self._bus_id}] TX 0x{msg.can_id:03X} CORRUPTED"
                )
                continue

            entry = self._store.read(msg.parameter)
            if entry is not None and self._command_store is not None:
                self._command_store.inject(
                    name=msg.parameter,
                    value=entry.value,
                    t=t,
                    source_id=f"{self._bus_id}.can_tx.{msg.id_str}",
                )

        # RX messages: nodes → controller
        for msg in self._rx_msgs:
            if self._is_node_error(msg.node_id, t):
                continue
            if self._has_corruption(t):
                continue

            entry = self._store.read(msg.parameter)
            if entry is not None:
                obc_param = (
                    f"can.{self._bus_id}.{msg.node_id}.{msg.parameter}"
                )
                self._store.write(
                    name=obc_param,
                    value=entry.value,
                    t=t,
                    model_id=self.equipment_id,
                )

    def _is_node_error(self, node_id: str, t: float) -> bool:
        """ACK error or error-passive for this node."""
        return (
            self.has_fault(FaultType.NO_RESPONSE, node_id, t) or
            self.has_fault(FaultType.LATE_RESPONSE, node_id, t)
        )

    def _has_corruption(self, t: float) -> bool:
        """Bad parity / CRC error on bus."""
        return self.has_fault(FaultType.BAD_PARITY, "all", t)

    @property
    def bus_off(self) -> bool:
        return self._bus_off
