"""
Tests for Equipment abstract base class.
Implements: SVF-DEV-004
"""

import pytest
from svf.equipment import Equipment, PortDefinition, PortDirection


# ── Test equipment implementations ───────────────────────────────────────────

class _SimpleSource(Equipment):
    """Minimal equipment with one output port."""

    def _declare_ports(self) -> list[PortDefinition]:
        return [
            PortDefinition("power_out", PortDirection.OUT, unit="W"),
        ]

    def initialise(self, start_time: float = 0.0) -> None:
        self._power = 10.0

    def do_step(self, t: float, dt: float) -> None:
        self.write_port("power_out", self._power)


class _SimpleSink(Equipment):
    """Minimal equipment with one input port."""

    def _declare_ports(self) -> list[PortDefinition]:
        return [
            PortDefinition("power_in", PortDirection.IN, unit="W"),
        ]

    def initialise(self, start_time: float = 0.0) -> None:
        self.received: list[float] = []

    def do_step(self, t: float, dt: float) -> None:
        self.received.append(self.read_port("power_in"))


class _BidirectionalEquipment(Equipment):
    """Equipment with both IN and OUT ports."""

    def _declare_ports(self) -> list[PortDefinition]:
        return [
            PortDefinition("enable", PortDirection.IN),
            PortDefinition("speed", PortDirection.OUT, unit="rpm"),
            PortDefinition("status", PortDirection.OUT),
        ]

    def initialise(self, start_time: float = 0.0) -> None:
        self._speed = 0.0

    def do_step(self, t: float, dt: float) -> None:
        enabled = self.read_port("enable")
        if enabled > 0.5:
            self._speed += 100.0 * dt
        self.write_port("speed", self._speed)
        self.write_port("status", 1.0 if enabled > 0.5 else 0.0)


# ── Construction tests ────────────────────────────────────────────────────────

def test_equipment_construction() -> None:
    """Equipment constructs with correct id and ports."""
    eq = _SimpleSource("source_1")
    assert eq.equipment_id == "source_1"
    assert "power_out" in eq.ports


def test_equipment_port_directions() -> None:
    """in_ports() and out_ports() filter correctly."""
    eq = _BidirectionalEquipment("bi_eq")
    assert len(eq.in_ports()) == 1
    assert len(eq.out_ports()) == 2
    assert eq.in_ports()[0].name == "enable"


def test_equipment_duplicate_port_raises() -> None:
    """Duplicate port name raises ValueError."""
    class _DuplicatePort(Equipment):
        def _declare_ports(self) -> list[PortDefinition]:
            return [
                PortDefinition("power", PortDirection.OUT),
                PortDefinition("power", PortDirection.IN),
            ]
        def initialise(self, start_time: float = 0.0) -> None: pass
        def do_step(self, t: float, dt: float) -> None: pass

    with pytest.raises(ValueError, match="duplicate port"):
        _DuplicatePort("bad")


# ── Port read/write tests ─────────────────────────────────────────────────────

def test_write_port_out() -> None:
    """write_port() sets OUT port value."""
    eq = _SimpleSource("src")
    eq.initialise()
    eq.do_step(0.0, 0.1)
    assert eq.read_port("power_out") == pytest.approx(10.0)


def test_write_port_to_in_raises() -> None:
    """write_port() on IN port raises ValueError."""
    eq = _SimpleSink("sink")
    eq.initialise()
    with pytest.raises(ValueError, match="Cannot write to IN port"):
        eq.write_port("power_in", 5.0)


def test_read_port_unknown_raises() -> None:
    """read_port() on unknown port raises ValueError."""
    eq = _SimpleSource("src")
    with pytest.raises(ValueError, match="Unknown port"):
        eq.read_port("nonexistent")


def test_port_default_value_is_zero() -> None:
    """Unwritten port defaults to 0.0."""
    eq = _SimpleSink("sink")
    assert eq.read_port("power_in") == pytest.approx(0.0)


# ── receive() tests ───────────────────────────────────────────────────────────

def test_receive_into_in_port() -> None:
    """receive() injects value into IN port."""
    eq = _SimpleSink("sink")
    eq.initialise()
    eq.receive("power_in", 42.0)
    assert eq.read_port("power_in") == pytest.approx(42.0)


def test_receive_into_out_port_raises() -> None:
    """receive() on OUT port raises ValueError."""
    eq = _SimpleSource("src")
    with pytest.raises(ValueError, match="Cannot receive into OUT port"):
        eq.receive("power_out", 1.0)


def test_receive_unknown_port_raises() -> None:
    """receive() on unknown port raises ValueError."""
    eq = _SimpleSource("src")
    with pytest.raises(ValueError, match="Unknown port"):
        eq.receive("nonexistent", 1.0)


# ── Integration: source -> sink ───────────────────────────────────────────────

def test_source_to_sink_wiring() -> None:
    """Source OUT port wired to sink IN port via receive()."""
    source = _SimpleSource("src")
    sink = _SimpleSink("sink")

    source.initialise()
    sink.initialise()

    # Tick source — produces output
    source.do_step(0.0, 0.1)

    # Master applies wiring: source.power_out -> sink.power_in
    sink.receive("power_in", source.read_port("power_out"))

    # Tick sink — reads wired value
    sink.do_step(0.1, 0.1)

    assert sink.received[-1] == pytest.approx(10.0)


def test_bidirectional_equipment_step() -> None:
    """Equipment reads IN port and writes OUT port correctly."""
    eq = _BidirectionalEquipment("rw")
    eq.initialise()

    # Not enabled — speed stays 0
    eq.do_step(0.0, 0.1)
    assert eq.read_port("speed") == pytest.approx(0.0)
    assert eq.read_port("status") == pytest.approx(0.0)

    # Enable — speed increases
    eq.receive("enable", 1.0)
    eq.do_step(0.1, 0.1)
    assert eq.read_port("speed") == pytest.approx(10.0)
    assert eq.read_port("status") == pytest.approx(1.0)
