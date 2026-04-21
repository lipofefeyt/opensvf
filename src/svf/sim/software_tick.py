"""
SVF SoftwareTickSource
Drives simulation time in a Python loop as fast as possible.
Implements: SVF-DEV-010
"""

from __future__ import annotations

import logging
from svf.core.abstractions import TickSource, TickCallback

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

class RealtimeTickSource(TickSource):
    """
    Advances simulation time aligned to wall-clock time.
    Sleeps between ticks to maintain dt alignment.
    If a tick takes longer than dt, logs a warning and continues
    immediately (no drift accumulation — each tick targets absolute
    wall-clock time, not relative to previous tick end).

    Usage:
        master = SimulationMaster(
            tick_source=RealtimeTickSource(),
            ...
        )
    """

    def __init__(self, warn_overrun: bool = True) -> None:
        self._running = False
        self._warn_overrun = warn_overrun

    def start(self, on_tick: TickCallback, dt: float, stop_time: float) -> None:
        import time
        self._running = True
        t = 0.0
        step = 0
        logger.info(
            f"RealtimeTickSource starting: dt={dt}s stop={stop_time}s"
        )
        t0_wall = time.monotonic()

        while self._running and round(t, 9) < round(stop_time, 9):
            logger.debug(f"Tick {step}: t={t:.6f}")
            on_tick(t)

            t = round(t + dt, 9)
            step += 1

            # Target wall-clock time for next tick
            target_wall = t0_wall + t
            now = time.monotonic()
            sleep_s = target_wall - now

            if sleep_s > 0:
                time.sleep(sleep_s)
            elif self._warn_overrun and sleep_s < -dt * 0.1:
                overrun_ms = -sleep_s * 1000
                logger.warning(
                    f"[realtime] Tick {step} overrun by {overrun_ms:.1f}ms "
                    f"(dt={dt*1000:.0f}ms)"
                )

        logger.info(
            f"RealtimeTickSource finished after {step} ticks "
            f"(wall={time.monotonic()-t0_wall:.2f}s sim={stop_time:.2f}s)"
        )

    def stop(self) -> None:
        """Signal the loop to stop after the current tick."""
        self._running = False
