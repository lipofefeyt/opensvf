"""
Tests for SRDB runtime validation in ParameterStore and CommandStore.
Implements: SVF-DEV-094, SVF-DEV-095
"""

import logging
import pytest
from pathlib import Path

from svf.stores.parameter_store import ParameterStore
from svf.stores.command_store import CommandStore
from svf.srdb.loader import SrdbLoader
from svf.srdb.definitions import Classification, Domain, Dtype, ParameterDefinition


@pytest.fixture
def srdb():  # type: ignore[no-untyped-def]
    """Load EPS baseline SRDB for validation tests."""
    baseline = Path(__file__).parent.parent.parent / "srdb" / "baseline" / "eps.yaml"
    loader = SrdbLoader()
    loader.load_baseline(baseline)
    return loader.build()


# ── ParameterStore validation ─────────────────────────────────────────────────

@pytest.mark.requirement("SVF-DEV-094")
def test_parameter_store_no_srdb_no_warnings(
    caplog: pytest.LogCaptureFixture
) -> None:
    """Without SRDB, no warnings are emitted."""
    store = ParameterStore()
    with caplog.at_level(logging.WARNING):
        store.write("anything", value=999.0, t=0.1, model_id="test")
    assert "SRDB" not in caplog.text


@pytest.mark.requirement("SVF-DEV-094")
def test_parameter_store_valid_value_no_warning(
    srdb: object, caplog: pytest.LogCaptureFixture
) -> None:
    """Valid value within range produces no warning."""
    store = ParameterStore(srdb=srdb)  # type: ignore[arg-type]
    with caplog.at_level(logging.WARNING):
        store.write("eps.battery.soc", value=0.8, t=0.1, model_id="eps")
    assert "outside valid range" not in caplog.text


@pytest.mark.requirement("SVF-DEV-094")
def test_parameter_store_range_violation_warns(
    srdb: object, caplog: pytest.LogCaptureFixture
) -> None:
    """Value outside valid_range emits a warning."""
    store = ParameterStore(srdb=srdb)  # type: ignore[arg-type]
    with caplog.at_level(logging.WARNING):
        store.write("eps.battery.soc", value=1.5, t=0.1, model_id="eps")
    assert "outside valid range" in caplog.text
    assert "eps.battery.soc" in caplog.text


@pytest.mark.requirement("SVF-DEV-095")
def test_parameter_store_tc_write_warns(
    srdb: object, caplog: pytest.LogCaptureFixture
) -> None:
    """Writing to a TC-classified parameter emits a warning."""
    store = ParameterStore(srdb=srdb)  # type: ignore[arg-type]
    with caplog.at_level(logging.WARNING):
        # eps.solar_array.illumination is TC-classified
        store.write("eps.solar_array.illumination", value=0.5, t=0.1, model_id="eps")
    assert "TC-classified" in caplog.text


@pytest.mark.requirement("SVF-DEV-094")
def test_parameter_store_unknown_parameter_no_warning(
    srdb: object, caplog: pytest.LogCaptureFixture
) -> None:
    """Unknown parameter emits debug log only, not a warning."""
    store = ParameterStore(srdb=srdb)  # type: ignore[arg-type]
    with caplog.at_level(logging.WARNING):
        store.write("unknown.parameter", value=1.0, t=0.1, model_id="test")
    assert "SRDB" not in caplog.text


@pytest.mark.requirement("SVF-DEV-094")
def test_parameter_store_warning_does_not_raise(
    srdb: object
) -> None:
    """Range violation warning never raises an exception — simulation continues."""
    store = ParameterStore(srdb=srdb)  # type: ignore[arg-type]
    # Should not raise even with out-of-range value
    store.write("eps.battery.soc", value=999.0, t=0.1, model_id="eps")
    entry = store.read("eps.battery.soc")
    assert entry is not None
    assert entry.value == pytest.approx(999.0)


# ── CommandStore validation ───────────────────────────────────────────────────

@pytest.mark.requirement("SVF-DEV-095")
def test_command_store_no_srdb_no_warnings(
    caplog: pytest.LogCaptureFixture
) -> None:
    """Without SRDB, no warnings are emitted."""
    store = CommandStore()
    with caplog.at_level(logging.WARNING):
        store.inject("anything", value=1.0)
    assert "SRDB" not in caplog.text


@pytest.mark.requirement("SVF-DEV-095")
def test_command_store_valid_tc_no_warning(
    srdb: object, caplog: pytest.LogCaptureFixture
) -> None:
    """Injecting to a valid TC parameter produces no warning."""
    store = CommandStore(srdb=srdb)  # type: ignore[arg-type]
    with caplog.at_level(logging.WARNING):
        store.inject("eps.solar_array.illumination", value=1.0)
    assert "TM-classified" not in caplog.text
    assert "outside valid range" not in caplog.text


@pytest.mark.requirement("SVF-DEV-095")
def test_command_store_tm_inject_warns(
    srdb: object, caplog: pytest.LogCaptureFixture
) -> None:
    """Injecting to a TM-classified parameter emits a warning."""
    store = CommandStore(srdb=srdb)  # type: ignore[arg-type]
    with caplog.at_level(logging.WARNING):
        # eps.battery.soc is TM-classified
        store.inject("eps.battery.soc", value=0.5)
    assert "TM-classified" in caplog.text


@pytest.mark.requirement("SVF-DEV-095")
def test_command_store_range_violation_warns(
    srdb: object, caplog: pytest.LogCaptureFixture
) -> None:
    """Command value outside valid_range emits a warning."""
    store = CommandStore(srdb=srdb)  # type: ignore[arg-type]
    with caplog.at_level(logging.WARNING):
        # eps.solar_array.illumination valid range is [0.0, 1.0]
        store.inject("eps.solar_array.illumination", value=2.0)
    assert "outside valid range" in caplog.text


@pytest.mark.requirement("SVF-DEV-095")
def test_command_store_warning_does_not_raise(
    srdb: object
) -> None:
    """TM injection warning never raises — command still stored."""
    store = CommandStore(srdb=srdb)  # type: ignore[arg-type]
    store.inject("eps.battery.soc", value=0.5)
    entry = store.peek("eps.battery.soc")
    assert entry is not None
    assert entry.value == pytest.approx(0.5)
