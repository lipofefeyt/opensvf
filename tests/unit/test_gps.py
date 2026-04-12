"""Tests for GPS Receiver Equipment model."""
from __future__ import annotations
import pytest
from svf.abstractions import SyncProtocol
from svf.parameter_store import ParameterStore
from svf.command_store import CommandStore
from svf.models.gps import (
    make_gps, STATUS_OFF, STATUS_ACQUIRING, STATUS_FIX,
    STATUS_ECLIPSE_OUTAGE, ACQUISITION_TIME_S
)
from svf.native_equipment import NativeEquipment


class _NoSync(SyncProtocol):
    def reset(self) -> None: pass
    def publish_ready(self, model_id: str, t: float) -> None: pass
    def wait_for_ready(self, expected: list[str], timeout: float) -> bool:
        return True


@pytest.fixture
def gps() -> NativeEquipment:
    eq = make_gps(_NoSync(), ParameterStore(), CommandStore(), seed=42)
    eq.initialise()
    eq.receive("gps.power_enable", 1.0)
    # Inject truth state (LEO ~500km)
    eq.receive("gps.truth.pos_x", 6_871_000.0)
    eq.receive("gps.truth.pos_y", 0.0)
    eq.receive("gps.truth.pos_z", 0.0)
    eq.receive("gps.truth.vel_x", 0.0)
    eq.receive("gps.truth.vel_y", 7613.0)
    eq.receive("gps.truth.vel_z", 0.0)
    eq.receive("gps.eclipse", 0.0)
    return eq


class TestGpsSuite:

    @pytest.mark.requirement("SVF-DEV-081")
    def test_no_fix_during_acquisition(self, gps: NativeEquipment) -> None:
        """GPS has no fix during acquisition period."""
        gps.do_step(t=0.0, dt=0.1)
        assert gps.read_port("gps.fix") == pytest.approx(0.0)
        assert gps.read_port("gps.status") == STATUS_ACQUIRING

    @pytest.mark.requirement("SVF-DEV-081")
    def test_fix_after_acquisition(self, gps: NativeEquipment) -> None:
        """GPS provides fix after acquisition period."""
        gps.do_step(t=ACQUISITION_TIME_S + 1.0, dt=0.1)
        assert gps.read_port("gps.fix") == pytest.approx(1.0)
        assert gps.read_port("gps.status") == STATUS_FIX

    @pytest.mark.requirement("SVF-DEV-081")
    def test_position_close_to_truth(self, gps: NativeEquipment) -> None:
        """GPS position is within noise bounds of truth."""
        gps.do_step(t=ACQUISITION_TIME_S + 1.0, dt=0.1)
        px = gps.read_port("gps.position_x")
        assert abs(px - 6_871_000.0) < 50.0  # within 10-sigma

    @pytest.mark.requirement("SVF-DEV-081")
    def test_altitude_computed(self, gps: NativeEquipment) -> None:
        """GPS altitude is ~500km for LEO truth state."""
        gps.do_step(t=ACQUISITION_TIME_S + 1.0, dt=0.1)
        alt = gps.read_port("gps.altitude_km")
        assert 490.0 < alt < 510.0

    @pytest.mark.requirement("SVF-DEV-081")
    def test_no_fix_when_unpowered(self, gps: NativeEquipment) -> None:
        """GPS has no fix when unpowered."""
        gps.receive("gps.power_enable", 0.0)
        gps.do_step(t=ACQUISITION_TIME_S + 1.0, dt=0.1)
        assert gps.read_port("gps.fix") == pytest.approx(0.0)
        assert gps.read_port("gps.status") == STATUS_OFF

    @pytest.mark.requirement("SVF-DEV-081")
    def test_eclipse_outage(self, gps: NativeEquipment) -> None:
        """GPS loses fix during eclipse when eclipse_outage=True."""
        gps.receive("gps.eclipse", 1.0)
        gps.do_step(t=ACQUISITION_TIME_S + 1.0, dt=0.1)
        assert gps.read_port("gps.fix") == pytest.approx(0.0)
        assert gps.read_port("gps.status") == STATUS_ECLIPSE_OUTAGE
