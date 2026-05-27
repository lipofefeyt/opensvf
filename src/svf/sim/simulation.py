"""
SVF Simulation Master
Orchestrates simulation execution via dependency-injected abstractions.
Depends only on TickSource, SyncProtocol, and ModelAdapter interfaces.
The master drives models and waits for sync — it never speaks for models.
Implements: SVF-DEV-016
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Callable, Optional

from svf.core.abstractions import TickSource, SyncProtocol, ModelAdapter
from svf.config.wiring import WiringMap
from svf.sim.obt_param_file import ObtParamFile
from svf.sim.replay import SeedManager
from svf.stores.command_store import CommandStore
from svf.stores.parameter_store import ParameterStore

logger = logging.getLogger(__name__)

_TICK_STATS_WINDOW = 100  # rolling window size for tick execution times


@dataclass
class TickStats:
    """
    Rolling-window tick execution time statistics.

    All durations are in milliseconds, computed over the last
    ``_TICK_STATS_WINDOW`` ticks.

    Implements: SVF-DEV-177
    """

    count: int
    min_ms: float
    max_ms: float
    mean_ms: float
    p95_ms: float
    p99_ms: float


class SimulationError(Exception):
    """Raised when the simulation master encounters a non-recoverable error."""
    pass


class EquipmentTimeoutError(Exception):
    """
    Raised when a model's ``on_tick()`` does not return within the configured
    ``equipment_tick_timeout`` deadline.

    In FreeRTOS HIL campaigns the recommended deadline is 3.5 s — providing
    a safety margin below the openobsw STM32H750 IWDG timeout of 4.0 s.

    Implements: SVF-DEV-178
    """

    def __init__(self, equipment_id: str, obt: float, timeout_s: float) -> None:
        self.equipment_id = equipment_id
        self.obt = obt
        self.timeout_s = timeout_s
        super().__init__(
            f"Equipment '{equipment_id}' tick timeout at OBT {obt:.3f}s "
            f"(deadline={timeout_s:.1f}s)"
        )


class EquipmentTickError(Exception):
    """
    Raised (or passed to on_tick_error) when an equipment model fails during
    a simulation tick. Carries structured context so harnesses and reporters
    can log exactly what failed without parsing exception messages.

    Implements: SVF-DEV-156
    """

    def __init__(
        self,
        equipment_id: str,
        obt: float,
        cause: Exception,
    ) -> None:
        self.equipment_id = equipment_id
        self.obt = obt
        self.cause = cause
        self.context: dict[str, Any] = {
            "equipment_id": equipment_id,
            "obt": obt,
            "cause_type": type(cause).__name__,
            "cause_message": str(cause),
        }
        super().__init__(
            f"Equipment '{equipment_id}' failed at OBT {obt:.3f}s: "
            f"{type(cause).__name__}: {cause}"
        )


# Callback type: receives an EquipmentTickError; may raise to abort the run,
# or return to record-and-continue.
OnTickError = Callable[[EquipmentTickError], None]


def _default_on_tick_error(err: EquipmentTickError) -> None:
    """Default handler: re-raise as SimulationError (existing behaviour)."""
    raise SimulationError(str(err)) from err.cause


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
        obt_param_file: Optional[ObtParamFile] = None,
        on_tick_error: Optional[OnTickError] = None,
        equipment_tick_timeout: Optional[float] = None,
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
        self._obt_param_file = obt_param_file
        self._time: float = 0.0
        self._running = False
        self._model_ids = [m.model_id for m in models]
        self._seed_manager: SeedManager = SeedManager(seed)
        self._on_tick_error: OnTickError = on_tick_error or _default_on_tick_error
        self._equipment_tick_timeout: Optional[float] = equipment_tick_timeout
        self._tick_times: deque[float] = deque(maxlen=_TICK_STATS_WINDOW)

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

    def tick_stats(self) -> Optional[TickStats]:
        """
        Rolling-window tick execution time statistics.

        Returns ``None`` when fewer than two ticks have elapsed.
        Implements: SVF-DEV-177
        """
        if len(self._tick_times) < 2:
            return None
        sorted_times = sorted(self._tick_times)
        n = len(sorted_times)

        def _percentile(data: list[float], pct: float) -> float:
            idx = (pct / 100.0) * (len(data) - 1)
            lo, hi = int(idx), min(int(idx) + 1, len(data) - 1)
            return data[lo] + (data[hi] - data[lo]) * (idx - lo)

        return TickStats(
            count=n,
            min_ms=sorted_times[0],
            max_ms=sorted_times[-1],
            mean_ms=sum(sorted_times) / n,
            p95_ms=_percentile(sorted_times, 95),
            p99_ms=_percentile(sorted_times, 99),
        )

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

    def _tick_model(self, model: ModelAdapter, t: float, dt: float) -> None:
        """
        Drive a single model for one tick, enforcing the equipment timeout.

        When ``equipment_tick_timeout`` is set the call runs in a daemon
        thread; if it does not return within the deadline
        ``EquipmentTimeoutError`` is raised.  Implements: SVF-DEV-178
        """
        if self._equipment_tick_timeout is None:
            model.on_tick(t=t, dt=dt)
            return

        exc_holder: list[BaseException] = []

        def _target() -> None:
            try:
                model.on_tick(t=t, dt=dt)
            except BaseException as exc:
                exc_holder.append(exc)

        thread = threading.Thread(target=_target, daemon=True)
        thread.start()
        thread.join(timeout=self._equipment_tick_timeout)

        if thread.is_alive():
            raise EquipmentTimeoutError(
                model.model_id, t, self._equipment_tick_timeout
            )
        if exc_holder:
            raise exc_holder[0]

    def _on_tick(self, t: float) -> None:
        """
        Called by TickSource on each tick.
        Drives all models then waits for their acknowledgements.
        """
        if not self._running:
            self._tick_source.stop()
            return

        _tick_start = time.monotonic()
        self._time = t
        self._sync_protocol.reset()

        # Inject time-tagged entries from OBT parameter file
        if self._obt_param_file is not None and self._command_store is not None:
            for entry in self._obt_param_file.entries_due(t):
                self._command_store.inject(
                    name=entry.name,
                    value=entry.value,
                    t=t,
                    source_id="obt_param_file",
                )

        for model in self._models:
            try:
                self._tick_model(model, t, self._effective_dt())
            except EquipmentTimeoutError as e:
                self._on_tick_error(EquipmentTickError(model.model_id, t, e))
            except Exception as e:
                self._on_tick_error(EquipmentTickError(model.model_id, t, e))

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

        self._tick_times.append((time.monotonic() - _tick_start) * 1000.0)


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