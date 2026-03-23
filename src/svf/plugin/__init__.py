"""
SVF pytest Plugin
Registers SVF fixtures and hooks with pytest.
Implements: SVF-DEV-040, SVF-DEV-041, SVF-DEV-044
"""

from __future__ import annotations

import pytest

from typing import cast as typing_cast
from typing import Generator
from svf.plugin.fixtures import svf_participant, svf_session, FmuConfig
from svf.plugin.verdict import Verdict, VerdictRecorder
from svf.plugin.observable import ObservableFactory, ConditionNotMet


def pytest_configure(config: pytest.Config) -> None:
    """Register SVF custom marks."""
    config.addinivalue_line(
        "markers",
        "svf_fmus(configs): list of FmuConfig objects for this test"
    )
    config.addinivalue_line(
        "markers",
        "svf_dt(dt): simulation timestep in seconds"
    )
    config.addinivalue_line(
        "markers",
        "svf_stop_time(t): simulation stop time in seconds"
    )


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(
    item: pytest.Item,
    call: pytest.CallInfo,  # type: ignore[type-arg]
) -> Generator[None, None, None]:
    """
    Capture test outcome and attach it to the item so the
    svf_session fixture can record the correct verdict.
    """
    outcome = yield
    rep = typing_cast(object, outcome).get_result()  # type: ignore[attr-defined]
    
    if rep.when == "call":
        item._svf_rep = rep  # type: ignore[attr-defined]


__all__ = [
    "svf_participant",
    "svf_session",
    "FmuConfig",
    "Verdict",
    "VerdictRecorder",
    "ObservableFactory",
    "ConditionNotMet",
]