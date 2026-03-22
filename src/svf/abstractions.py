"""
SVF Abstraction Layer
Defines the three core interfaces that SimulationMaster depends on.
All timing, synchronisation, and model driving occurs through these interfaces.
Implements: SVF-DEV-009, SVF-DEV-011, SVF-DEV-013, SVF-DEV-016
"""

from __future__ import annotations

from abc import ABC, abstractmethod


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
    calls publish_ready() when it has finished processing the tick.

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
    FMUs, native Python models, and future hardware bridges all look
    identical to the master.
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
    def on_tick(self, t: float, dt: float) -> dict[str, float]:
        """
        Advance the model by one timestep.

        Args:
            t:  Current simulation time in seconds.
            dt: Timestep size in seconds.

        Returns:
            Dict of {variable_name: value} for all model outputs.
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


# Type alias for the tick callback signature
from typing import Callable
TickCallback = Callable[[float], None]