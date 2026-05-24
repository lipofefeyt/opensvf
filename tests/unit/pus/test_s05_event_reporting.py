"""
Tests for PUS Service 5 — Event Reporting.
Implements: PUS-006
"""

import pytest
import struct
from svf.pus.services import PusService5, EventSeverity


@pytest.mark.requirement("PUS-006")
def test_s5_informative_event() -> None:
    """TM(5,1) informative event generated correctly."""
    tm = PusService5.report(
        severity=EventSeverity.INFORMATIVE,
        event_id=0x0001,
        tm_apid=0x100,
        sequence_count=1,
    )
    assert tm.service == 5
    assert tm.subservice == 1
    event_id = struct.unpack_from(">H", tm.app_data)[0]
    assert event_id == 0x0001


@pytest.mark.requirement("PUS-006")
def test_s5_high_severity_event() -> None:
    """TM(5,4) high severity event generated correctly."""
    tm = PusService5.report(
        severity=EventSeverity.HIGH,
        event_id=0x00FF,
        tm_apid=0x100,
        sequence_count=1,
        auxiliary_data=b"\x01\x02",
    )
    assert tm.subservice == 4
    assert tm.app_data[2:] == b"\x01\x02"


@pytest.mark.requirement("PUS-006")
def test_s5_invalid_severity_raises() -> None:
    """Invalid severity raises ValueError."""
    with pytest.raises(ValueError, match="severity"):
        PusService5.report(severity=5, event_id=1, tm_apid=0x100, sequence_count=1)
