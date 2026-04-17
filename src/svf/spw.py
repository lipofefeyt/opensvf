"""
SVF SpaceWire Bus Adapter with RMAP support.

Models a SpaceWire network with:
- One initiator port (connects to OBC/instrument)
- Up to N target node ports
- RMAP read/write transaction routing by logical address
- Error injection: link error, invalid address, RMAP error codes

SpaceWire uses logical addressing — each node has a unique 8-bit
logical address. RMAP transactions are routed by the router to
the correct target node.

Port naming convention:
    initiator_in    — initiator port (OBC/instrument)
    node{n}_out     — target node ports

RMAP transaction routing:
    WRITE: value read from CommandStore → injected to target node
    READ:  value read from ParameterStore → written back to initiator

Implements: SVF-DEV-038
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from svf.abstractions import SyncProtocol
from svf.bus import Bus, BusFault, FaultType
from svf.equipment import PortDefinition, PortDirection, InterfaceType
from svf.parameter_store import ParameterStore
from svf.command_store import CommandStore

logger = logging.getLogger(__name__)

MAX_LOGICAL_ADDRESS = 254   # 0xFE — 0xFF reserved
MIN_LOGICAL_ADDRESS = 32    # 0x00-0x1F reserved by SpW standard


@dataclass(frozen=True)
class RmapMapping:
    """
    Maps a SpaceWire RMAP transaction to a parameter.

    Attributes:
        logical_address:  Target node logical address (32-254)
        register_address: RMAP register/memory address
        parameter:        SRDB canonical parameter name
        transaction_type: "write" (initiator→node) or "read" (node→initiator)
        data_length:      Data length in bytes
    """
    logical_address:  int
    register_address: int
    parameter:        str
    transaction_type: str   # "write" or "read"
    data_length:      int = 4

    def __post_init__(self) -> None:
        if not (MIN_LOGICAL_ADDRESS <= self.logical_address
                <= MAX_LOGICAL_ADDRESS):
            raise ValueError(
                f"Logical address must be {MIN_LOGICAL_ADDRESS}-"
                f"{MAX_LOGICAL_ADDRESS}, got {self.logical_address}"
            )
        if self.transaction_type not in ("write", "read"):
            raise ValueError(
                f"transaction_type must be 'write' or 'read', "
                f"got {self.transaction_type}"
            )
        if self.data_length not in (1, 2, 4, 8):
            raise ValueError(
                f"data_length must be 1, 2, 4, or 8, "
                f"got {self.data_length}"
            )


@dataclass
class SpwNode:
    """A SpaceWire target node in the network."""
    logical_address: int
    node_id:         str
    description:     str = ""


class SpwBus(Bus):
    """
    SpaceWire bus adapter with RMAP transaction routing.

    Models a SpaceWire network router with logical address routing.
    Supports RMAP write (initiator→node) and read (node→initiator).

    Usage:
        nodes = [
            SpwNode(logical_address=0x20, node_id="str1",
                    description="Star tracker"),
            SpwNode(logical_address=0x21, node_id="payload_mem",
                    description="Payload mass memory"),
        ]
        mappings = [
            RmapMapping(logical_address=0x20, register_address=0x0100,
                        parameter="aocs.str1.quaternion_w",
                        transaction_type="read"),
            RmapMapping(logical_address=0x21, register_address=0x0000,
                        parameter="payload.mem.write_ptr",
                        transaction_type="write"),
        ]
        bus = SpwBus("platform_spw", nodes=nodes, mappings=mappings, ...)
    """

    def __init__(
        self,
        bus_id:         str,
        nodes:          list[SpwNode],
        mappings:       list[RmapMapping],
        sync_protocol:  SyncProtocol,
        store:          ParameterStore,
        command_store:  Optional[CommandStore] = None,
    ) -> None:
        self._nodes    = {n.logical_address: n for n in nodes}
        self._mappings = list(mappings)

        # Index by (logical_address, register_address)
        self._writes: dict[tuple[int, int], RmapMapping] = {}
        self._reads:  dict[tuple[int, int], RmapMapping] = {}
        for m in mappings:
            key = (m.logical_address, m.register_address)
            if m.transaction_type == "write":
                self._writes[key] = m
            else:
                self._reads[key] = m

        super().__init__(
            bus_id=bus_id,
            sync_protocol=sync_protocol,
            store=store,
            command_store=command_store,
        )

    def _declare_ports(self) -> list[PortDefinition]:
        ports = [
            PortDefinition(
                "initiator_in",
                PortDirection.IN,
                description="SpaceWire initiator (OBC/instrument)",
            )
        ]
        for addr, node in sorted(self._nodes.items()):
            ports.append(PortDefinition(
                f"node_{node.node_id}_out",
                PortDirection.OUT,
                description=(
                    f"SpW node LA=0x{addr:02X}: {node.description}"
                ),
            ))
        return ports

    def initialise(self, start_time: float = 0.0) -> None:
        logger.info(
            f"[{self._bus_id}] SpaceWire initialised: "
            f"{len(self._nodes)} nodes, {len(self._mappings)} RMAP mappings"
        )
        for addr, node in sorted(self._nodes.items()):
            logger.info(
                f"[{self._bus_id}]   LA=0x{addr:02X} → {node.node_id}"
            )

    def do_step(self, t: float, dt: float) -> None:
        """Route RMAP transactions for this tick."""

        # RMAP WRITE: initiator → node (command flow)
        for (la, reg), mapping in self._writes.items():
            node = self._nodes.get(la)
            if node is None:
                continue
            if self._is_link_error(node.node_id, t):
                self._report_link_error(node.node_id, t)
                continue
            if self._is_invalid_address(node.node_id, t):
                logger.warning(
                    f"[{self._bus_id}] RMAP write: invalid address "
                    f"LA=0x{la:02X} reg=0x{reg:04X}"
                )
                continue

            entry = self._store.read(mapping.parameter)
            if entry is not None and self._command_store is not None:
                self._command_store.inject(
                    name=mapping.parameter,
                    value=entry.value,
                    t=t,
                    source_id=f"{self._bus_id}.rmap_write.{node.node_id}",
                )

        # RMAP READ: node → initiator (telemetry flow)
        for (la, reg), mapping in self._reads.items():
            node = self._nodes.get(la)
            if node is None:
                continue
            if self._is_link_error(node.node_id, t):
                continue

            entry = self._store.read(mapping.parameter)
            if entry is not None:
                obc_param = (
                    f"spw.{self._bus_id}.{node.node_id}.{mapping.parameter}"
                )
                self._store.write(
                    name=obc_param,
                    value=entry.value,
                    t=t,
                    model_id=self.equipment_id,
                )

    def _is_link_error(self, node_id: str, t: float) -> bool:
        return (
            self.has_fault(FaultType.BUS_ERROR, node_id, t) or
            self.has_fault(FaultType.BUS_ERROR, "all", t)
        )

    def _is_invalid_address(self, node_id: str, t: float) -> bool:
        return self.has_fault(FaultType.NO_RESPONSE, node_id, t)

    def _report_link_error(self, node_id: str, t: float) -> None:
        logger.warning(
            f"[{self._bus_id}] Link error to node '{node_id}' at t={t:.2f}s"
        )
        if self._store is not None:
            self._store.write(
                name=f"spw.{self._bus_id}.{node_id}.link_error",
                value=1.0,
                t=t,
                model_id=self.equipment_id,
            )

    @property
    def nodes(self) -> dict[int, SpwNode]:
        return dict(self._nodes)
