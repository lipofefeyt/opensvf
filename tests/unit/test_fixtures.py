"""
Tests for the simulation lifecycle fixture.
Implements: SVF-DEV-040, SVF-DEV-041
"""

import pytest
from pathlib import Path

from svf.plugin.fixtures import FmuConfig
from svf.plugin.verdict import Verdict
from svf.plugin.observable import ConditionNotMet

FMU_PATH = Path(__file__).parent.parent.parent / "examples" / "SimpleCounter.fmu"


@pytest.mark.requirement("SVF-DEV-041")
def test_fixture_default_fmu(svf_session) -> None:  # type: ignore[no-untyped-def]
    """
    Default fixture starts SimpleCounter FMU.
    Counter should reach 1.0 within 2s default stop time.
    """
    svf_session.observe("counter").reaches(1.0).within(3.0)


@pytest.mark.svf_stop_time(0.5)
@pytest.mark.requirement("SVF-DEV-041")
def test_fixture_custom_stop_time(svf_session) -> None:  # type: ignore[no-untyped-def]
    """Fixture respects svf_stop_time mark."""
    svf_session.observe("counter").reaches(0.4).within(2.0)


@pytest.mark.svf_dt(0.05)
@pytest.mark.svf_stop_time(1.0)
@pytest.mark.requirement("SVF-DEV-041")
def test_fixture_custom_dt(svf_session) -> None:  # type: ignore[no-untyped-def]
    """Fixture respects svf_dt mark — smaller dt means more steps."""
    svf_session.observe("counter").reaches(0.5).within(3.0)


@pytest.mark.svf_fmus([FmuConfig(FMU_PATH, "my_counter")])
@pytest.mark.requirement("SVF-DEV-041")
def test_fixture_explicit_fmu(svf_session) -> None:  # type: ignore[no-untyped-def]
    """Fixture accepts explicit FmuConfig via svf_fmus mark."""
    svf_session.observe("counter").reaches(1.0).within(3.0)


@pytest.mark.svf_stop_time(0.3)
@pytest.mark.requirement("SVF-DEV-043")
def test_fixture_condition_not_met(svf_session) -> None:  # type: ignore[no-untyped-def]
    """ConditionNotMet raised when condition never satisfied."""
    with pytest.raises(ConditionNotMet):
        svf_session.observe("counter").reaches(999.0).within(1.0)

@pytest.mark.requirement("SVF-DEV-042")
def test_fixture_inject_command(svf_session) -> None:  # type: ignore[no-untyped-def]
    """
    inject() writes to CommandStore without error.
    SimpleCounter has no inputs so command is injected but not consumed —
    this test verifies the API works and pending() reflects the state.
    """
    svf_session.inject("some_cmd", 1.0)
    pending = svf_session._cmd_store.pending()
    assert "some_cmd" in pending
