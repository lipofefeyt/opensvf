"""Tests for continuous temporal monitor (MTL-style assertions)."""
from __future__ import annotations
import time
import threading
import pytest
from svf.campaign.procedure import (
    ParameterMonitor, MonitorResult, ProcedureContext, ProcedureError
)
from svf.stores.parameter_store import ParameterStore
from svf.stores.command_store import CommandStore


def make_store() -> ParameterStore:
    return ParameterStore()


class TestParameterMonitorSuite:

    @pytest.mark.requirement("SVF-DEV-131")
    def test_compliant_when_no_violations(self) -> None:
        """Monitor reports compliant when parameter stays within bounds."""
        store = make_store()
        store.write("x", 0.05, t=0.0, model_id="test")

        mon = ParameterMonitor(store, "x", less_than=0.1)
        time.sleep(0.15)
        mon.stop()
        result = mon.summary()

        assert result.compliant is True
        assert len(result.violations) == 0
        assert result.samples > 0

    @pytest.mark.requirement("SVF-DEV-131")
    def test_violation_recorded_when_threshold_exceeded(self) -> None:
        """Monitor records violation when parameter exceeds threshold."""
        store = make_store()
        store.write("x", 0.05, t=0.0, model_id="test")

        mon = ParameterMonitor(store, "x", less_than=0.1, poll_interval=0.02)
        time.sleep(0.05)

        # Inject violation
        store.write("x", 0.5, t=1.0, model_id="test")
        time.sleep(0.1)
        mon.stop()
        result = mon.summary()

        assert result.compliant is False
        assert len(result.violations) > 0
        assert result.violations[0].value == pytest.approx(0.5)

    @pytest.mark.requirement("SVF-DEV-131")
    def test_assert_no_violations_raises_on_violation(self) -> None:
        """assert_no_violations() raises ProcedureError when violated."""
        store = make_store()
        store.write("x", 0.5, t=0.0, model_id="test")

        mon = ParameterMonitor(store, "x", less_than=0.1, poll_interval=0.02)
        time.sleep(0.1)

        with pytest.raises(ProcedureError, match="Monitor violation"):
            mon.assert_no_violations()

    @pytest.mark.requirement("SVF-DEV-131")
    def test_assert_no_violations_passes_when_compliant(self) -> None:
        """assert_no_violations() does not raise when no violations."""
        store = make_store()
        store.write("x", 0.05, t=0.0, model_id="test")

        mon = ParameterMonitor(store, "x", less_than=0.1, poll_interval=0.02)
        time.sleep(0.1)
        mon.assert_no_violations()  # should not raise

    @pytest.mark.requirement("SVF-DEV-131")
    def test_greater_than_condition(self) -> None:
        """Monitor checks greater_than condition correctly."""
        store = make_store()
        store.write("x", 0.5, t=0.0, model_id="test")

        mon = ParameterMonitor(store, "x", greater_than=0.1, poll_interval=0.02)
        time.sleep(0.05)

        # Inject violation — drop below threshold
        store.write("x", 0.05, t=1.0, model_id="test")
        time.sleep(0.1)
        result = mon.summary()

        assert result.compliant is False
        assert result.violations[0].condition == "greater_than"

    @pytest.mark.requirement("SVF-DEV-131")
    def test_max_min_values_tracked(self) -> None:
        """Monitor tracks max and min parameter values."""
        store = make_store()
        store.write("x", 0.05, t=0.0, model_id="test")

        mon = ParameterMonitor(store, "x", less_than=1.0, poll_interval=0.02)
        time.sleep(0.05)
        store.write("x", 0.3, t=1.0, model_id="test")
        time.sleep(0.05)
        store.write("x", 0.01, t=2.0, model_id="test")
        time.sleep(0.05)
        result = mon.summary()

        assert result.max_value is not None
        assert result.min_value is not None
        assert result.max_value >= 0.3
        assert result.min_value <= 0.05

    @pytest.mark.requirement("SVF-DEV-131")
    def test_requirement_in_result(self) -> None:
        """MonitorResult includes requirement ID."""
        store = make_store()
        store.write("x", 0.05, t=0.0, model_id="test")

        mon = ParameterMonitor(
            store, "x", less_than=0.1, requirement="MIS-AOCS-042"
        )
        time.sleep(0.1)
        result = mon.summary()

        assert result.requirement == "MIS-AOCS-042"

    @pytest.mark.requirement("SVF-DEV-131")
    def test_ctx_monitor_returns_monitor(self) -> None:
        """ctx.monitor() returns a ParameterMonitor."""
        store = make_store()
        store.write("x", 0.05, t=0.0, model_id="test")
        ctx = ProcedureContext(None, store, CommandStore())

        mon = ctx.monitor("x", less_than=0.1)
        assert isinstance(mon, ParameterMonitor)
        mon.stop()

    @pytest.mark.requirement("SVF-DEV-131")
    def test_multiple_concurrent_monitors(self) -> None:
        """Multiple monitors can run concurrently."""
        store = make_store()
        store.write("rate_x", 0.05, t=0.0, model_id="test")
        store.write("rate_y", 0.05, t=0.0, model_id="test")

        mon1 = ParameterMonitor(store, "rate_x", less_than=0.1)
        mon2 = ParameterMonitor(store, "rate_y", less_than=0.1)
        time.sleep(0.1)

        # Violate only rate_y
        store.write("rate_y", 0.5, t=1.0, model_id="test")
        time.sleep(0.1)

        r1 = mon1.summary()
        r2 = mon2.summary()

        assert r1.compliant is True
        assert r2.compliant is False
