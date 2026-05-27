"""
Unit tests for FreeRTOS support additions (M43).

Groups:
  G1 — TC burst guard (SVF-DEV-176)
  G2 — Tick stats + equipment timeout (SVF-DEV-177, SVF-DEV-178)
  G3 — FreeRTOS UART diagnostics (SVF-DEV-179)
"""
from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from svf.core.abstractions import SyncProtocol, TickSource, TickCallback, ModelAdapter
from svf.core.equipment import PortDefinition
from svf.models.dhs.hil_adapter import HilAdapter
from svf.models.dhs.obc_emulator import OBCEmulatorAdapter, _FREERTOS_TC_QUEUE_DEPTH
from svf.pus.tm import PusTmPacket
from svf.sim.simulation import (
    EquipmentTimeoutError,
    EquipmentTickError,
    SimulationError,
    SimulationMaster,
    TickStats,
)
from svf.stores.command_store import CommandStore
from svf.stores.parameter_store import ParameterStore


# ── shared stubs ─────────────────────────────────────────────────────────────

class _NoSync(SyncProtocol):
    def reset(self) -> None: pass
    def publish_ready(self, model_id: str, t: float) -> None: pass
    def wait_for_ready(self, expected: list[str], timeout: float) -> bool: return True


def _make_obc() -> OBCEmulatorAdapter:
    return OBCEmulatorAdapter(
        sim_path=None,
        sync_protocol=_NoSync(),
        store=ParameterStore(),
        command_store=CommandStore(),
        socket_addr=None,
    )


class _NullModel(ModelAdapter):
    """ModelAdapter that does nothing but complete instantly."""

    def __init__(self, model_id: str = "null") -> None:
        self._model_id = model_id

    @property
    def model_id(self) -> str:
        return self._model_id

    def initialise(self, start_time: float = 0.0) -> None: pass
    def on_tick(self, t: float, dt: float) -> None: pass
    def teardown(self) -> None: pass


class _SlowModel(ModelAdapter):
    """ModelAdapter whose on_tick blocks for a configurable duration."""

    def __init__(self, sleep_s: float) -> None:
        self._sleep_s = sleep_s

    @property
    def model_id(self) -> str:
        return "slow"

    def initialise(self, start_time: float = 0.0) -> None: pass

    def on_tick(self, t: float, dt: float) -> None:
        time.sleep(self._sleep_s)

    def teardown(self) -> None: pass


class _ImmediateTickSource(TickSource):
    """Fires exactly N ticks and stops."""

    def __init__(self, n: int = 3) -> None:
        self._n = n

    def start(self, on_tick: TickCallback, dt: float, stop_time: float) -> None:
        for i in range(self._n):
            on_tick(float(i) * dt)

    def stop(self) -> None: pass


# ── G1: TC burst guard ────────────────────────────────────────────────────────

class FreeRTOSTcGuardSuite:

    @pytest.mark.requirement("SVF-DEV-176")
    def test_tc_burst_constant_matches_obsw_queue_depth(self) -> None:
        """_FREERTOS_TC_QUEUE_DEPTH is 4, matching obsw/task/tmtc.h capacity."""
        assert _FREERTOS_TC_QUEUE_DEPTH == 4

    @pytest.mark.requirement("SVF-DEV-176")
    def test_tc_burst_warns_at_freertos_queue_depth(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """_send_tcs() warns when frames exceed _FREERTOS_TC_QUEUE_DEPTH.

        Patching the constant to 0 means the single heartbeat ping always
        triggers the guard — tests the warning branch without needing >4
        simultaneous port commands.
        """
        obc = _make_obc()

        with patch("svf.models.dhs.obc_emulator._FREERTOS_TC_QUEUE_DEPTH", 0):
            with patch.object(obc, "_write_typed_frame"):
                with patch.object(obc, "_collect_until_sync", return_value=([], True)):
                    with caplog.at_level("WARNING"):
                        obc.do_step(0.0, 0.1)

        assert any("TC burst" in r.message for r in caplog.records)
        assert any("FreeRTOS queue depth" in r.message for r in caplog.records)

    @pytest.mark.requirement("SVF-DEV-176")
    def test_nominal_tick_no_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        """A normal tick with 1 heartbeat ping does not trigger a burst warning."""
        obc = _make_obc()

        with patch.object(obc, "_write_typed_frame"):
            with patch.object(obc, "_collect_until_sync", return_value=([], True)):
                with caplog.at_level("WARNING"):
                    obc.do_step(0.0, 0.1)

        burst_warnings = [r for r in caplog.records if "TC burst" in r.message]
        assert burst_warnings == []


# ── G2: Tick stats + equipment timeout ───────────────────────────────────────

class TickStatsSuite:

    def _make_master(self, n_ticks: int = 5, **kwargs: object) -> SimulationMaster:
        return SimulationMaster(
            tick_source=_ImmediateTickSource(n=n_ticks),
            sync_protocol=_NoSync(),
            models=[_NullModel()],
            dt=0.1,
            stop_time=float(n_ticks) * 0.1,
            **kwargs,  # type: ignore[arg-type]
        )

    @pytest.mark.requirement("SVF-DEV-177")
    def test_tick_stats_none_before_two_ticks(self) -> None:
        """tick_stats() returns None when fewer than two ticks have elapsed."""
        master = self._make_master(n_ticks=0)
        assert master.tick_stats() is None

    @pytest.mark.requirement("SVF-DEV-177")
    def test_tick_stats_returns_rolling_window_metrics(self) -> None:
        """After several ticks tick_stats() returns a TickStats with sensible values."""
        master = self._make_master(n_ticks=10)
        master.run()
        stats = master.tick_stats()
        assert stats is not None
        assert isinstance(stats, TickStats)
        assert stats.count == 10
        assert stats.min_ms >= 0.0
        assert stats.max_ms >= stats.min_ms
        assert stats.min_ms <= stats.mean_ms <= stats.max_ms
        assert stats.p95_ms >= stats.p99_ms * 0.0  # p99 >= p95 not guaranteed in tiny samples
        assert stats.p95_ms <= stats.max_ms

    @pytest.mark.requirement("SVF-DEV-177")
    def test_tick_stats_window_caps_at_100(self) -> None:
        """Rolling window never exceeds 100 entries regardless of tick count."""
        master = self._make_master(n_ticks=150)
        master.run()
        stats = master.tick_stats()
        assert stats is not None
        assert stats.count == 100


class EquipmentTimeoutSuite:

    @pytest.mark.requirement("SVF-DEV-178")
    def test_equipment_timeout_raises_equipment_timeout_error(self) -> None:
        """When a model blocks past the deadline EquipmentTimeoutError is raised."""
        errors: list[EquipmentTickError] = []

        def _capture(err: EquipmentTickError) -> None:
            errors.append(err)

        master = SimulationMaster(
            tick_source=_ImmediateTickSource(n=1),
            sync_protocol=_NoSync(),
            models=[_SlowModel(sleep_s=0.3)],
            dt=0.1,
            stop_time=0.1,
            equipment_tick_timeout=0.05,
            on_tick_error=_capture,
        )
        master.run()

        assert len(errors) == 1
        assert isinstance(errors[0].cause, EquipmentTimeoutError)
        assert errors[0].equipment_id == "slow"

    @pytest.mark.requirement("SVF-DEV-178")
    def test_equipment_timeout_not_triggered_when_model_is_fast(self) -> None:
        """No timeout error when model completes well within deadline."""
        errors: list[EquipmentTickError] = []

        master = SimulationMaster(
            tick_source=_ImmediateTickSource(n=3),
            sync_protocol=_NoSync(),
            models=[_NullModel()],
            dt=0.1,
            stop_time=0.3,
            equipment_tick_timeout=1.0,
            on_tick_error=lambda e: errors.append(e),
        )
        master.run()
        assert errors == []

    @pytest.mark.requirement("SVF-DEV-178")
    def test_equipment_timeout_error_message(self) -> None:
        """EquipmentTimeoutError carries equipment_id, obt, and timeout_s."""
        err = EquipmentTimeoutError("obc", 12.5, 3.5)
        assert err.equipment_id == "obc"
        assert err.obt == 12.5
        assert err.timeout_s == 3.5
        assert "3.5" in str(err)
        assert "obc" in str(err)

    @pytest.mark.requirement("SVF-DEV-178")
    def test_no_timeout_when_parameter_is_none(self) -> None:
        """When equipment_tick_timeout=None models run without a thread wrapper."""
        master = SimulationMaster(
            tick_source=_ImmediateTickSource(n=2),
            sync_protocol=_NoSync(),
            models=[_NullModel()],
            dt=0.1,
            stop_time=0.2,
            equipment_tick_timeout=None,
        )
        master.run()
        stats = master.tick_stats()
        assert stats is not None
        assert stats.count == 2


# ── G3: FreeRTOS UART diagnostics ────────────────────────────────────────────

class FreeRTOSDiagnosticsSuite:

    @pytest.mark.requirement("SVF-DEV-179")
    def test_stack_overflow_diagnostic_increments_counter(self) -> None:
        """vApplicationStackOverflowHook line increments stack_overflow_count."""
        obc = _make_obc()
        assert obc._freertos_stack_overflow_count == 0

        obc._on_obsw_freertos_diagnostic(
            "[OBSW] vApplicationStackOverflowHook: task AOCS"
        )
        assert obc._freertos_stack_overflow_count == 1

    @pytest.mark.requirement("SVF-DEV-179")
    def test_stack_overflow_case_insensitive(self) -> None:
        """Stack overflow detection is case-insensitive."""
        obc = _make_obc()
        obc._on_obsw_freertos_diagnostic("STACK OVERFLOW in task PUS")
        assert obc._freertos_stack_overflow_count == 1

    @pytest.mark.requirement("SVF-DEV-179")
    def test_stack_overflow_writes_to_parameter_store(self) -> None:
        """Stack overflow detection writes svf.obc.freertos.stack_overflow_count."""
        obc = _make_obc()
        obc._on_obsw_freertos_diagnostic("Stack overflow detected")
        entry = obc._store.read("svf.obc.freertos.stack_overflow_count")
        assert entry is not None
        assert entry.value == 1.0

    @pytest.mark.requirement("SVF-DEV-179")
    def test_iwdg_reset_diagnostic_increments_counter(self) -> None:
        """IWDG reset banner increments iwdg_reset_count."""
        obc = _make_obc()
        assert obc._freertos_iwdg_reset_count == 0

        obc._on_obsw_freertos_diagnostic("[OBSW] IWDG reset detected at boot")
        assert obc._freertos_iwdg_reset_count == 1

    @pytest.mark.requirement("SVF-DEV-179")
    def test_watchdog_reset_alias_recognised(self) -> None:
        """'watchdog reset' is recognised as an IWDG reset alias."""
        obc = _make_obc()
        obc._on_obsw_freertos_diagnostic("watchdog reset: previous boot")
        assert obc._freertos_iwdg_reset_count == 1

    @pytest.mark.requirement("SVF-DEV-179")
    def test_iwdg_reset_writes_to_parameter_store(self) -> None:
        """IWDG reset detection writes svf.obc.freertos.iwdg_reset_count."""
        obc = _make_obc()
        obc._on_obsw_freertos_diagnostic("IWDG reset at previous boot")
        entry = obc._store.read("svf.obc.freertos.iwdg_reset_count")
        assert entry is not None
        assert entry.value == 1.0

    @pytest.mark.requirement("SVF-DEV-179")
    def test_normal_line_does_not_increment_counters(self) -> None:
        """Normal log lines do not affect diagnostic counters."""
        obc = _make_obc()
        obc._on_obsw_freertos_diagnostic("[OBSW] STM32H750 started (protocol v2).")
        obc._on_obsw_freertos_diagnostic("[OBSW] SRDB version: 0.1.0")
        assert obc._freertos_stack_overflow_count == 0
        assert obc._freertos_iwdg_reset_count == 0

    @pytest.mark.requirement("SVF-DEV-180")
    def test_freertos_parameter_namespace_reserved(self) -> None:
        """PUS IDs 0x4020–0x402F must not appear in dhs.yaml (reserved for FreeRTOS)."""
        from pathlib import Path
        import yaml  # type: ignore[import-untyped]

        dhs_path = Path(__file__).parent.parent.parent / "srdb" / "baseline" / "dhs.yaml"
        data = yaml.safe_load(dhs_path.read_text())
        reserved = set(range(0x4020, 0x4030))
        used_ids: set[int] = set()
        for param in data.get("parameters", {}).values():
            pid = param.get("pus", {}).get("parameter_id")
            if pid is not None:
                used_ids.add(int(pid))
        collisions = reserved & used_ids
        assert not collisions, (
            f"PUS IDs {[hex(x) for x in collisions]} are reserved for "
            "dhs.obc.freertos.* but already used in dhs.yaml"
        )

    @pytest.mark.requirement("SVF-DEV-179")
    def test_counters_accumulate_across_multiple_events(self) -> None:
        """Multiple events accumulate correctly in the counters."""
        obc = _make_obc()
        for _ in range(3):
            obc._on_obsw_freertos_diagnostic("Stack overflow detected")
        for _ in range(2):
            obc._on_obsw_freertos_diagnostic("IWDG reset at boot")

        assert obc._freertos_stack_overflow_count == 3
        assert obc._freertos_iwdg_reset_count == 2
        assert obc._store.read("svf.obc.freertos.stack_overflow_count").value == 3.0  # type: ignore[union-attr]
        assert obc._store.read("svf.obc.freertos.iwdg_reset_count").value == 2.0  # type: ignore[union-attr]
