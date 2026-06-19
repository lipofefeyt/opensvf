"""
Tests for ProcedureContext TC uplink and TM receipt, and OBCEmulatorAdapter
unit-level behaviour (TM queue, HK parsing, desync recovery).

Validates GAP-004 (tc() reaches OBSW) and GAP-005 (expect_tm() works).
Uses ObcStub as a stand-in for OBCEmulatorAdapter  -  it responds to
TC(17,1) with TM(17,2) without requiring a real OBSW binary.
"""
from __future__ import annotations
import struct
import pytest
import time
import threading
from unittest.mock import patch
from svf.campaign.procedure import Procedure, ProcedureContext, ProcedureError
from svf.core.abstractions import SyncProtocol
from svf.core.equipment import PortDefinition
from svf.models.dhs.hil_adapter import HilAdapter
from svf.pus.tm import PusTmPacket, PusTmBuilder
from svf.stores.parameter_store import ParameterStore
from svf.stores.command_store import CommandStore


class _NoSync(SyncProtocol):
    def reset(self) -> None: pass
    def publish_ready(self, m: str, t: float) -> None: pass
    def wait_for_ready(self, e: list[str], t: float) -> bool: return True


class _FakeHil(HilAdapter):
    """Minimal HilAdapter test double that records received TCs."""

    def __init__(self, store: ParameterStore, cmd_store: CommandStore) -> None:
        super().__init__("obc", _NoSync(), store, cmd_store)
        self.received: list[bytes] = []

    def _declare_ports(self) -> list[PortDefinition]:
        return []

    def do_step(self, t: float, dt: float) -> None:
        pass

    def initialise(self, start_time: float = 0.0) -> None: pass
    def connect(self) -> None: pass
    def disconnect(self) -> None: pass
    def is_connected(self) -> bool: return True

    def receive_tc(self, raw_tc: bytes, t: float = 0.0) -> list[PusTmPacket]:
        self.received.append(raw_tc)
        return []

    def get_tm_queue(self) -> list[PusTmPacket]:
        return []


class TestProcedureTcTmSuite:

    @pytest.mark.requirement("SVF-DEV-120")
    def test_tc_reaches_model_with_receive_tc(self) -> None:
        """ctx.tc() calls receive_tc() on the first HilAdapter model found."""
        store     = ParameterStore()
        cmd_store = CommandStore()
        fake_obc  = _FakeHil(store, cmd_store)

        class FakeMaster:
            _models = [fake_obc]

        ctx = ProcedureContext(FakeMaster(), store, cmd_store)
        ctx.tc(17, 1)
        assert len(fake_obc.received) == 1
        pkt = fake_obc.received[0]
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


def _make_obc() -> "OBCEmulatorAdapter":  # type: ignore[name-defined]
    """Build a disconnected OBCEmulatorAdapter for unit testing."""
    from svf.models.dhs.obc_emulator import OBCEmulatorAdapter

    class _NoSync(SyncProtocol):
        def reset(self) -> None: pass
        def publish_ready(self, m: str, t: float) -> None: pass
        def wait_for_ready(self, e: list[str], t: float) -> bool: return True

    return OBCEmulatorAdapter(
        sim_path=None,
        sync_protocol=_NoSync(),
        store=ParameterStore(),
        command_store=CommandStore(),
        socket_addr=None,
    )


class OBCEmulatorAdapterSuite:

    @pytest.mark.requirement("SVF-DEV-159")
    def test_get_tm_queue_returns_and_drains_parsed_packet(self) -> None:
        """get_tm_queue() returns parsed packets and empties on second call."""
        obc = _make_obc()
        pkt = PusTmBuilder().build(
            PusTmPacket(apid=0x010, sequence_count=1, service=17, subservice=2)
        )
        obc._parse_tm(pkt, t=1.0)

        queue = obc.get_tm_queue()
        assert len(queue) == 1
        assert queue[0].service == 17
        assert queue[0].subservice == 2
        assert obc.get_tm_queue() == []

    @pytest.mark.requirement("SVF-DEV-160")
    def test_on_s3_25_updates_hk_ports(self) -> None:
        """TM(3,25) HK packet updates watchdog, memory, health, reset, cpu ports."""
        from svf.models.dhs.obc_emulator import OBCEmulatorAdapter, _DHS_OBC_HK_FMT

        obc = _make_obc()
        hk = struct.pack(_DHS_OBC_HK_FMT, 1, 100, 0, 45, 0, 2, 75)
        # mode=1, obt=100, watchdog=0, mem=45%, health=0, reset=2, cpu=75%
        app_data = bytes([3]) + hk  # SID=3 followed by HK fields
        pkt = PusTmBuilder().build(
            PusTmPacket(apid=0x100, sequence_count=1, service=3, subservice=25,
                        app_data=app_data)
        )
        obc._parse_tm(pkt, t=2.0)

        assert obc._obc_memory_used_pct == 45
        assert obc._obc_reset_count == 2
        assert obc._obc_cpu_load == 75
        assert obc._mode == 1

    @pytest.mark.requirement("SVF-DEV-161")
    def test_consecutive_desync_raises_after_max_desync(self) -> None:
        """RuntimeError is raised after MAX_DESYNC consecutive missed sync bytes."""
        from svf.models.dhs.obc_emulator import MAX_DESYNC

        obc = _make_obc()
        with patch.object(obc, "_collect_until_sync", return_value=([], False)):
            for i in range(MAX_DESYNC - 1):
                obc.do_step(float(i) * 0.1, 0.1)  # should not raise
            with pytest.raises(RuntimeError, match="Lost sync"):
                obc.do_step(float(MAX_DESYNC - 1) * 0.1, 0.1)
