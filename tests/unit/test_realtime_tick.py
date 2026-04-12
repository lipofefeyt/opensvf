"""Tests for RealtimeTickSource wall-clock alignment."""
from __future__ import annotations
import time
import pytest
from svf.software_tick import RealtimeTickSource, SoftwareTickSource


class TestRealtimeTickSourceSuite:

    @pytest.mark.requirement("SVF-DEV-010")
    def test_realtime_tick_wall_clock_alignment(self) -> None:
        """RealtimeTickSource: 1s simulation takes ~1s wall clock."""
        source = RealtimeTickSource()
        ticks: list[float] = []
        t_start = time.monotonic()
        source.start(lambda t: ticks.append(t), dt=0.1, stop_time=1.0)
        elapsed = time.monotonic() - t_start

        assert len(ticks) == 10
        assert 0.9 <= elapsed <= 1.5, (
            f"Wall clock {elapsed:.2f}s — expected ~1.0s for 1s simulation"
        )

    @pytest.mark.requirement("SVF-DEV-010")
    def test_realtime_tick_correct_count(self) -> None:
        """RealtimeTickSource fires correct number of ticks."""
        source = RealtimeTickSource()
        ticks: list[float] = []
        source.start(lambda t: ticks.append(t), dt=0.1, stop_time=0.5)
        assert len(ticks) == 5

    @pytest.mark.requirement("SVF-DEV-010")
    def test_software_tick_faster_than_realtime(self) -> None:
        """SoftwareTickSource runs faster than wall clock."""
        source = SoftwareTickSource()
        t_start = time.monotonic()
        source.start(lambda t: None, dt=0.1, stop_time=5.0)
        elapsed = time.monotonic() - t_start
        assert elapsed < 1.0, (
            f"SoftwareTickSource took {elapsed:.2f}s for 5s simulation — too slow"
        )

    @pytest.mark.requirement("SVF-DEV-010")
    def test_realtime_tick_stop(self) -> None:
        """RealtimeTickSource stops cleanly when stop() called."""
        import threading
        source = RealtimeTickSource()
        ticks: list[float] = []

        def run() -> None:
            source.start(lambda t: ticks.append(t), dt=0.1, stop_time=10.0)

        t = threading.Thread(target=run)
        t.start()
        time.sleep(0.35)
        source.stop()
        t.join(timeout=2.0)
        assert 2 <= len(ticks) <= 6
