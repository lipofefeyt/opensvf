"""
Tests for WiringLoader and WiringMap.
Implements: SVF-DEV-004
"""

import pytest
from pathlib import Path
from svf.equipment import Equipment, PortDefinition, PortDirection
from svf.wiring import WiringLoader, WiringMap, WiringLoadError, Connection
from svf.abstractions import SyncProtocol
from svf.parameter_store import ParameterStore
from svf.command_store import CommandStore

class _NoSync(SyncProtocol):
    def reset(self) -> None: pass
    def publish_ready(self, model_id: str, t: float) -> None: pass
    def wait_for_ready(self, expected: list[str], timeout: float) -> bool: return True

# ── Test equipment ────────────────────────────────────────────────────────────

class _Source(Equipment):
    def __init__(self, equipment_id: str, sync_protocol: SyncProtocol, store: ParameterStore) -> None:
        super().__init__(equipment_id, sync_protocol=sync_protocol, store=store)

    def _declare_ports(self) -> list[PortDefinition]:
        return [PortDefinition("power_out", PortDirection.OUT, unit="W")]

    def initialise(self, start_time: float = 0.0) -> None: pass
    def do_step(self, t: float, dt: float) -> None: pass


class _Sink(Equipment):
    def __init__(self, equipment_id: str, sync_protocol: SyncProtocol, store: ParameterStore) -> None:
        super().__init__(equipment_id, sync_protocol=sync_protocol, store=store)

    def _declare_ports(self) -> list[PortDefinition]:
        return [PortDefinition("power_in", PortDirection.IN, unit="W")]

    def initialise(self, start_time: float = 0.0) -> None: pass
    def do_step(self, t: float, dt: float) -> None: pass

@pytest.fixture
def sync() -> _NoSync:
    return _NoSync()

@pytest.fixture
def store() -> ParameterStore:
    return ParameterStore()

@pytest.fixture
def equipment(sync: _NoSync, store: ParameterStore) -> dict[str, Equipment]:
    return {
        "source": _Source("source", sync_protocol=sync, store=store),
        "sink": _Sink("sink", sync_protocol=sync, store=store),
    }

@pytest.fixture
def valid_wiring_file(tmp_path: Path) -> Path:
    f = tmp_path / "wiring.yaml"
    f.write_text("""
connections:
  - from: source.power_out
    to: sink.power_in
    description: Power line from source to sink
""")
    return f


# ── WiringLoader tests ────────────────────────────────────────────────────────

@pytest.mark.requirement("SVF-DEV-004")
def test_load_valid_wiring(
    equipment: dict[str, Equipment],
    valid_wiring_file: Path,
) -> None:
    """Valid wiring YAML loads correctly."""
    loader = WiringLoader(equipment)
    wiring = loader.load(valid_wiring_file)
    assert len(wiring) == 1
    conn = wiring.connections[0]
    assert conn.from_equipment == "source"
    assert conn.from_port == "power_out"
    assert conn.to_equipment == "sink"
    assert conn.to_port == "power_in"
    assert conn.description == "Power line from source to sink"

@pytest.mark.requirement("SVF-DEV-004")
def test_missing_file_raises(equipment: dict[str, Equipment], tmp_path: Path) -> None:
    """Missing file raises WiringLoadError."""
    loader = WiringLoader(equipment)
    with pytest.raises(WiringLoadError, match="not found"):
        loader.load(tmp_path / "nonexistent.yaml")

@pytest.mark.requirement("SVF-DEV-004")
def test_unknown_equipment_raises(
    equipment: dict[str, Equipment], tmp_path: Path
) -> None:
    """Unknown equipment ID raises WiringLoadError."""
    f = tmp_path / "bad.yaml"
    f.write_text("""
connections:
  - from: unknown.power_out
    to: sink.power_in
""")
    loader = WiringLoader(equipment)
    with pytest.raises(WiringLoadError, match="unknown source equipment"):
        loader.load(f)

@pytest.mark.requirement("SVF-DEV-004")
def test_unknown_port_raises(
    equipment: dict[str, Equipment], tmp_path: Path
) -> None:
    """Unknown port name raises WiringLoadError."""
    f = tmp_path / "bad.yaml"
    f.write_text("""
connections:
  - from: source.nonexistent_port
    to: sink.power_in
""")
    loader = WiringLoader(equipment)
    with pytest.raises(WiringLoadError, match="unknown port"):
        loader.load(f)

@pytest.mark.requirement("SVF-DEV-004")
def test_in_port_as_source_raises(
    equipment: dict[str, Equipment], tmp_path: Path
) -> None:
    """Using IN port as connection source raises WiringLoadError."""
    f = tmp_path / "bad.yaml"
    f.write_text("""
connections:
  - from: sink.power_in
    to: sink.power_in
""")
    loader = WiringLoader(equipment)
    with pytest.raises(WiringLoadError, match="IN port"):
        loader.load(f)

@pytest.mark.requirement("SVF-DEV-004")
def test_out_port_as_destination_raises(
    equipment: dict[str, Equipment], tmp_path: Path
) -> None:
    """Using OUT port as connection destination raises WiringLoadError."""
    f = tmp_path / "bad.yaml"
    f.write_text("""
connections:
  - from: source.power_out
    to: source.power_out
""")
    loader = WiringLoader(equipment)
    with pytest.raises(WiringLoadError, match="OUT port"):
        loader.load(f)

@pytest.mark.requirement("SVF-DEV-004")
def test_duplicate_connection_raises(
    equipment: dict[str, Equipment], tmp_path: Path
) -> None:
    """Duplicate connection raises WiringLoadError."""
    f = tmp_path / "bad.yaml"
    f.write_text("""
connections:
  - from: source.power_out
    to: sink.power_in
  - from: source.power_out
    to: sink.power_in
""")
    loader = WiringLoader(equipment)
    with pytest.raises(WiringLoadError, match="duplicate"):
        loader.load(f)

@pytest.mark.requirement("SVF-DEV-004")
def test_missing_from_field_raises(
    equipment: dict[str, Equipment], tmp_path: Path
) -> None:
    """Missing 'from' field raises WiringLoadError."""
    f = tmp_path / "bad.yaml"
    f.write_text("""
connections:
  - to: sink.power_in
""")
    loader = WiringLoader(equipment)
    with pytest.raises(WiringLoadError, match="missing required field 'from'"):
        loader.load(f)


# ── WiringMap tests ───────────────────────────────────────────────────────────

@pytest.mark.requirement("SVF-DEV-004")
def test_wiring_map_connections_from(
    equipment: dict[str, Equipment],
    valid_wiring_file: Path,
) -> None:
    """connections_from() filters by source equipment."""
    loader = WiringLoader(equipment)
    wiring = loader.load(valid_wiring_file)
    assert len(wiring.connections_from("source")) == 1
    assert len(wiring.connections_from("sink")) == 0

@pytest.mark.requirement("SVF-DEV-004")
def test_wiring_map_connections_to(
    equipment: dict[str, Equipment],
    valid_wiring_file: Path,
) -> None:
    """connections_to() filters by destination equipment."""
    loader = WiringLoader(equipment)
    wiring = loader.load(valid_wiring_file)
    assert len(wiring.connections_to("sink")) == 1
    assert len(wiring.connections_to("source")) == 0

@pytest.mark.requirement("SVF-DEV-004")
def test_connection_str() -> None:
    """Connection __str__ is readable."""
    conn = Connection("pcdu", "bus.lcl1", "rw1", "power_enable")
    assert str(conn) == "pcdu.bus.lcl1 -> rw1.power_enable"
