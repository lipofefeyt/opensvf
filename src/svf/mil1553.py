"""
SVF MIL-STD-1553 Bus Adapter
Simulates a MIL-STD-1553B bus with BC/RT model.
Implements: SVF-DEV-038
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from svf.abstractions import SyncProtocol
from svf.bus import Bus, BusFault, FaultType
from svf.equipment import PortDefinition, PortDirection, InterfaceType
from svf.parameter_store import ParameterStore
from svf.command_store import CommandStore

logger = logging.getLogger(__name__)

BROADCAST_RT = 31   # MIL-STD-1553 broadcast RT address
MAX_RT = 30         # Maximum RT address


@dataclass(frozen=True)
class SubaddressMapping:
    """
    Maps a MIL-STD-1553 subaddress to a parameter name.

    Attributes:
        rt_address:     Remote Terminal address (1-30, 31=broadcast)
        subaddress:     Subaddress (1-30)
        parameter:      SRDB canonical parameter name
        direction:      "BC_to_RT" (command) or "RT_to_BC" (telemetry)
        word_count:     Number of 16-bit data words (1-32)
    """
    rt_address: int
    subaddress: int
    parameter: str
    direction: str      # "BC_to_RT" or "RT_to_BC"
    word_count: int = 1

    def __post_init__(self) -> None:
        if not (1 <= self.rt_address <= BROADCAST_RT):
            raise ValueError(
                f"RT address must be 1-31, got {self.rt_address}"
            )
        if not (1 <= self.subaddress <= 30):
            raise ValueError(
                f"Subaddress must be 1-30, got {self.subaddress}"
            )
        if self.direction not in ("BC_to_RT", "RT_to_BC"):
            raise ValueError(
                f"Direction must be BC_to_RT or RT_to_BC, "
                f"got {self.direction}"
            )
        if not (1 <= self.word_count <= 32):
            raise ValueError(
                f"Word count must be 1-32, got {self.word_count}"
            )


class Mil1553Bus(Bus):
    """
    MIL-STD-1553B bus adapter.

    Models a dual-redundant 1553 bus (A/B) with:
    - One Bus Controller (BC) port — connects to OBC
    - Up to 30 Remote Terminal (RT) ports — connect to equipment
    - Subaddress-to-parameter routing
    - Broadcast command support (RT address 31)
    - Automatic bus A/B switchover on BUS_ERROR fault

    Port naming convention:
        bc_in         — BC port (type: MIL1553_BC), receives from OBC
        rt{n}_out     — RT ports (type: MIL1553_RT), connects to equipment

    Subaddress routing:
        BC_to_RT: value read from ParameterStore (OBC output)
                  -> injected into equipment CommandStore
        RT_to_BC: value read from ParameterStore (equipment output)
                  -> written to ParameterStore as telemetry for OBC

    Usage:
        mappings = [
            SubaddressMapping(rt_address=5, subaddress=1,
                              parameter="aocs.rw1.torque_cmd",
                              direction="BC_to_RT"),
            SubaddressMapping(rt_address=5, subaddress=2,
                              parameter="aocs.rw1.speed",
                              direction="RT_to_BC"),
        ]
        bus = Mil1553Bus("platform_1553", rt_count=5,
                         mappings=mappings, ...)
    """

    def __init__(
        self,
        bus_id: str,
        rt_count: int,
        mappings: list[SubaddressMapping],
        sync_protocol: SyncProtocol,
        store: ParameterStore,
        command_store: Optional[CommandStore] = None,
        active_bus: str = "A",
    ) -> None:
        if not (1 <= rt_count <= MAX_RT):
            raise ValueError(
                f"rt_count must be 1-{MAX_RT}, got {rt_count}"
            )
        self._rt_count = rt_count
        self._mappings = list(mappings)
        self._active_bus = active_bus

        # Index mappings for fast lookup
        self._bc_to_rt: dict[tuple[int, int], SubaddressMapping] = {}
        self._rt_to_bc: dict[tuple[int, int], SubaddressMapping] = {}
        for m in mappings:
            key = (m.rt_address, m.subaddress)
            if m.direction == "BC_to_RT":
                self._bc_to_rt[key] = m
            else:
                self._rt_to_bc[key] = m

        super().__init__(
            bus_id=bus_id,
            sync_protocol=sync_protocol,
            store=store,
            command_store=command_store,
        )

    def _declare_ports(self) -> list[PortDefinition]:
        """BC port + one RT port per RT."""
        ports = [
            PortDefinition(
                "bc_in",
                PortDirection.IN,
                interface_type=InterfaceType.MIL1553_BC,
                description="Bus Controller input from OBC",
            )
        ]
        for i in range(1, self._rt_count + 1):
            ports.append(PortDefinition(
                f"rt{i}_out",
                PortDirection.OUT,
                interface_type=InterfaceType.MIL1553_RT,
                description=f"Remote Terminal {i} output",
            ))
        return ports

    def initialise(self, start_time: float = 0.0) -> None:
        logger.info(
            f"[{self._bus_id}] Initialised: "
            f"{self._rt_count} RTs, bus {self._active_bus} active, "
            f"{len(self._mappings)} subaddress mappings"
        )

    def do_step(self, t: float, dt: float) -> None:
        """
        Route messages between BC and RTs according to subaddress map.

        BC_to_RT: read parameter from ParameterStore (OBC wrote it),
                  check for faults, inject into equipment CommandStore
        RT_to_BC: read parameter from ParameterStore (RT wrote it),
                  check for faults, write as OBC telemetry
        """
        
        # Check for BUS_ERROR — switch to redundant bus (once per fault)
        if self.has_fault(FaultType.BUS_ERROR, "all", t):
            if not getattr(self, "_bus_switched", False):
                new_bus = "B" if self._active_bus == "A" else "A"
                logger.warning(
                    f"[{self._bus_id}] BUS_ERROR detected — "
                    f"switching from bus {self._active_bus} to {new_bus}"
                )
                self._active_bus = new_bus
                self._bus_switched = True
                self._store.write(
                    name=f"bus.{self._bus_id}.active_bus",
                    value=1.0 if new_bus == "A" else 2.0,
                    t=t,
                    model_id=self.equipment_id,
                )
        else:
            self._bus_switched = False

        # Process BC_to_RT mappings
        for (rt_addr, sa), mapping in self._bc_to_rt.items():
            targets = self._get_targets(rt_addr)
            for target_rt in targets:
                if self._is_blocked(target_rt, t):
                    self._store.write(
                        name=f"bus.{self._bus_id}.fault.{target_rt}",
                        value=1.0,
                        t=t,
                        model_id=self.equipment_id,
                    )
                    logger.debug(
                        f"[{self._bus_id}] BC->RT{target_rt} "
                        f"SA{sa} BLOCKED (fault active)"
                    )
                    continue

                entry = self._store.read(mapping.parameter)
                if entry is not None and self._command_store is not None:
                    self._command_store.inject(
                        name=mapping.parameter,
                        value=entry.value,
                        t=t,
                        source_id=f"{self._bus_id}.bc_to_rt{target_rt}",
                    )

        # Process RT_to_BC mappings
        for (rt_addr, sa), mapping in self._rt_to_bc.items():
            targets = self._get_targets(rt_addr)
            for target_rt in targets:
                if self._is_blocked(target_rt, t):
                    continue

                entry = self._store.read(mapping.parameter)
                if entry is not None:
                    obc_param = f"obc.rt{target_rt}.{mapping.parameter}"
                    self._store.write(
                        name=obc_param,
                        value=entry.value,
                        t=t,
                        model_id=self.equipment_id,
                    )

    def _get_targets(self, rt_address: int) -> list[int]:
        """Resolve RT address to list of target RT numbers."""
        if rt_address == BROADCAST_RT:
            return list(range(1, self._rt_count + 1))
        return [rt_address]

    def _is_blocked(self, rt_number: int, t: float) -> bool:
        """True if any blocking fault is active for this RT."""
        target = f"rt{rt_number}"
        return (
            self.has_fault(FaultType.NO_RESPONSE, target, t) or
            self.has_fault(FaultType.NO_RESPONSE, "all", t) or
            self.has_fault(FaultType.BUS_ERROR, target, t)
        )

    @property
    def active_bus(self) -> str:
        return self._active_bus
