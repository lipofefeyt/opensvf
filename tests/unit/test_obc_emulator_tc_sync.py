"""
L1 tests for TC-frame sync accounting in OBCEmulatorAdapter: a TC frame whose
0xFF never arrives is counted in LinkHealth and makes the link unhealthy.

A fake obsw_sim (a Python script) stands in for the binary.

Implements: SVF-DEV-225
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from svf.models.dhs.obc_emulator import OBCEmulatorAdapter
from svf.pus.tc import PusTcBuilder, PusTcPacket
from svf.stores.parameter_store import ParameterStore

_SIM = f"""#!{sys.executable}
import sys
sys.stderr.write("[OBSW] Host sim started (wire protocol v4).\\n")
sys.stderr.flush()
ANSWER_TC = {{answer_tc}}
while True:
    hdr = sys.stdin.buffer.read(3)
    if len(hdr) < 3:
        sys.exit(0)
    sys.stdin.buffer.read((hdr[1] << 8) | hdr[2])
    if hdr[0] == 0x02 or ANSWER_TC:
        sys.stdout.buffer.write(b"\\xff")
        sys.stdout.flush()
"""


def _adapter(tmp_path: Path, answer_tc: bool) -> OBCEmulatorAdapter:
    sim = tmp_path / "obsw_sim"
    sim.write_text(_SIM.replace("{answer_tc}", str(answer_tc)))
    sim.chmod(0o755)
    return OBCEmulatorAdapter(sim_path=sim, sync_protocol=MagicMock(),
                              store=ParameterStore(), sync_timeout=2.0,
                              qemu_prefix=[])


def _ping() -> bytes:
    return PusTcBuilder().build(PusTcPacket(
        apid=0x010, sequence_count=1, service=17, subservice=1))


class TcSyncSuite:

    @pytest.mark.requirement("SVF-DEV-225")
    def test_missed_tc_sync_makes_the_link_unhealthy(self, tmp_path: Path) -> None:
        obc = _adapter(tmp_path, answer_tc=False)
        obc.initialise()
        try:
            obc.receive_tc(_ping())
            obc.on_tick(0.0, 0.1)
            obc.on_tick(0.1, 0.1)
        finally:
            obc.teardown()
        health = obc.link_health()
        assert health.tc_syncs_missed == 1
        assert health.desyncs == 0
        assert not health.healthy
        assert any("TC frame(s) without the OBSW sync byte" in p
                   for p in health.problems())
        assert health.to_dict()["tc_syncs_missed"] == 1
        assert "TC syncs missed 1" in health.summary()

    @pytest.mark.requirement("SVF-DEV-225")
    def test_answered_tc_sync_keeps_the_link_healthy(self, tmp_path: Path) -> None:
        obc = _adapter(tmp_path, answer_tc=True)
        obc.initialise()
        try:
            obc.receive_tc(_ping())
            obc.on_tick(0.0, 0.1)
        finally:
            obc.teardown()
        health = obc.link_health()
        assert health.tc_sent == 1
        assert health.tc_syncs_missed == 0
        assert health.healthy
        assert "TC syncs missed" not in health.summary()
