"""
Tests for PUS Service 17  -  Test (are-you-alive).
Implements: PUS-007
"""

import pytest
from svf.pus.tc import PusTcPacket
from svf.pus.services import PusService17


@pytest.fixture
def tc_s17() -> PusTcPacket:
    return PusTcPacket(apid=0x100, sequence_count=1, service=17, subservice=1)


@pytest.mark.requirement("PUS-007")
def test_s17_are_you_alive_detected(tc_s17: PusTcPacket) -> None:
    """is_are_you_alive() correctly identifies TC(17,1)."""
    assert PusService17.is_are_you_alive(tc_s17) is True


@pytest.mark.requirement("PUS-007")
def test_s17_are_you_alive_response(tc_s17: PusTcPacket) -> None:
    """TM(17,2) response generated correctly."""
    tm = PusService17.are_you_alive_response(tm_apid=0x101, sequence_count=1)
    assert tm.service == 17
    assert tm.subservice == 2


@pytest.mark.requirement("PUS-007")
def test_s17_non_alive_tc_not_detected() -> None:
    """TC with different service not identified as are-you-alive."""
    tc = PusTcPacket(apid=0x100, sequence_count=1, service=3, subservice=25)
    assert PusService17.is_are_you_alive(tc) is False
