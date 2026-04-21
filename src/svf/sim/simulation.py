"""
SVF Simulation Master
Orchestrates simulation execution via dependency-injected abstractions.
Depends only on TickSource, SyncProtocol, and ModelAdapter interfaces.
The master drives models and waits for sync — it never speaks for models.
Implements: SVF-DEV-016
"""

from __future__ import annotations

import logging
from typing import Optional

from svf.core.abstractions import TickSource, SyncProtocol, ModelAdapter
from svf.config.wiring import WiringMap
from svf.sim.replay import SeedManager
from svf.stores.command_store import CommandStore
from svf.stores.parameter_store import ParameterStore

logger = logging.getLogger(__name__)


class SimulationError(Exception):
    """Raised when the simulation master encounters a non-recoverable error."""
    pass


class SimulationMaster:
    """
    Orchestrates a simulation run across one or more models.

    The master:
      - tells the TickSource to start
      - on each tick: drives all models via on_tick()
      - waits for all models to acknowledge via SyncProtocol
      - never publishes telemetry or sync messages itself

    Usage:
        participant = DomainParticipant()
        sync = DdsSyncProtocol(participant)
        master = SimulationMaster(
            tick_source=SoftwareTickSource(),
            sync_protocol=sync,
            models=[
                FmuModelAdapter("power.fmu", "power", participant, sync),
            ],
            dt=0.1,
            stop_time=10.0,
        )
        master.run()
    """

    def __init__(
        self,
        tick_source: TickSource,
        sync_protocol: SyncProtocol,
        models: list[ModelAdapter],
        dt: float = 0.1,
        stop_time: float = 1.0,
        sync_timeout: float = 5.0,
        wiring: Optional[WiringMap] = None,
        command_store: Optional[CommandStore] = None,
        param_store: Optional[ParameterStore] = None,
        seed: Optional[int] = None,
    ) -> None:
        if not models:
            raise SimulationError("SimulationMaster requires at least one ModelAdapter.")

        self._tick_source = tick_source
        self._sync_protocol = sync_protocol
        self._models = models
        self._dt = dt
        self._stop_time = stop_time
        self._sync_timeout = sync_timeout
        self._wiring = wiring
        self._command_store = command_store
        self._param_store = param_store
        self._time: float = 0.0
        self._running = False
        self._model_ids = [m.model_id for m in models]
        self._seed_manager: SeedManager = SeedManager(seed)

    def run(self, start_time: float = 0.0) -> None:
        """
        Initialise all models and run the simulation to stop_time.
        Blocks until the simulation completes or an error occurs.
        """
        self._time = start_time
        self._running = True

        logger.info(
            f"SimulationMaster starting: models={self._model_ids} "
            f"dt={self._dt}s stop={self._stop_time}s"
        )

        for model in self._models:
            try:
                model.initialise(start_time=start_time)
            except Exception as e:
                raise SimulationError(
                    f"Failed to initialise model '{model.model_id}': {e}"
                ) from e

        # Validate wiring against registered equipment
        if self._wiring is not None:
            from svf.core.equipment import Equipment
            equipment_map = {
                m.model_id: m for m in self._models
                if isinstance(m, Equipment)
            }

            # Build equipment map
            self._equipment_map = equipment_map

            for conn in self._wiring.connections:
                if conn.from_equipment not in equipment_map:
                    raise SimulationError(
                        f"Wiring references unknown source equipment "
                        f"'{conn.from_equipment}' in connection: {conn}"
                    )
                if conn.to_equipment not in equipment_map:
                    raise SimulationError(
                        f"Wiring references unknown destination equipment "
                        f"'{conn.to_equipment}' in connection: {conn}"
                    )
                src = equipment_map[conn.from_equipment]
                if conn.from_port not in src.ports:
                    raise SimulationError(
                        f"Wiring references unknown port '{conn.from_port}' "
                        f"on equipment '{conn.from_equipment}'"
                    )
                dst = equipment_map[conn.to_equipment]
                if conn.to_port not in dst.ports:
                    raise SimulationError(
                        f"Wiring references unknown port '{conn.to_port}' "
                        f"on equipment '{conn.to_equipment}'"
                    )
            logger.info(
                f"Wiring validated: {len(self._wiring.connections)} "
                f"connections across {len(equipment_map)} equipment"
            )

        try:
            self._tick_source.start(
                on_tick=self._on_tick,
                dt=self._dt,
                stop_time=self._stop_time,
            )
        finally:
            self._teardown()

        self._seed_manager.save()
        logger.info(f"SimulationMaster run complete (seed={self._seed_manager.master_seed})")

    @property
    def seed(self) -> int:
        """Master seed for this simulation run."""
        return int(self._seed_manager.master_seed)

    def seed_for(self, model_id: str) -> int:
        """Get deterministic seed for a specific model."""
        return int(self._seed_manager.seed_for(model_id))

    def stop(self) -> None:
        """Signal the simulation to stop after the current tick."""
        self._running = False
        self._tick_source.stop()

    def _effective_dt(self) -> float:
        """
        Compute effective timestep as min of master dt and any model suggestions.
        Falls back to self._dt if no model suggests a smaller step.
        """
        dt = self._dt
        for model in self._models:
            suggested = getattr(model, "suggested_dt", lambda: None)()
            if suggested is not None and suggested < dt:
                dt = suggested
        return dt

    def _on_tick(self, t: float) -> None:
        """
        Called by TickSource on each tick.
        Drives all models then waits for their acknowledgements.
        """
        if not self._running:
            self._tick_source.stop()
            return

        self._time = t
        self._sync_protocol.reset()

        for model in self._models:
            try:
                model.on_tick(t=t, dt=self._effective_dt())
            except Exception as e:
                raise SimulationError(
                    f"Model '{model.model_id}' failed on tick t={t:.3f}: {e}"
                ) from e

        all_ready = self._sync_protocol.wait_for_ready(
            expected=self._model_ids,
            timeout=self._sync_timeout,
        )

        if not all_ready:
            raise SimulationError(
                f"Sync timeout at t={t:.3f}: not all models acknowledged "
                f"within {self._sync_timeout}s"
            )
            
        # Apply wiring — copy OUT port values to connected IN ports
        if self._wiring is not None and self._command_store is not None:
            from svf.core.equipment import Equipment
            
            # Grab the equipment map
            equipment_map = getattr(self, "_equipment_map", {})

            for conn in self._wiring.connections:
                src = equipment_map.get(conn.from_equipment)
                if src is not None:
                    try:
                        value = src.read_port(conn.from_port)
                        self._command_store.inject(
                            name=conn.to_port,
                            value=value,
                            t=self._time,
                            source_id=f"wiring:{conn.from_equipment}.{conn.from_port}",
                        )
                        logger.debug(
                            f"Wiring: {conn.from_equipment}.{conn.from_port} "
                            f"-> {conn.to_equipment}.{conn.to_port} = {value}"
                        )
                    except ValueError as e:
                        logger.warning(f"Wiring error: {e}")

        # Publish simulation time for svf_command_schedule
        if self._param_store is not None:
            self._param_store.write(
                name="svf.sim_time",
                value=round(self._time, 9),
                t=round(self._time, 9),
                model_id="svf.master",
            )


    def _teardown(self) -> None:
        """Tear down all models then DDS sync protocol cleanly."""
        for model in self._models:
            try:
                model.teardown()
            except Exception as e:
                logger.warning(f"Error during teardown of '{model.model_id}': {e}")
        # Explicitly close DDS sync protocol to prevent double-linked list crash
        if hasattr(self._sync_protocol, "close"):
            try:
                self._sync_protocol.close()
            except Exception as e:
                logger.warning(f"Error closing sync protocol: {e}")

    @property
    def time(self) -> float:
        """Current simulation time in seconds."""
        return self._time

    @property
    def model_ids(self) -> list[str]:
        """IDs of all registered models."""
        return list(self._model_ids)

    def __enter__(self) -> "SimulationMaster":
        return self

    def __exit__(self, *args: object) -> None:
        self._teardown()