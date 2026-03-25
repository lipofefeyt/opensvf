"""
SVF Integration Test — Equipment Wiring via SimulationMaster
Verifies that OUT port values flow to connected IN ports between ticks.
Implements: SVF-DEV-004
"""

import pytest
from pathlib import Path

from cyclonedds.domain import DomainParticipant

from svf.simulation import SimulationMaster
from svf.software_tick import SoftwareTickSource
from svf.dds_sync import DdsSyncProtocol
from svf.native_equipment import NativeEquipment
from svf.equipment import PortDefinition, PortDirection
from svf.parameter_store import ParameterStore
from svf.command_store import CommandStore
from svf.wiring import WiringLoader, WiringMap


@pytest.fixture
def participant() -> DomainParticipant:
    return DomainParticipant()


@pytest.fixture
def store() -> ParameterStore:
    return ParameterStore()


@pytest.fixture
def cmd_store() -> CommandStore:
    return CommandStore()


@pytest.fixture
def sync(participant: DomainParticipant) -> DdsSyncProtocol:
    return DdsSyncProtocol(participant)


def test_wiring_propagates_values(
    store: ParameterStore,
    cmd_store: CommandStore,
    sync: DdsSyncProtocol,
    tmp_path: Path,
) -> None:
    """
    Source equipment OUT port value propagates to sink equipment IN port
    via WiringMap applied by SimulationMaster after each tick.
    """
    received: list[float] = []

    def source_step(eq: NativeEquipment, t: float, dt: float) -> None:
        eq.write_port("power_out", 42.0)

    def sink_step(eq: NativeEquipment, t: float, dt: float) -> None:
        received.append(eq.read_port("power_in"))
        eq.write_port("status", 1.0)

    source = NativeEquipment(
        "source",
        [PortDefinition("power_out", PortDirection.OUT, unit="W")],
        source_step,
        sync,
        store,
        cmd_store,
    )
    sink = NativeEquipment(
        "sink",
        [
            PortDefinition("power_in", PortDirection.IN, unit="W"),
            PortDefinition("status", PortDirection.OUT),
        ],
        sink_step,
        sync,
        store,
        cmd_store,
    )

    # Create wiring YAML
    wiring_file = tmp_path / "wiring.yaml"
    wiring_file.write_text("""
connections:
  - from: source.power_out
    to: sink.power_in
    description: Power from source to sink
""")

    equipment = {"source": source, "sink": sink}
    loader = WiringLoader(equipment)
    wiring = loader.load(wiring_file)

    master = SimulationMaster(
        tick_source=SoftwareTickSource(),
        sync_protocol=sync,
        models=[source, sink],
        dt=0.1,
        stop_time=0.5,
        sync_timeout=5.0,
        wiring=wiring,
        command_store=cmd_store,
    )
    master.run()

    # First tick: sink gets default 0.0 (wiring applies after tick)
    # Ticks 2-5: sink gets 42.0 from source via wiring
    assert len(received) == 5
    assert received[0] == pytest.approx(0.0)  # first tick before wiring applies
    assert all(v == pytest.approx(42.0) for v in received[1:])


def test_wiring_multiple_connections(
    store: ParameterStore,
    cmd_store: CommandStore,
    sync: DdsSyncProtocol,
    tmp_path: Path,
) -> None:
    """Multiple wiring connections all propagate correctly."""
    log: dict[str, list[float]] = {"a": [], "b": []}

    def source_step(eq: NativeEquipment, t: float, dt: float) -> None:
        eq.write_port("out_a", 10.0)
        eq.write_port("out_b", 20.0)

    def sink_step(eq: NativeEquipment, t: float, dt: float) -> None:
        log["a"].append(eq.read_port("in_a"))
        log["b"].append(eq.read_port("in_b"))
        eq.write_port("dummy", 0.0)

    source = NativeEquipment(
        "source",
        [
            PortDefinition("out_a", PortDirection.OUT),
            PortDefinition("out_b", PortDirection.OUT),
        ],
        source_step,
        sync,
        store,
        cmd_store,
    )
    sink = NativeEquipment(
        "sink",
        [
            PortDefinition("in_a", PortDirection.IN),
            PortDefinition("in_b", PortDirection.IN),
            PortDefinition("dummy", PortDirection.OUT),
        ],
        sink_step,
        sync,
        store,
        cmd_store,
    )

    wiring_file = tmp_path / "wiring.yaml"
    wiring_file.write_text("""
connections:
  - from: source.out_a
    to: sink.in_a
  - from: source.out_b
    to: sink.in_b
""")

    equipment = {"source": source, "sink": sink}
    wiring = WiringLoader(equipment).load(wiring_file)

    master = SimulationMaster(
        tick_source=SoftwareTickSource(),
        sync_protocol=sync,
        models=[source, sink],
        dt=0.1,
        stop_time=0.3,
        sync_timeout=5.0,
        wiring=wiring,
        command_store=cmd_store,
    )
    master.run()

    # After first tick wiring applies — ticks 2+ should see correct values
    assert all(v == pytest.approx(10.0) for v in log["a"][1:])
    assert all(v == pytest.approx(20.0) for v in log["b"][1:])
