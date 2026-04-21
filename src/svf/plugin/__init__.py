
"""
SVF pytest Plugin
Registers SVF fixtures and hooks with pytest.
Implements: SVF-DEV-040, SVF-DEV-041, SVF-DEV-044
"""

from __future__ import annotations
import sys as _sys
import os as _os
_src = _os.path.normpath(_os.path.join(_os.path.dirname(__file__), "..", "..", ".."))
if _src not in _sys.path:
    _sys.path.insert(0, _src)


import pytest
import pluggy

from typing import cast as typing_cast
from typing import Any, Generator
from svf.plugin.fixtures import svf_participant, svf_session, FmuConfig
from svf.plugin.verdict import Verdict, VerdictRecorder
from svf.plugin.observable import ObservableFactory, ConditionNotMet

# Global registry of DDS participants for explicit cleanup at session end
_dds_participants: list[Any] = []


def _register_participant(p: Any) -> Any:
    """Register a DomainParticipant for cleanup at session end."""
    _dds_participants.append(p)
    return p


def pytest_terminal_summary(
    terminalreporter: pytest.TerminalReporter,
    exitstatus: int,
    config: pytest.Config,
) -> None:
    """
    After the test run, generate a requirements traceability matrix.
    Writes to results/traceability.txt.
    Implements: SVF-DEV-073
    """
    import os
    from pathlib import Path
    from collections import defaultdict

    # Collect all requirement markers from test reports
    matrix: dict[str, list[tuple[str, str]]] = defaultdict(list)

    for report in terminalreporter.stats.get("passed", []):
        _collect_requirements(report, matrix, "PASS")
    for report in terminalreporter.stats.get("failed", []):
        _collect_requirements(report, matrix, "FAIL")
    for report in terminalreporter.stats.get("error", []):
        _collect_requirements(report, matrix, "ERROR")

    if not matrix:
        return

    # Write traceability matrix
    output_dir = Path("results")
    output_dir.mkdir(exist_ok=True)
    output_file = output_dir / "traceability.txt"

    lines = [
        "SVF Requirements Traceability Matrix",
        "=" * 60,
        f"{'Requirement':<20} {'Verdict':<12} {'Test Case'}",
        "-" * 60,
    ]

    for req_id in sorted(matrix.keys()):
        for test_id, verdict in sorted(matrix[req_id]):
            short_test = test_id.split("::")[-1]
            lines.append(f"{req_id:<20} {verdict:<12} {short_test}")

    lines.append("-" * 60)
    lines.append(f"Total requirements covered: {len(matrix)}")

    output_file.write_text("\n".join(lines))
    terminalreporter.write_sep(
        "-", f"Traceability matrix written to {output_file}"
    )


def _collect_requirements(
    report: pytest.TestReport,
    matrix: dict[str, list[tuple[str, str]]],
    verdict: str,
) -> None:
    """Extract requirement markers from a test report."""
    markers = getattr(report, "own_markers", [])
    for marker in markers:
        if marker.name == "requirement":
            for req_id in marker.args:
                matrix[req_id].append((report.nodeid, verdict))
                

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
    config.addinivalue_line(
        "markers",
        "requirement(*ids): requirement IDs verified by this test case"
    )
    config.addinivalue_line(
        "markers",
        "svf_initial_commands(cmds): list of (name, value) tuples injected before simulation starts"
    )
    config.addinivalue_line(
        "markers",
        "svf_command_schedule(cmds): list of (sim_time, name, value) "
        "tuples fired at specific simulation times"
    )


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(
    item: pytest.Item,
    call: pytest.CallInfo,  # type: ignore[type-arg]
) -> Generator[None, pluggy.Result, None]:  # type: ignore[type-arg]
    outcome: pluggy.Result = yield  # type: ignore[type-arg]
    rep = outcome.get_result()
    if rep.when == "call":
        item._svf_rep = rep  # type: ignore[attr-defined]


        # Add ECSS verdict and requirement IDs as JUnit XML properties
        from svf.plugin.verdict import Verdict
        if rep.passed:
            verdict = Verdict.PASS.value
        elif rep.failed:
            verdict = Verdict.FAIL.value
        else:
            verdict = Verdict.INCONCLUSIVE.value

        item.user_properties.append(("ecss_verdict", verdict))

        for marker in item.own_markers:
            if marker.name == "requirement":
                for req_id in marker.args:
                    item.user_properties.append(("requirement", req_id))

__all__ = [
    "svf_participant",
    "svf_session",
    "FmuConfig",
    "Verdict",
    "VerdictRecorder",
    "ObservableFactory",
    "ConditionNotMet",
]

def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Explicitly delete all DDS participants before Python shuts down."""
    import gc
    # Delete all tracked participants explicitly
    for p in _dds_participants:
        try:
            p._delete()
        except Exception:
            pass
    _dds_participants.clear()
    gc.collect()
    gc.collect()
    gc.collect()
