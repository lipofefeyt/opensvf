"""Tests for Procedure base class."""
from __future__ import annotations
from typing import Any
import pytest
from svf.test.procedure import (
    Procedure, ProcedureContext, ProcedureError,
    ProcedureResult, Verdict
)
from svf.stores.parameter_store import ParameterStore
from svf.stores.command_store import CommandStore
from svf.core.abstractions import SyncProtocol


class _NoSync(SyncProtocol):
    def reset(self) -> None: pass
    def publish_ready(self, m: str, t: float) -> None: pass
    def wait_for_ready(self, e: list[str], t: float) -> bool: return True


def make_minimal_master() -> tuple[Any, ParameterStore, CommandStore]:
    """Return a minimal (store, cmd_store) pair — master is None for unit tests."""
    store     = ParameterStore()
    cmd_store = CommandStore()
    return None, store, cmd_store


class PassingProcedure(Procedure):
    id          = "TC-TEST-001"
    title       = "Passing test procedure"
    requirement = "TEST-REQ-001"

    def run(self, ctx: ProcedureContext) -> None:
        self.step("Inject parameter")
        ctx.inject("test.param", 1.0)
        self.step("Verify parameter")
        ctx.assert_parameter("test.param", greater_than=0.5)


class FailingProcedure(Procedure):
    id          = "TC-TEST-002"
    title       = "Failing test procedure"
    requirement = "TEST-REQ-002"

    def run(self, ctx: ProcedureContext) -> None:
        self.step("Assert impossible condition")
        ctx.assert_parameter("test.param", less_than=0.0)


class TestProcedureSuite:

    @pytest.mark.requirement("SVF-DEV-120")
    def test_passing_procedure_returns_pass(self) -> None:
        """Procedure with passing assertions returns PASS verdict."""
        master, store, cmd_store = make_minimal_master()
        store.write("test.param", 1.0, t=0.0, model_id="test")
        proc = PassingProcedure()
        result = proc.execute(master, store, cmd_store)
        assert result.verdict == Verdict.PASS

    @pytest.mark.requirement("SVF-DEV-120")
    def test_failing_procedure_returns_fail(self) -> None:
        """Procedure with failing assertion returns FAIL verdict."""
        master, store, cmd_store = make_minimal_master()
        store.write("test.param", 1.0, t=0.0, model_id="test")
        proc = FailingProcedure()
        result = proc.execute(master, store, cmd_store)
        assert result.verdict == Verdict.FAIL

    @pytest.mark.requirement("SVF-DEV-120")
    def test_result_contains_procedure_metadata(self) -> None:
        """ProcedureResult contains id, title, requirement."""
        master, store, cmd_store = make_minimal_master()
        store.write("test.param", 1.0, t=0.0, model_id="test")
        result = PassingProcedure().execute(master, store, cmd_store)
        assert result.procedure_id == "TC-TEST-001"
        assert result.title == "Passing test procedure"
        assert result.requirement == "TEST-REQ-001"

    @pytest.mark.requirement("SVF-DEV-120")
    def test_inject_writes_to_command_store(self) -> None:
        """ctx.inject() writes to CommandStore."""
        master, store, cmd_store = make_minimal_master()
        ctx = ProcedureContext(master, store, cmd_store)
        ctx.inject("aocs.mag.power_enable", 1.0)
        entry = cmd_store.peek("aocs.mag.power_enable")
        assert entry is not None
        assert entry.value == pytest.approx(1.0)

    @pytest.mark.requirement("SVF-DEV-120")
    def test_assert_parameter_less_than_passes(self) -> None:
        """assert_parameter less_than passes when value < threshold."""
        master, store, cmd_store = make_minimal_master()
        store.write("x", 0.5, t=0.0, model_id="test")
        ctx = ProcedureContext(master, store, cmd_store)
        ctx.assert_parameter("x", less_than=1.0)  # should not raise

    @pytest.mark.requirement("SVF-DEV-120")
    def test_assert_parameter_less_than_fails(self) -> None:
        """assert_parameter less_than raises when value >= threshold."""
        master, store, cmd_store = make_minimal_master()
        store.write("x", 2.0, t=0.0, model_id="test")
        ctx = ProcedureContext(master, store, cmd_store)
        with pytest.raises(ProcedureError):
            ctx.assert_parameter("x", less_than=1.0)

    @pytest.mark.requirement("SVF-DEV-120")
    def test_assert_missing_parameter_raises(self) -> None:
        """assert_parameter raises when parameter not in store."""
        master, store, cmd_store = make_minimal_master()
        ctx = ProcedureContext(master, store, cmd_store)
        with pytest.raises(ProcedureError, match="not found"):
            ctx.assert_parameter("nonexistent.param", less_than=1.0)

    @pytest.mark.requirement("SVF-DEV-120")
    def test_step_names_captured(self) -> None:
        """Step names are captured in ProcedureResult."""
        master, store, cmd_store = make_minimal_master()
        store.write("test.param", 1.0, t=0.0, model_id="test")
        result = PassingProcedure().execute(master, store, cmd_store)
        step_names = [s.step_name for s in result.steps]
        assert any("Verify" in n for n in step_names)

    @pytest.mark.requirement("SVF-DEV-120")
    def test_summary_contains_verdict(self) -> None:
        """ProcedureResult.summary() includes verdict string."""
        master, store, cmd_store = make_minimal_master()
        store.write("test.param", 1.0, t=0.0, model_id="test")
        result = PassingProcedure().execute(master, store, cmd_store)
        summary = result.summary()
        assert "PASS" in summary
        assert "TC-TEST-001" in summary
