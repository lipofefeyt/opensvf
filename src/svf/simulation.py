"""
SVF Simulation Master
Orchestrates simulation execution via dependency-injected abstractions.
Depends only on TickSource, SyncProtocol, and ModelAdapter interfaces.
Implements: SVF-DEV-016
"""

from __future__ import annotations

import logging
from typing import Optional

from svf.abstractions import TickSource, SyncProtocol, ModelAdapter

logger = logging.getLogger(__name__)


class SimulationError(Exception):
    """Raised when the simulation master encounters a non-recoverable error."""
    pass


class SimulationMaster:
    """
    Orchestrates a simulation run across one or more models.

    The master does not know about FMUs, DDS, or Python loops directly.
    It depends exclusively on three injected abstractions:
      - TickSource:    drives simulation time
      - SyncProtocol:  coordinates model acknowledgements
      - ModelAdapter[]: the models being simulated

    Usage:
        participant = DomainParticipant()
        master = SimulationMaster(
            tick_source=SoftwareTickSource(),
            sync_protocol=DdsSyncProtocol(participant),
            models=[FmuModelAdapter("power.fmu", "power")],
            dt=0.1,
            stop_time=10.0,
        )
        master.run()

    Or as a context manager:
        with SimulationMaster(...) as master:
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
    ) -> None:
        if not models:
            raise SimulationError("SimulationMaster requires at least one ModelAdapter.")

        self._tick_source = tick_source
        self._sync_protocol = sync_protocol
        self._models = models
        self._dt = dt
        self._stop_time = stop_time
        self._sync_timeout = sync_timeout
        self._time: float = 0.0
        self._running = False
        self._model_ids = [m.model_id for m in models]

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

        # Initialise all models
        for model in self._models:
            try:
                model.initialise(start_time=start_time)
            except Exception as e:
                raise SimulationError(
                    f"Failed to initialise model '{model.model_id}': {e}"
                ) from e

        # Hand control to the TickSource
        try:
            self._tick_source.start(
                on_tick=self._on_tick,
                dt=self._dt,
                stop_time=self._stop_time,
            )
        finally:
            self._teardown()

        logger.info("SimulationMaster run complete")

    def stop(self) -> None:
        """Signal the simulation to stop after the current tick."""
        self._running = False
        self._tick_source.stop()

    def _on_tick(self, t: float) -> None:
        """
        Called by TickSource on each tick.
        Drives all models and waits for acknowledgements.
        """
        if not self._running:
            self._tick_source.stop()
            return

        self._time = t
        self._sync_protocol.reset()

        # Drive all models
        for model in self._models:
            try:
                outputs = model.on_tick(t=t, dt=self._dt)
                logger.debug(f"[{model.model_id}] t={t:.3f} outputs={outputs}")
            except Exception as e:
                raise SimulationError(
                    f"Model '{model.model_id}' failed on tick t={t:.3f}: {e}"
                ) from e

            # Model publishes its own ready acknowledgement
            self._sync_protocol.publish_ready(
                model_id=model.model_id,
                t=t,
            )

        # Wait for all models to acknowledge
        all_ready = self._sync_protocol.wait_for_ready(
            expected=self._model_ids,
            timeout=self._sync_timeout,
        )

        if not all_ready:
            raise SimulationError(
                f"Sync timeout at t={t:.3f}: not all models acknowledged "
                f"within {self._sync_timeout}s"
            )

    def _teardown(self) -> None:
        """Tear down all models cleanly."""
        for model in self._models:
            try:
                model.teardown()
            except Exception as e:
                logger.warning(f"Error during teardown of '{model.model_id}': {e}")

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