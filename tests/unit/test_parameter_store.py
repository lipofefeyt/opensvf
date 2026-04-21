"""
Tests for ParameterStore.
Implements: SVF-DEV-031, SVF-DEV-032, SVF-DEV-033
"""

import pytest
import threading
from svf.stores.parameter_store import ParameterStore, ParameterEntry


@pytest.mark.requirement("SVF-DEV-031", "SVF-DEV-032")
def test_write_and_read() -> None:
    """Written value is immediately readable."""
    store = ParameterStore()
    store.write("voltage", value=3.7, t=0.1, model_id="power")
    entry = store.read("voltage")
    assert entry is not None
    assert entry.value == pytest.approx(3.7)
    assert entry.t == pytest.approx(0.1)
    assert entry.model_id == "power"


@pytest.mark.requirement("SVF-DEV-033")
def test_read_unknown_parameter() -> None:
    """Reading an unknown parameter returns None."""
    store = ParameterStore()
    assert store.read("nonexistent") is None


@pytest.mark.requirement("SVF-DEV-033")
def test_overwrite_returns_latest() -> None:
    """Second write overwrites the first — reader always gets latest."""
    store = ParameterStore()
    store.write("voltage", value=3.7, t=0.1, model_id="power")
    store.write("voltage", value=3.9, t=0.2, model_id="power")
    entry = store.read("voltage")
    assert entry is not None
    assert entry.value == pytest.approx(3.9)
    assert entry.t == pytest.approx(0.2)


@pytest.mark.requirement("SVF-DEV-033")
def test_snapshot_returns_full_state() -> None:
    """Snapshot returns all current parameter values."""
    store = ParameterStore()
    store.write("voltage", value=3.7, t=0.1, model_id="power")
    store.write("temperature", value=25.0, t=0.1, model_id="thermal")
    snap = store.snapshot()
    assert "voltage" in snap
    assert "temperature" in snap
    assert snap["voltage"].value == pytest.approx(3.7)
    assert snap["temperature"].value == pytest.approx(25.0)


@pytest.mark.requirement("SVF-DEV-033")
def test_snapshot_is_a_copy() -> None:
    """Modifying snapshot does not affect the store."""
    store = ParameterStore()
    store.write("voltage", value=3.7, t=0.1, model_id="power")
    snap = store.snapshot()
    snap.clear()
    assert store.read("voltage") is not None


@pytest.mark.requirement("SVF-DEV-031")
def test_clear() -> None:
    """Clear removes all parameters."""
    store = ParameterStore()
    store.write("voltage", value=3.7, t=0.1, model_id="power")
    store.clear()
    assert store.read("voltage") is None
    assert len(store) == 0


@pytest.mark.requirement("SVF-DEV-031")
def test_parameter_names() -> None:
    """parameter_names returns all written parameter names."""
    store = ParameterStore()
    store.write("voltage", value=3.7, t=0.1, model_id="power")
    store.write("temperature", value=25.0, t=0.1, model_id="thermal")
    assert set(store.parameter_names) == {"voltage", "temperature"}


@pytest.mark.requirement("SVF-DEV-033")
def test_late_reader_sees_value() -> None:
    """A reader that connects after a write still sees the value."""
    store = ParameterStore()
    store.write("voltage", value=3.7, t=0.1, model_id="power")
    # Reader connects "late" — no subscription needed
    entry = store.read("voltage")
    assert entry is not None
    assert entry.value == pytest.approx(3.7)


@pytest.mark.requirement("SVF-DEV-031")
def test_concurrent_writes_are_safe() -> None:
    """Concurrent writes from multiple threads do not corrupt the store."""
    store = ParameterStore()
    errors: list[Exception] = []

    def writer(model_id: str, value: float) -> None:
        try:
            for i in range(100):
                store.write("voltage", value=value + i, t=float(i), model_id=model_id)
        except Exception as e:
            errors.append(e)

    threads = [
        threading.Thread(target=writer, args=(f"model_{i}", float(i)))
        for i in range(5)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    entry = store.read("voltage")
    assert entry is not None


@pytest.mark.requirement("SVF-DEV-031")
def test_concurrent_reads_are_safe() -> None:
    """Concurrent reads while writing do not raise."""
    store = ParameterStore()
    errors: list[Exception] = []

    def writer() -> None:
        for i in range(100):
            store.write("voltage", value=float(i), t=float(i), model_id="power")

    def reader() -> None:
        try:
            for _ in range(100):
                store.read("voltage")
        except Exception as e:
            errors.append(e)

    threads = (
        [threading.Thread(target=writer)] +
        [threading.Thread(target=reader) for _ in range(4)]
    )
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
