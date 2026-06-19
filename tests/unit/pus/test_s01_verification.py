"""
Tests for PUS Service 1  -  Request Verification.
Implements: PUS-009
"""

import pytest
import struct
from svf.pus.tc import PusTcPacket
from svf.pus.services import PusService1


@pytest.fixture
def tc_s17() -> PusTcPacket:
    return PusTcPacket(apid=0x100, sequence_count=1, service=17, subservice=1)


@pytest.mark.requirement("PUS-009")
def test_s1_acceptance_success(tc_s17: PusTcPacket) -> None:
    """TM(1,1) acceptance success carries TC APID and sequence count."""
    tm = PusService1.acceptance_success(tc_s17, tm_apid=0x101, sequence_count=1)
    assert tm.service == 1
    assert tm.subservice == 1
    apid, seq = struct.unpack_from(">HH", tm.app_data)
    assert apid == tc_s17.apid
    assert seq == tc_s17.sequence_count


@pytest.mark.requirement("PUS-009")
def test_s1_acceptance_failure(tc_s17: PusTcPacket) -> None:
    """TM(1,2) acceptance failure carries failure code."""
    tm = PusService1.acceptance_failure(
        tc_s17, tm_apid=0x101, sequence_count=1, failure_code=0x0001
    )
    assert tm.subservice == 2
    _, _, code = struct.unpack_from(">HHH", tm.app_data)
    assert code == 0x0001


@pytest.mark.requirement("PUS-009")
def test_s1_completion_success(tc_s17: PusTcPacket) -> None:
    """TM(1,7) completion success."""
    tm = PusService1.completion_success(tc_s17, tm_apid=0x101, sequence_count=2)
    assert tm.subservice == 7


@pytest.mark.requirement("PUS-009")
def test_s1_completion_failure(tc_s17: PusTcPacket) -> None:
    """TM(1,8) completion failure."""
    tm = PusService1.completion_failure(
        tc_s17, tm_apid=0x101, sequence_count=2, failure_code=0x0002
    )
    assert tm.subservice == 8
