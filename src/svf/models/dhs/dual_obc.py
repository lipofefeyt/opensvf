"""
Dual-OBC Topology
Primary + secondary HilAdapter running in lockstep.
Implements: SVF-DEV-166, SVF-DEV-167, SVF-DEV-168
"""

from __future__ import annotations

import logging
from typing import Optional

from svf.core.abstractions import SyncProtocol
from svf.core.equipment import PortDefinition
from svf.models.dhs.hil_adapter import HilAdapter
from svf.pus.tm import PusTmPacket
from svf.stores.command_store import CommandStore
from svf.stores.parameter_store import ParameterStore

logger = logging.getLogger(__name__)


class _NoOpSync(SyncProtocol):
    """Silent sync — used to detach inner OBCs from the outer sync protocol."""
    def reset(self) -> None: pass
    def publish_ready(self, model_id: str, t: float) -> None: pass
    def wait_for_ready(self, expected: list[str], timeout: float) -> bool: return True


class DualObcAdapter(HilAdapter):
    """
    Dual-OBC topology: primary and secondary HilAdapters in lockstep.

    Each tick, only the active OBC is driven (``on_tick()``). The passive OBC
    stays warm — it is initialised and torn down with the primary, but does
    not receive sensor data or TCs until it becomes active.

    Auto-failover: if the active OBC's ``is_connected()`` returns False after a
    tick, ``DualObcAdapter`` switches to the other OBC automatically.

    Manual failover (test procedures)::

        dual = ctx.find_model(DualObcAdapter)
        dual.switch_to_secondary()

    Cross-checking TM::

        primary_tm   = dual.get_primary_tm()
        secondary_tm = dual.get_secondary_tm()

    Multi-process note: inner OBCs are detached from the outer
    ``SyncProtocol`` at construction time. Their ``publish_ready()`` calls are
    silenced so they do not interfere with the master's tick coordination.

    Args:
        primary:         HilAdapter for the primary OBC (active by default).
        secondary:       HilAdapter for the secondary (standby) OBC.
        sync_protocol:   SyncProtocol used by SimulationMaster for this adapter.
        store:           Shared ParameterStore.
        command_store:   Shared CommandStore.
        equipment_id:    Equipment ID visible to SimulationMaster (default "obc").
    """

    def __init__(
        self,
        primary: HilAdapter,
        secondary: HilAdapter,
        sync_protocol: SyncProtocol,
        store: ParameterStore,
        command_store: Optional[CommandStore] = None,
        equipment_id: str = "obc",
    ) -> None:
        super().__init__(
            equipment_id=equipment_id,
            sync_protocol=sync_protocol,
            store=store,
            command_store=command_store,
        )
        self._primary = primary
        self._secondary = secondary

        # Detach inner OBCs from the outer sync so their publish_ready() calls
        # don't race with or confuse the master's wait_for_ready().
        _noop: SyncProtocol = _NoOpSync()
        primary._sync_protocol = _noop
        secondary._sync_protocol = _noop

        self._active: HilAdapter = primary
        self._active_id: str = "primary"

    # ── Equipment interface ───────────────────────────────────────────────────

    def _declare_ports(self) -> list[PortDefinition]:
        return []

    def do_step(self, t: float, dt: float) -> None:
        pass  # on_tick() drives everything directly

    def on_tick(self, t: float, dt: float) -> None:
        """Tick the active OBC; auto-failover if it disconnects; publish ready."""
        self._active.on_tick(t, dt)
        if not self._active.is_connected():
            self._auto_failover()
        self._sync_protocol.publish_ready(self.model_id, t)

    def initialise(self, start_time: float = 0.0) -> None:
        self._primary.initialise(start_time)
        self._secondary.initialise(start_time)

    def teardown(self) -> None:
        self._primary.teardown()
        self._secondary.teardown()

    # ── HilAdapter interface ──────────────────────────────────────────────────

    def connect(self) -> None:
        self._primary.connect()
        self._secondary.connect()

    def disconnect(self) -> None:
        self._primary.disconnect()
        self._secondary.disconnect()

    def is_connected(self) -> bool:
        return self._active.is_connected()

    def receive_tc(self, raw_tc: bytes, t: float = 0.0) -> list[PusTmPacket]:
        """Route TC to the active OBC only."""
        return self._active.receive_tc(raw_tc, t)

    def get_tm_queue(self) -> list[PusTmPacket]:
        """Drain TM from the active OBC."""
        return self._active.get_tm_queue()

    # ── Dual-OBC specific ─────────────────────────────────────────────────────

    @property
    def active_id(self) -> str:
        """'primary' or 'secondary'."""
        return self._active_id

    @property
    def primary(self) -> HilAdapter:
        return self._primary

    @property
    def secondary(self) -> HilAdapter:
        return self._secondary

    def switch_to_primary(self) -> None:
        """Manual failover to primary OBC."""
        self._active = self._primary
        self._active_id = "primary"
        logger.info("[DualObc] Switched to primary")

    def switch_to_secondary(self) -> None:
        """Manual failover to secondary OBC."""
        self._active = self._secondary
        self._active_id = "secondary"
        logger.info("[DualObc] Switched to secondary")

    def get_primary_tm(self) -> list[PusTmPacket]:
        """Drain TM from the primary OBC regardless of which is active."""
        return self._primary.get_tm_queue()

    def get_secondary_tm(self) -> list[PusTmPacket]:
        """Drain TM from the secondary OBC regardless of which is active."""
        return self._secondary.get_tm_queue()

    # ── Internal ──────────────────────────────────────────────────────────────

    def _auto_failover(self) -> None:
        if self._active_id == "primary":
            self.switch_to_secondary()
            logger.warning("[DualObc] Primary OBC disconnected — switched to secondary")
        else:
            self.switch_to_primary()
            logger.warning("[DualObc] Secondary OBC disconnected — switched to primary")
