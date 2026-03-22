"""
SVF SoftwareTickSource
Drives simulation time in a Python loop as fast as possible.
Implements: SVF-DEV-010
"""

from __future__ import annotations

import logging
from svf.abstractions import TickSource, TickCallback

logger = logging.getLogger(__name__)


class SoftwareTickSource(TickSource):
    """
    Advances simulation time in a simple Python loop.
    No real-time guarantees — runs as fast as the hardware allows.
    This is the default TickSource for software-only simulation runs.
    """

    def __init__(self) -> None:
        self._running = False

    def start(self, on_tick: TickCallback, dt: float, stop_time: float) -> None:
        """
        Run the simulation loop synchronously from start_time to stop_time.
        Calls on_tick(t) at each step before advancing time.
        """
        self._running = True
        t = 0.0
        step = 0

        logger.info(f"SoftwareTickSource starting: dt={dt}s stop={stop_time}s")

        while self._running and round(t, 9) < round(stop_time, 9):
            logger.debug(f"Tick {step}: t={t:.6f}")
            on_tick(t)
            t = round(t + dt, 9)
            step += 1

        logger.info(f"SoftwareTickSource finished after {step} ticks")

    def stop(self) -> None:
        """Signal the loop to stop after the current tick."""
        self._running = False