"""
Wire layouts of opensvf's S11/S12/S19 TC builders, pinned to what openobsw
v0.18 parses (OBSW-SRS-280, 290, 300). The L3 counterpart runs them against
obsw_sim in tests/system/test_obsw_alignment.py.

Implements: SVF-DEV-211
"""
from __future__ import annotations

import math
import struct

import pytest

from svf.pus.services.s11_scheduling import PusService11
from svf.pus.services.s12_monitoring import PusService12
from svf.pus.services.s19_event_action import PusService19
from svf.pus.tc import PusTcBuilder, PusTcPacket

_PING = PusTcBuilder().build(PusTcPacket(apid=0x010, sequence_count=1, service=17, subservice=1))


@pytest.mark.requirement("SVF-DEV-211")
def test_s11_insert_is_cuc42_tag_then_complete_packet() -> None:
    data = PusService11.build_insert(103.5, _PING, tc_apid=0x010).app_data
    coarse, fine = struct.unpack_from(">IH", data, 0)
    assert (coarse, fine) == (103, 0x8000)
    assert data[6:] == _PING
    assert len(_PING) <= 64                       # OBSW_S11_TC_MAX_LEN


@pytest.mark.requirement("SVF-DEV-211")
def test_s12_add_is_15_bytes_in_srs_290_order() -> None:
    data = PusService12.build_add(0x20A0, None, 5000.0, 0x7001, 0x7002, 2,
                                  tc_apid=0x010).app_data
    assert len(data) == 15
    pid, low, high, ev_lo, ev_hi, sev = struct.unpack(">HffHHB", data)
    assert (pid, high, ev_lo, ev_hi, sev) == (0x20A0, 5000.0, 0x7001, 0x7002, 2)
    assert math.isnan(low)                        # NaN disables the low check


@pytest.mark.requirement("SVF-DEV-211")
def test_s19_add_is_event_id_then_complete_packet() -> None:
    data = PusService19.build_add(0x7004, _PING, tc_apid=0x010).app_data
    assert struct.unpack_from(">H", data, 0)[0] == 0x7004
    assert data[2:] == _PING
