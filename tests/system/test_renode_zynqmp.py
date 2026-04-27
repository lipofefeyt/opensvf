"""
Renode ZynqMP OBC Emulator Socket Adapter Tests

Validates OBCEmulatorAdapter in socket mode against obsw_zynqmp
running in Renode ZynqMP emulation.

Requires:
  - renode available in PATH
  - bin/obsw_zynqmp.bin (run baremetal-build in openobsw)
  - Renode running: renode renode/zynqmp_obsw.resc

Usage:
  renode renode/zynqmp_obsw.resc &
  sleep 5
  pytest tests/hardware/test_renode_zynqmp.py -v

Implements: SVF-DEV-101 (Renode ZynqMP socket SIL)
"""
from __future__ import annotations

import shutil
import socket
import struct
import time

import pytest
from cyclonedds.domain import DomainParticipant

from svf.ground.dds_sync import DdsSyncProtocol
from svf.stores.parameter_store import ParameterStore
from svf.stores.command_store import CommandStore
from svf.models.dhs.obc_emulator import OBCEmulatorAdapter

RENODE_HOST = "localhost"
RENODE_PORT = 3456

pytestmark = pytest.mark.skipif(
    shutil.which("renode") is None,
    reason="renode not in PATH"
)


def _renode_running() -> bool:
    """Return True if Renode is listening on port 3456."""
    try:
        s = socket.create_connection((RENODE_HOST, RENODE_PORT), timeout=2.0)
        s.close()
        return True
    except Exception:
        return False


def _send_tc_recv(tc_hex: str, wait: float = 1.0) -> bytes:
    """
    Connect, drain banner, send TC as type-0x01 frame, wait, recv response.
    Leaves OBSW unblocked by consuming its response before closing.
    """
    sock = socket.create_connection((RENODE_HOST, RENODE_PORT), timeout=5.0)
    with sock:
        # Drain banner (present on fresh boot, absent on subsequent connects)
        sock.settimeout(2.0)
        try:
            sock.recv(256)
        except Exception:
            pass

        tc = bytes.fromhex(tc_hex)
        sock.sendall(bytes([0x01]) + struct.pack(">H", len(tc)) + tc)

        time.sleep(wait)
        sock.settimeout(5.0)
        try:
            return sock.recv(1024)
        except Exception:
            return b""


def _parse_tm_packets(raw: bytes) -> list[tuple[int, int]]:
    """Parse type-0x04 TM frames, skipping ASCII debug text."""
    packets = []
    i = 0
    # Skip ASCII preamble
    while i < len(raw) and raw[i] != 0x04:
        if raw[i] == 0xFF:
            return packets
        i += 1
    while i < len(raw):
        if raw[i] == 0xFF:
            break
        if raw[i] != 0x04 or i + 3 > len(raw):
            i += 1
            continue
        length = (raw[i + 1] << 8) | raw[i + 2]
        i += 3
        if i + length > len(raw):
            break
        pkt = raw[i : i + length]
        i += length
        if len(pkt) >= 9:
            packets.append((pkt[7], pkt[8]))
    return packets


class TestRenodeZynqmpSuite:

    @pytest.mark.requirement("SVF-DEV-101")
    def test_s17_ping_via_renode(self) -> None:
        """TC(17,1) ping returns TM(17,2) pong from ZynqMP OBSW in Renode."""
        if not _renode_running():
            pytest.skip(f"Renode not running on {RENODE_HOST}:{RENODE_PORT}")

        # TC(17,1) are-you-alive — APID 0x010, PUS-C
        raw = _send_tc_recv("1810c0000003201101" + "00", wait=1.0)

        packets = _parse_tm_packets(raw)
        assert any(svc == 17 and subsvc == 2 for svc, subsvc in packets), (
            f"No TM(17,2) pong received. "
            f"Raw ({len(raw)} bytes): {raw.hex()}"
        )

    @pytest.mark.requirement("SVF-DEV-101")
    def test_socket_connects_to_renode(self) -> None:
        """OBCEmulatorAdapter connects to Renode UART socket."""
        if not _renode_running():
            pytest.skip(f"Renode not running on {RENODE_HOST}:{RENODE_PORT}")

        participant = DomainParticipant()
        store = ParameterStore()
        cmd_store = CommandStore()
        sync = DdsSyncProtocol(participant)
        try:
            obc = OBCEmulatorAdapter(
                sim_path=None,
                sync_protocol=sync,
                store=store,
                command_store=cmd_store,
                sync_timeout=5.0,
                socket_addr=(RENODE_HOST, RENODE_PORT),
            )
            obc.initialise(start_time=0.0)
            obc.teardown()
        finally:
            sync.close()
            try:
                participant._delete()
            except Exception:
                pass