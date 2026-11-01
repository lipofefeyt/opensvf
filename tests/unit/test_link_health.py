"""
Communication health between opensvf and a real OBSW (M77).

Implements: SVF-DEV-214
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from svf.campaign.campaign_runner import _attach_link_health
from svf.campaign.procedure import ProcedureResult, Verdict
from svf.models.dhs.link_health import LinkHealth
from svf.models.dhs.obc_emulator import S1_FAILURE_CODES, OBCEmulatorAdapter
from svf.stores.parameter_store import ParameterStore

# TM(3,25) set 3 as openobsw v0.18 emits it: no PEC.
_HK = bytes.fromhex("0903c00000162003190000000000000000"
                    "0301000003e8000c01000005")
_TM_1_2 = bytes.fromhex("0903c00000102001020000000000000000" "1810c0020007")


def _adapter(tm_pec: bool = False) -> OBCEmulatorAdapter:
    return OBCEmulatorAdapter(sim_path=None, sync_protocol=MagicMock(),
                              store=ParameterStore(), tm_pec=tm_pec)


@pytest.mark.requirement("SVF-DEV-214")
def test_defect_1_reproduced_every_packet_counted_as_dropped() -> None:
    """Parsing openobsw TM with a PEC expectation drops it: now counted, not silent."""
    adapter = _adapter(tm_pec=True)
    for _ in range(3):
        adapter._parse_tm(_HK, t=1.0)
    health = adapter.link_health()
    assert (health.tm_received, health.tm_parsed, health.tm_dropped) == (3, 0, 3)
    assert health.last_drop_reason is not None and "CRC" in health.last_drop_reason
    assert not health.healthy
    assert adapter.get_tm_queue() == []


@pytest.mark.requirement("SVF-DEV-214")
def test_parsed_tm_rejections_and_mode_changes_are_counted() -> None:
    adapter = _adapter()
    adapter._parse_tm(_HK, t=1.0)           # set 3, mode SAFE (1)
    adapter._parse_tm(_TM_1_2, t=1.1)       # rejected, 0x0007
    h = adapter.link_health()
    assert (h.tm_received, h.tm_parsed, h.tm_dropped) == (2, 2, 0)
    assert h.tc_rejected == {0x0007: 1}
    assert h.mode_changes == [(1.0, 1)]
    assert "0x0007 not allowed in this mode x1" in h.summary(S1_FAILURE_CODES)


@pytest.mark.requirement("SVF-DEV-214")
def test_tm_listener_sees_packets_even_if_queue_is_drained() -> None:
    adapter = _adapter()
    seen: list[tuple[int, int, float]] = []
    adapter.add_tm_listener(lambda p, t: seen.append((p.service, p.subservice, t)))
    adapter._parse_tm(_HK, t=2.0)
    adapter.get_tm_queue()                  # another consumer drains the queue
    assert seen == [(3, 25, 2.0)]


def _result(verdict: Verdict) -> ProcedureResult:
    return ProcedureResult(procedure_id="P", title="t", requirement="R",
                           verdict=verdict, duration_s=0.0)


@pytest.mark.requirement("SVF-DEV-214")
def test_pass_on_an_unhealthy_link_becomes_fail() -> None:
    adapter = _adapter(tm_pec=True)
    adapter._parse_tm(_HK, t=1.0)
    result = _result(Verdict.PASS)
    _attach_link_health(result, SimpleNamespace(_models=[adapter]))
    assert result.verdict == Verdict.FAIL
    assert result.error is not None and "1 of 1 TM packets dropped" in result.error
    assert result.link is not None and result.link["tm_dropped"] == 1


@pytest.mark.requirement("SVF-DEV-214")
def test_healthy_link_keeps_verdict_and_stub_has_no_link() -> None:
    adapter = _adapter()
    adapter._parse_tm(_HK, t=1.0)
    ok = _result(Verdict.PASS)
    _attach_link_health(ok, SimpleNamespace(_models=[adapter]))
    assert ok.verdict == Verdict.PASS and ok.link is not None and ok.link["healthy"]

    stub_result = _result(Verdict.PASS)
    _attach_link_health(stub_result, SimpleNamespace(_models=[]))
    assert stub_result.link is None


@pytest.mark.requirement("SVF-DEV-214")
def test_link_health_problems_name_desyncs() -> None:
    h = LinkHealth(desyncs=2)
    assert not h.healthy
    assert h.problems() == ["2 tick(s) without the OBSW sync byte"]
