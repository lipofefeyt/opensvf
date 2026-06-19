"""
Tests for SharedMemorySyncProtocol.
Implements: SVF-DEV-018
"""

import threading
import time
import uuid
from collections.abc import Iterator

import pytest

from svf.core.abstractions import SyncProtocol
from svf.ground.shm_sync import SharedMemorySyncProtocol


def _unique_name() -> str:
    return f"svftest{uuid.uuid4().hex[:10]}"


@pytest.fixture
def shm() -> Iterator[SharedMemorySyncProtocol]:
    """Two-slot SharedMemorySyncProtocol for mag and gyro."""
    proto = SharedMemorySyncProtocol(model_ids=["mag", "gyro"])
    yield proto
    proto.close()


# ── Basic correctness ─────────────────────────────────────────────────────────

@pytest.mark.requirement("SVF-DEV-018")
def test_shm_sync_implements_sync_protocol(shm: SharedMemorySyncProtocol) -> None:
    assert isinstance(shm, SyncProtocol)


@pytest.mark.requirement("SVF-DEV-018")
def test_shm_sync_single_model_sequential_roundtrip() -> None:
    """publish_ready then wait_for_ready returns True immediately (flags already set)."""
    proto = SharedMemorySyncProtocol(model_ids=["obc"])
    proto.reset()
    proto.publish_ready("obc", 1.0)
    assert proto.wait_for_ready(["obc"], timeout=0.01) is True
    proto.close()


@pytest.mark.requirement("SVF-DEV-018")
def test_shm_sync_timeout_when_not_published() -> None:
    """wait_for_ready returns False when no model publishes within the timeout."""
    proto = SharedMemorySyncProtocol(model_ids=["obc"])
    proto.reset()
    result = proto.wait_for_ready(["obc"], timeout=0.02)
    assert result is False
    proto.close()


@pytest.mark.requirement("SVF-DEV-018")
def test_shm_sync_multi_model_all_publish(shm: SharedMemorySyncProtocol) -> None:
    """wait_for_ready returns True only when all expected models have published."""
    shm.reset()
    shm.publish_ready("mag", 0.1)
    shm.publish_ready("gyro", 0.1)
    assert shm.wait_for_ready(["mag", "gyro"], timeout=0.01) is True


@pytest.mark.requirement("SVF-DEV-018")
def test_shm_sync_partial_publish_timeout(shm: SharedMemorySyncProtocol) -> None:
    """Only one of two models publishes  -  wait_for_ready must time out."""
    shm.reset()
    shm.publish_ready("mag", 0.1)
    # "gyro" never publishes
    assert shm.wait_for_ready(["mag", "gyro"], timeout=0.02) is False


@pytest.mark.requirement("SVF-DEV-018")
def test_shm_sync_reset_clears_flags(shm: SharedMemorySyncProtocol) -> None:
    """After reset(), previously published flags no longer satisfy wait_for_ready."""
    shm.reset()
    shm.publish_ready("mag", 1.0)
    shm.publish_ready("gyro", 1.0)
    shm.reset()
    assert shm.wait_for_ready(["mag", "gyro"], timeout=0.02) is False


# ── Concurrency ───────────────────────────────────────────────────────────────

@pytest.mark.requirement("SVF-DEV-018")
def test_shm_sync_thread_publisher_unblocks_wait() -> None:
    """Publisher running in a separate thread unblocks a waiting spinwait."""
    proto = SharedMemorySyncProtocol(model_ids=["str"])
    proto.reset()

    def publish_after_delay() -> None:
        time.sleep(0.005)
        proto.publish_ready("str", 2.0)

    t = threading.Thread(target=publish_after_delay, daemon=True)
    t.start()
    result = proto.wait_for_ready(["str"], timeout=0.5)
    t.join()
    proto.close()
    assert result is True


# ── Multi-process cross-instance ──────────────────────────────────────────────

@pytest.mark.requirement("SVF-DEV-018")
def test_shm_sync_attach_mode_sees_creator_flags() -> None:
    """
    An attached instance shares the same memory as the creator.
    Publisher on attacher, waiter on creator  -  simulates cross-process use.
    """
    name = _unique_name()
    creator = SharedMemorySyncProtocol(model_ids=["rw"], name=name, create=True)
    attacher = SharedMemorySyncProtocol(model_ids=["rw"], name=name, create=False)

    creator.reset()
    attacher.publish_ready("rw", 5.0)
    result = creator.wait_for_ready(["rw"], timeout=0.01)

    attacher.close()  # non-creator: close without unlink
    creator.close()   # creator: close + unlink

    assert result is True


# ── Integration with SimulationMaster ────────────────────────────────────────

@pytest.mark.requirement("SVF-DEV-018")
def test_shm_sync_drives_simulation_master() -> None:
    """SharedMemorySyncProtocol works as a drop-in in SimulationMaster."""
    from svf.sim.simulation import SimulationMaster
    from svf.sim.software_tick import SoftwareTickSource
    from svf.core.native_equipment import NativeEquipment
    from svf.core.equipment import PortDefinition, PortDirection
    from svf.stores.parameter_store import ParameterStore
    from svf.stores.command_store import CommandStore

    store = ParameterStore()
    cmd_store = CommandStore()
    ticks: list[float] = []

    sync = SharedMemorySyncProtocol(model_ids=["counter"])

    def step(eq: NativeEquipment, t: float, _dt: float) -> None:
        ticks.append(round(t, 6))
        eq.write_port("counter.value", t)

    eq = NativeEquipment(
        equipment_id="counter",
        ports=[PortDefinition("counter.value", PortDirection.OUT)],
        step_fn=step,
        sync_protocol=sync,
        store=store,
        command_store=cmd_store,
    )

    master = SimulationMaster(
        tick_source=SoftwareTickSource(),
        sync_protocol=sync,
        models=[eq],
        dt=0.1,
        stop_time=0.3,
        param_store=store,
        command_store=cmd_store,
    )
    master.run()
    sync.close()

    assert len(ticks) == 3
    assert ticks[0] == pytest.approx(0.0, abs=1e-9)
    assert ticks[2] == pytest.approx(0.2, abs=1e-9)
