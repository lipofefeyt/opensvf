"""
Tests for ProcedureContext TC uplink and TM receipt.

Validates GAP-004 (tc() reaches OBSW) and GAP-005 (expect_tm() works).
Uses ObcStub as a stand-in for OBCEmulatorAdapter — it responds to
TC(17,1) with TM(17,2) without requiring a real OBSW binary.
"""
from __future__ import annotations
import pytest
import time
import threading
from svf.campaign.procedure import Procedure, ProcedureContext, ProcedureError
from svf.stores.parameter_store import ParameterStore
from svf.stores.command_store import CommandStore


class TestProcedureTcTmSuite:

    @pytest.mark.requirement("SVF-DEV-120")
    def test_tc_reaches_model_with_receive_tc(self) -> None:
        """ctx.tc() calls receive_tc() on the first model that has it."""
        store     = ParameterStore()
        cmd_store = CommandStore()
        received  = []

        class FakeObc:
            equipment_id = "obc"
            _models      = []
            def receive_tc(self, raw: bytes) -> None:
                received.append(raw)

        class FakeMaster:
            _models = [FakeObc()]

        ctx = ProcedureContext(FakeMaster(), store, cmd_store)
        ctx.tc(17, 1)
        assert len(received) == 1
        # Check service and subservice bytes in the packet
        pkt = received[0]
        assert pkt[7] == 17
        assert pkt[8] == 1

    @pytest.mark.requirement("SVF-DEV-120")
    def test_expect_tm_passes_when_parameter_written(self) -> None:
        """expect_tm() passes when svf.tm.{svc}.{subsvc}.received is written."""
        store     = ParameterStore()
        cmd_store = CommandStore()
        ctx       = ProcedureContext(None, store, cmd_store)

        # Simulate TM receipt by writing the confirmation key
        def write_tm():
            time.sleep(0.1)
            store.write("svf.tm.17.2.received", 1.0, t=1.0, model_id="obc")

        t = threading.Thread(target=write_tm, daemon=True)
        t.start()
        ctx.expect_tm(17, 2, timeout=2.0)  # should not raise

    @pytest.mark.requirement("SVF-DEV-120")
    def test_expect_tm_raises_on_timeout(self) -> None:
        """expect_tm() raises ProcedureError when TM never arrives."""
        store     = ParameterStore()
        cmd_store = CommandStore()
        ctx       = ProcedureContext(None, store, cmd_store)

        with pytest.raises(ProcedureError, match="Timeout"):
            ctx.expect_tm(17, 2, timeout=0.2)

    @pytest.mark.requirement("SVF-DEV-120")
    def test_tc_falls_back_to_command_store_when_no_obc(self) -> None:
        """ctx.tc() falls back to CommandStore when no model has receive_tc."""
        store     = ParameterStore()
        cmd_store = CommandStore()

        class FakeMaster:
            _models = []  # no OBC

        ctx = ProcedureContext(FakeMaster(), store, cmd_store)
        ctx.tc(17, 1)  # should not raise, falls back to CommandStore
        entry = cmd_store.peek("svf.tc.17.1")
        assert entry is not None

    @pytest.mark.requirement("SVF-DEV-120")
    def test_obc_emulator_writes_tm_receipt_on_parse(self) -> None:
        """OBCEmulatorAdapter._parse_tm() writes svf.tm.{svc}.{subsvc}.received."""
        from svf.models.dhs.obc_emulator import OBCEmulatorAdapter
        from svf.core.abstractions import SyncProtocol

        class _NoSync(SyncProtocol):
            def reset(self) -> None: pass
            def publish_ready(self, m: str, t: float) -> None: pass
            def wait_for_ready(self, e: list[str], t: float) -> bool: return True

        store     = ParameterStore()
        cmd_store = CommandStore()
        obc = OBCEmulatorAdapter(
            sim_path=None,
            sync_protocol=_NoSync(),
            store=store,
            command_store=cmd_store,
            socket_addr=None,
        )

        # Build a minimal TM(17,2) pong packet (10 bytes minimum)
        tm_pkt = bytes([
            0x08, 0x10,  # version + APID
            0xC0, 0x00,  # seq flags + count
            0x00, 0x04,  # data length
            0x20,        # secondary header flag
            17,          # service
            2,           # subservice
            0x00,        # spare
        ])
        obc._parse_tm(tm_pkt, t=1.0)

        entry = store.read("svf.tm.17.2.received")
        assert entry is not None
        assert entry.value >= 1.0
