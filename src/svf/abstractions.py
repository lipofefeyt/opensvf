"""
SVF Abstraction Layer
Defines the three core interfaces that SimulationMaster depends on.
All timing, synchronisation, and model driving occurs through these interfaces.
Implements: SVF-DEV-009, SVF-DEV-011, SVF-DEV-013, SVF-DEV-016
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable


# Type alias for the tick callback signature
TickCallback = Callable[[float], None]


class TickSource(ABC):
    """
    Drives simulation time progression.

    The TickSource is responsible for determining when the next tick
    should occur and notifying the SimulationMaster. The master never
    advances time on its own — it always waits for the TickSource.

    Swap SoftwareTickSource for RealtimeTickSource to go real-time
    without changing anything else.
    """

    @abstractmethod
    def start(self, on_tick: TickCallback, dt: float, stop_time: float) -> None:
        """
        Start generating ticks.

        Args:
            on_tick:   Callback invoked on each tick with current time t.
            dt:        Timestep in seconds.
            stop_time: Simulation stop time in seconds.
        """
        ...

    @abstractmethod
    def stop(self) -> None:
        """Stop generating ticks. Safe to call before start()."""
        ...


class SyncProtocol(ABC):
    """
    Coordinates tick acknowledgements between master and models.

    After broadcasting a tick, the master calls wait_for_ready() to
    block until all registered models have acknowledged. Each model
    calls publish_ready() itself when it has finished processing the tick.

    Swap DdsSyncProtocol for SharedMemorySyncProtocol for sub-ms latency.
    """

    @abstractmethod
    def wait_for_ready(self, expected: list[str], timeout: float) -> bool:
        """
        Block until all expected models have acknowledged the current tick.

        Args:
            expected: List of model_id strings to wait for.
            timeout:  Maximum seconds to wait before returning False.

        Returns:
            True if all models acknowledged within timeout, False otherwise.
        """
        ...

    @abstractmethod
    def publish_ready(self, model_id: str, t: float) -> None:
        """
        Publish a readiness acknowledgement for the given model and time.
        Called by the ModelAdapter itself after on_tick() completes —
        never by the SimulationMaster.

        Args:
            model_id: Unique identifier of the acknowledging model.
            t:        The simulation time being acknowledged.
        """
        ...

    @abstractmethod
    def reset(self) -> None:
        """Clear any pending acknowledgements. Called before each tick."""
        ...


class ModelAdapter(ABC):
    """
    Wraps any simulation model in a uniform interface.

    The SimulationMaster drives models exclusively through this interface.
    Each adapter is responsible for:
      - executing its model on each tick
      - publishing telemetry outputs to DDS
      - publishing its own sync acknowledgement via SyncProtocol

    The master never publishes on behalf of a model.
    """

    @property
    @abstractmethod
    def model_id(self) -> str:
        """Unique identifier for this model within a simulation run."""
        ...

    @abstractmethod
    def initialise(self, start_time: float = 0.0) -> None:
        """
        Prepare the model for simulation.
        Called once before the first tick.
        """
        ...

    @abstractmethod
    def on_tick(self, t: float, dt: float) -> None:
        """
        Advance the model by one timestep.
        The adapter is responsible for publishing outputs and
        acknowledging readiness via its SyncProtocol.

        Args:
            t:  Current simulation time in seconds.
            dt: Timestep size in seconds.

        Raises:
            Any exception signals a fault to the SimulationMaster.
        """
        ...

    @abstractmethod
    def teardown(self) -> None:
        """
        Clean up model resources.
        Called once after the final tick. Safe to call if initialise()
        was never called.
        """
        ...