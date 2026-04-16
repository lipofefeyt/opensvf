"""
tests/test_obc_emulator_adapter.py
End-to-end test for OBCEmulatorAdapter against the real obsw_sim binary.

Requires obsw_sim to be built:
    cd ../openobsw && cmake --build build

Run:
    pytest tests/test_obc_emulator_adapter.py -v
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from svf.models.dhs.obc_emulator import OBCEmulatorAdapter

# Resolve obsw_sim path: env var > repo root > sibling repo
_env = os.environ.get("OBSW_SIM")
if _env:
    OBSW_SIM = Path(_env)
else:
    _root = Path(__file__).parent.parent
    _candidates = [
        _root / "obsw_sim",
        _root / "build" / "sim" / "obsw_sim",
        _root.parent / "openobsw" / "build" / "sim" / "obsw_sim",
    ]
    OBSW_SIM = next((p for p in _candidates if p.exists()), _candidates[0])


def make_sync() -> MagicMock:
    sync = MagicMock()
    sync.publish_ready = MagicMock()
    return sync


def make_store() -> MagicMock:
    store = MagicMock()
    store.write = MagicMock()
    store.read  = MagicMock(return_value=None)
    return store


def make_adapter(**kwargs: object) -> OBCEmulatorAdapter:
    return OBCEmulatorAdapter(
        sim_path=OBSW_SIM,
        sync_protocol=make_sync(),
        store=make_store(),
        sync_timeout=5.0,
        **kwargs,  # type: ignore[arg-type]
    )


@pytest.mark.skipif(
    not OBSW_SIM.exists(),
    reason=f"obsw_sim not found at {OBSW_SIM} — run 'cmake --build build' in openobsw"
)
class OBCEmulatorAdapterTests:

    def test_ports_match_obc_equipment(self) -> None:
        """Adapter exposes same port names as ObcEquipment."""
        adapter = make_adapter()
        expected_in = {
            "obc.tc_input", "dhs.obc.mode_cmd",
            "dhs.obc.watchdog_kick", "dhs.obc.memory_dump_cmd",
        }
        expected_out = {
            "dhs.obc.mode", "dhs.obc.obt", "dhs.obc.watchdog_status",
            "dhs.obc.memory_used_pct", "dhs.obc.health",
            "dhs.obc.reset_count", "dhs.obc.cpu_load", "obc.tm_output",
        }
        assert expected_in  <= set(adapter.ports.keys())
        assert expected_out <= set(adapter.ports.keys())

    def test_missing_sim_raises(self) -> None:
        """FileNotFoundError if obsw_sim path is wrong."""
        adapter = OBCEmulatorAdapter(
            sim_path="/nonexistent/obsw_sim",
            sync_protocol=make_sync(),
            store=make_store(),
        )
        with pytest.raises(FileNotFoundError):
            adapter.initialise()

    def test_initialise_spawns_process(self) -> None:
        """Subprocess is running after initialise()."""
        adapter = make_adapter()
        adapter.initialise()
        assert adapter._proc is not None
        assert adapter._proc.poll() is None
        adapter.teardown()

    def test_teardown_kills_process(self) -> None:
        """Process is gone after teardown()."""
        adapter = make_adapter()
        adapter.initialise()
        adapter.teardown()
        time.sleep(0.1)
        assert adapter._proc is None

    def test_do_step_receives_sync_byte(self) -> None:
        """do_step() completes without timeout when obsw_sim is running."""
        sync  = make_sync()
        store = make_store()
        adapter = OBCEmulatorAdapter(
            sim_path=OBSW_SIM,
            sync_protocol=sync,
            store=store,
            sync_timeout=5.0,
        )
        adapter.initialise()
        try:
            # Send 10 do_step()s to trigger sync byte (every 10 TCs)
            for i in range(10):
                adapter.do_step(t=float(i) * 0.1, dt=0.1)
        finally:
            adapter.teardown()

    def test_on_tick_calls_publish_ready(self) -> None:
        """Equipment.on_tick() calls publish_ready after do_step()."""
        sync  = make_sync()
        store = make_store()
        adapter = OBCEmulatorAdapter(
            sim_path=OBSW_SIM,
            sync_protocol=sync,
            store=store,
            sync_timeout=5.0,
        )
        adapter.initialise()
        try:
            for i in range(10):
                adapter.on_tick(t=float(i) * 0.1, dt=0.1)
        finally:
            adapter.teardown()

        assert sync.publish_ready.call_count == 10

    def test_mode_cmd_sends_recover_tc(self) -> None:
        """Setting mode_cmd=NOMINAL sends TC(8,1) to obsw_sim."""
        sync  = make_sync()
        store = make_store()
        adapter = OBCEmulatorAdapter(
            sim_path=OBSW_SIM,
            sync_protocol=sync,
            store=store,
            sync_timeout=5.0,
        )
        adapter.initialise()
        try:
            # Inject NOMINAL mode command
            adapter.receive("dhs.obc.mode_cmd", 1.0)
            for i in range(10):
                adapter.do_step(t=float(i) * 0.1, dt=0.1)
        finally:
            adapter.teardown()

        # mode_cmd should be consumed after first tick
        assert adapter.read_port("dhs.obc.mode_cmd") == -1.0

    def test_obt_advances_each_tick(self) -> None:
        """On-board time increments by dt each do_step()."""
        adapter = make_adapter()
        adapter.initialise()
        try:
            for i in range(10):
                adapter.do_step(t=float(i) * 0.1, dt=0.1)
        finally:
            adapter.teardown()

        assert adapter.read_port("dhs.obc.obt") == pytest.approx(1.0, abs=0.01)