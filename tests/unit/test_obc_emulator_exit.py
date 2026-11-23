"""
L1 tests for how OBCEmulatorAdapter reports an obsw_sim that exits or goes
silent in pipe mode: exit status and stderr in the exception and in
LinkHealth, instead of a plain sync loss.

A fake obsw_sim (a Python script) stands in for the binary.

Implements: SVF-DEV-220
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from svf.models.dhs.link_health import LinkHealth
from svf.models.dhs.obc_emulator import OBCEmulatorAdapter
from svf.stores.parameter_store import ParameterStore

_PRELUDE = f"""#!{sys.executable}
import sys, time
err = sys.stderr
err.write("[OBSW] Host sim started (wire protocol v4).\\n")
err.write("[OBSW] SRDB version: 0.1.0\\n")
err.flush()

def read_frame():
    hdr = sys.stdin.buffer.read(3)
    if len(hdr) < 3:
        sys.exit(0)
    sys.stdin.buffer.read((hdr[1] << 8) | hdr[2])
"""

# Answers the first sensor frame, then dies like a v4 frame-size mismatch.
_EXITS_ON_SECOND_FRAME = _PRELUDE + """
read_frame()
sys.stdout.buffer.write(b"\\xff")
sys.stdout.flush()
read_frame()
err.write("[OBSW] FATAL: sensor frame of 47 B, wire protocol v4 expects 50 B\\n")
err.flush()
sys.exit(2)
"""

# Stays alive, writes to stderr, never sends the sync byte.
_SILENT = _PRELUDE + """
err.write("[OBSW] stuck in a loop\\n")
err.flush()
while True:
    read_frame()
"""


def _fake_sim(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "obsw_sim"
    path.write_text(body)
    path.chmod(0o755)
    return path


def _adapter(sim: Path, sync_timeout: float) -> OBCEmulatorAdapter:
    return OBCEmulatorAdapter(
        sim_path=sim, sync_protocol=MagicMock(), store=ParameterStore(),
        sync_timeout=sync_timeout, qemu_prefix=[],
    )


class ObswExitReportingSuite:

    @pytest.mark.requirement("SVF-DEV-220")
    def test_sim_exit_raises_with_status_and_stderr(self, tmp_path: Path) -> None:
        """A sim that exits ends the tick at once with its status and stderr."""
        obc = _adapter(_fake_sim(tmp_path, _EXITS_ON_SECOND_FRAME), 2.0)
        obc.initialise()
        try:
            obc.on_tick(0.0, 0.1)
            with pytest.raises(RuntimeError) as exc:
                obc.on_tick(0.1, 0.1)
            message = str(exc.value)
            assert "exited with status 2" in message
            assert "FATAL: sensor frame of 47 B" in message
            health = obc.link_health()
            assert health.obsw_exit_status == 2
            assert health.desyncs == 0
            assert not health.healthy
            assert "exited with status 2" in health.problems()[0]
            assert any("FATAL" in line for line in health.obsw_stderr_tail)
        finally:
            obc.teardown()

    @pytest.mark.requirement("SVF-DEV-220")
    def test_lost_sync_reports_stderr_of_live_sim(self, tmp_path: Path) -> None:
        """Lost sync with a sim still running carries its last stderr lines."""
        obc = _adapter(_fake_sim(tmp_path, _SILENT), 0.3)
        obc.initialise()
        try:
            with pytest.raises(RuntimeError) as exc:
                for i in range(3):
                    obc.on_tick(i * 0.1, 0.1)
            message = str(exc.value)
            assert "Lost sync" in message
            assert "stuck in a loop" in message
            health = obc.link_health()
            assert health.obsw_exit_status is None
            assert health.desyncs == 3
        finally:
            obc.teardown()

    @pytest.mark.requirement("SVF-DEV-220")
    def test_link_health_serialises_exit(self) -> None:
        """to_dict carries the exit status and stderr tail."""
        health = LinkHealth(obsw_exit_status=2, obsw_stderr_tail=["[OBSW] FATAL: x"])
        d = health.to_dict()
        assert d["obsw_exit_status"] == 2
        assert d["obsw_stderr_tail"] == ["[OBSW] FATAL: x"]
        assert d["healthy"] is False
