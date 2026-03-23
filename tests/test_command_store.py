"""
Tests for CommandStore.
Implements: SVF-DEV-035, SVF-DEV-036
"""

import pytest
import threading
from svf.command_store import CommandStore, CommandEntry


def test_inject_and_take() -> None:
    """Injected command is immediately takeable."""
    store = CommandStore()
    store.inject("thruster_cmd", value=1.0, t=0.1, source_id="TC-001")
    entry = store.take("thruster_cmd")
    assert entry is not None
    assert entry.value == pytest.approx(1.0)
    assert entry.t == pytest.approx(0.1)
    assert entry.source_id == "TC-001"
    assert entry.consumed is True


def test_take_unknown_command() -> None:
    """Taking an unknown command returns None."""
    store = CommandStore()
    assert store.take("nonexistent") is None


def test_take_is_atomic() -> None:
    """Command can only be taken once — second take returns None."""
    store = CommandStore()
    store.inject("thruster_cmd", value=1.0, t=0.0, source_id="TC-001")
    first = store.take("thruster_cmd")
    second = store.take("thruster_cmd")
    assert first is not None
    assert second is None


def test_latest_command_wins() -> None:
    """Second inject overwrites first — latest command wins."""
    store = CommandStore()
    store.inject("thruster_cmd", value=1.0, t=0.0, source_id="TC-001")
    store.inject("thruster_cmd", value=2.0, t=0.1, source_id="TC-002")
    entry = store.take("thruster_cmd")
    assert entry is not None
    assert entry.value == pytest.approx(2.0)
    assert entry.source_id == "TC-002"


def test_peek_does_not_consume() -> None:
    """peek() does not mark command as consumed."""
    store = CommandStore()
    store.inject("thruster_cmd", value=1.0, t=0.0, source_id="TC-001")
    peeked = store.peek("thruster_cmd")
    taken = store.take("thruster_cmd")
    assert peeked is not None
    assert taken is not None
    assert taken.value == pytest.approx(1.0)


def test_peek_unknown_command() -> None:
    """peek() on unknown command returns None."""
    store = CommandStore()
    assert store.peek("nonexistent") is None


def test_pending_lists_unconsumed() -> None:
    """pending() returns names of unconsumed commands only."""
    store = CommandStore()
    store.inject("cmd_a", value=1.0, t=0.0, source_id="TC-001")
    store.inject("cmd_b", value=2.0, t=0.0, source_id="TC-002")
    store.take("cmd_a")
    assert store.pending() == ["cmd_b"]


def test_clear() -> None:
    """clear() removes all commands."""
    store = CommandStore()
    store.inject("cmd_a", value=1.0, t=0.0, source_id="TC-001")
    store.clear()
    assert store.take("cmd_a") is None
    assert len(store) == 0


def test_concurrent_inject_and_take() -> None:
    """Concurrent inject and take do not corrupt the store."""
    store = CommandStore()
    errors: list[Exception] = []

    def injector() -> None:
        try:
            for i in range(100):
                store.inject("cmd", value=float(i), t=float(i), source_id="tc")
        except Exception as e:
            errors.append(e)

    def taker() -> None:
        try:
            for _ in range(100):
                store.take("cmd")
        except Exception as e:
            errors.append(e)

    threads = (
        [threading.Thread(target=injector)] +
        [threading.Thread(target=taker) for _ in range(3)]
    )
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors


def test_inject_default_source_id() -> None:
    """Default source_id is 'test_procedure'."""
    store = CommandStore()
    store.inject("cmd", value=1.0, t=0.0)
    entry = store.peek("cmd")
    assert entry is not None
    assert entry.source_id == "test_procedure"
