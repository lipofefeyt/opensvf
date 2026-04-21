"""
SVF Bus Abstract Base Class
A Bus is an Equipment with typed ports on both sides and
built-in fault injection support for FDIR test procedures.
Implements: SVF-DEV-038
"""

from __future__ import annotations

import enum
import logging
from abc import abstractmethod
from dataclasses import dataclass
from typing import Optional

from svf.core.abstractions import SyncProtocol
from svf.core.equipment import Equipment, PortDefinition
from svf.stores.parameter_store import ParameterStore
from svf.stores.command_store import CommandStore

logger = logging.getLogger(__name__)


class FaultType(enum.Enum):
    """
    Bus-level fault types for FDIR testing.

    These are injected at the bus adapter level — the Equipment
    model never sees them. The OBC FDIR sees a bus-level anomaly.
    """
    NO_RESPONSE      = "no_response"    # RT does not respond
    LATE_RESPONSE    = "late_response"  # RT responds after timeout window
    BAD_PARITY       = "bad_parity"     # Corrupted message
    WRONG_WORD_COUNT = "wrong_word_count"  # Protocol violation
    BUS_ERROR        = "bus_error"      # Physical bus failure


@dataclass(frozen=True)
class BusFault:
    """
    A bus-level fault for FDIR test injection.

    Attributes:
        fault_type:   Type of fault to inject
        target:       equipment_id to affect, or 'all' for broadcast
        duration_s:   How long the fault lasts in simulation seconds.
                      0.0 means permanent until explicitly cleared.
        injected_at:  Simulation time when fault was injected
    """
    fault_type: FaultType
    target: str
    duration_s: float
    injected_at: float

    def is_expired(self, current_t: float) -> bool:
        """True if this fault has expired at the given simulation time."""
        if self.duration_s <= 0.0:
            return False
        return current_t >= self.injected_at + self.duration_s

    def affects(self, equipment_id: str) -> bool:
        """True if this fault affects the given equipment."""
        return self.target == "all" or self.target == equipment_id


class Bus(Equipment):
    """
    Abstract base class for spacecraft bus adapters.

    A Bus is an Equipment with:
    - Typed ports on both sides (controller side and node side)
    - Built-in fault injection for FDIR test procedures
    - Automatic fault expiry based on simulation time

    Subclasses implement specific bus protocols (1553, SpW, CAN etc.)
    by overriding _declare_ports() and do_step().

    Fault injection pattern in test procedures:
        # Via svf_command_schedule — fault at t=10s, 3s duration
        @pytest.mark.svf_command_schedule([
            (10.0, "bus.platform_1553.fault.rw1.no_response", 3.0),
        ])

        # Or directly via CommandStore
        cmd_store.inject("bus.platform_1553.fault.rw1.no_response", 3.0)
    """

    def __init__(
        self,
        bus_id: str,
        sync_protocol: SyncProtocol,
        store: ParameterStore,
        command_store: Optional[CommandStore] = None,
    ) -> None:
        self._bus_id = bus_id
        self._faults: list[BusFault] = []
        super().__init__(
            equipment_id=f"bus.{bus_id}",
            sync_protocol=sync_protocol,
            store=store,
            command_store=command_store,
        )

    @property
    def bus_id(self) -> str:
        return self._bus_id

    def inject_fault(self, fault: BusFault) -> None:
        """
        Inject a bus fault.
        Replaces any existing fault of the same type targeting the same equipment.
        """
        self._faults = [
            f for f in self._faults
            if not (f.fault_type == fault.fault_type
                    and f.target == fault.target)
        ]
        self._faults.append(fault)
        logger.warning(
            f"[{self._bus_id}] Fault injected: "
            f"{fault.fault_type.value} on '{fault.target}' "
            f"for {fault.duration_s}s"
        )

    def clear_faults(self, target: Optional[str] = None) -> None:
        """
        Clear all faults, or only faults targeting a specific equipment.
        """
        if target is None:
            self._faults.clear()
            logger.info(f"[{self._bus_id}] All faults cleared")
        else:
            self._faults = [f for f in self._faults if f.target != target]
            logger.info(f"[{self._bus_id}] Faults cleared for '{target}'")

    def active_faults(self, t: float) -> list[BusFault]:
        """Active (non-expired) faults at simulation time t."""
        return [f for f in self._faults if not f.is_expired(t)]

    def has_fault(
        self,
        fault_type: FaultType,
        target: str,
        t: float,
    ) -> bool:
        """True if a specific fault is active for the given target at time t."""
        return any(
            f.fault_type == fault_type
            and f.affects(target)
            and not f.is_expired(t)
            for f in self._faults
        )

    def _expire_faults(self, t: float) -> None:
        """Remove expired faults — called at the start of each tick."""
        expired = [f for f in self._faults if f.is_expired(t)]
        for f in expired:
            self._faults.remove(f)
            logger.info(
                f"[{self._bus_id}] Fault expired: "
                f"{f.fault_type.value} on '{f.target}'"
            )

    def _process_fault_commands(self, t: float) -> None:
        """
        Read fault injection commands from CommandStore.

        Command naming convention:
            bus.{bus_id}.fault.{target}.{fault_type}
            e.g. bus.platform_1553.fault.rw1.no_response

        Value = duration in seconds (0.0 = permanent, -1.0 = clear)
        """
        if self._command_store is None:
            return

        prefix = f"bus.{self._bus_id}.fault."

        # Scan all pending CommandStore entries for matching keys
        for name in list(self._command_store.pending()):
            if not name.startswith(prefix):
                continue

            entry = self._command_store.take(name)
            if entry is None:
                continue

            # Parse: bus.{bus_id}.fault.{target}.{fault_type_or_clear}
            remainder = name[len(prefix):]
            parts = remainder.rsplit(".", 1)
            if len(parts) != 2:
                logger.warning(
                    f"[{self._bus_id}] Unrecognised fault command: {name}"
                )
                continue

            target, action = parts[0], parts[1]

            if action == "clear":
                if target == "all":
                    self.clear_faults()
                else:
                    self.clear_faults(target)
                continue

            try:
                fault_type = FaultType(action)
            except ValueError:
                logger.warning(
                    f"[{self._bus_id}] Unknown fault type: {action}"
                )
                continue

            if entry.value < 0:
                self.clear_faults(target)
            else:
                self.inject_fault(BusFault(
                    fault_type=fault_type,
                    target=target,
                    duration_s=float(entry.value),
                    injected_at=t,
                ))

    def on_tick(self, t: float, dt: float) -> None:
        """
        Extended on_tick: expire faults, process fault commands,
        then standard Equipment tick.
        """
        self._expire_faults(t)
        self._process_fault_commands(t)
        super().on_tick(t, dt)
