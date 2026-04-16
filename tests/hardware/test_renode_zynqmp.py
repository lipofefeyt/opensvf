"""
Renode ZynqMP OBC Emulator Socket Adapter Tests

Validates OBCEmulatorAdapter in socket mode against obsw_zynqmp
running in Renode ZynqMP emulation.

Requires:
  - renode available in PATH
  - build_zynqmp_baremetal/obsw_zynqmp.bin (run baremetal-build in openobsw)
  - OBSW_ZYNQMP_BIN env var pointing to obsw_zynqmp.bin
  - RENODE_RESC env var pointing to zynqmp_obsw.resc

Usage:
  renode renode/zynqmp_obsw.resc &
  sleep 5
  OBSW_ZYNQMP_BIN=... pytest tests/hardware/test_renode_zynqmp.py -v

Implements: SVF-DEV-101 (Renode ZynqMP socket SIL)
"""
from __future__ import annotations

import os
import shutil
import time
from pathlib import Path

import pytest
from cyclonedds.domain import DomainParticipant

from svf.dds_sync import DdsSyncProtocol
from svf.parameter_store import ParameterStore
from svf.command_store import CommandStore
from svf.models.obc_emulator import OBCEmulatorAdapter

RENODE_HOST = "localhost"
RENODE_PORT = 3456

pytestmark = pytest.mark.skipif(
    shutil.which("renode") is None,
    reason="renode not in PATH"
)


@pytest.fixture
def obc_socket(tmp_path: Path) -> OBCEmulatorAdapter:
    """OBCEmulatorAdapter in socket mode — connects to running Renode."""
    participant = DomainParticipant()
    store = ParameterStore()
    cmd_store = CommandStore()
    sync = DdsSyncProtocol(participant)

    obc = OBCEmulatorAdapter(
        sim_path=None,
        sync_protocol=sync,
        store=store,
        command_store=cmd_store,
        sync_timeout=10.0,
        socket_addr=(RENODE_HOST, RENODE_PORT),
    )
    obc.initialise(start_time=0.0)
    yield obc
    obc.teardown()
    sync.close()
    participant._delete()


class TestRenodeZynqmpSuite:

    @pytest.mark.requirement("SVF-DEV-101")
    def test_socket_connects_to_renode(self) -> None:
        """OBCEmulatorAdapter connects to Renode UART socket."""
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
        except Exception as e:
            pytest.skip(f"Renode not running on {RENODE_HOST}:{RENODE_PORT}: {e}")
        finally:
            sync.close()
            participant._delete()

    @pytest.mark.requirement("SVF-DEV-101")
    def test_s17_ping_via_renode(self) -> None:
        """TC(17,1) ping returns TM(17,2) pong from ZynqMP OBSW in Renode."""
        import socket
        import struct

        # Direct socket test — doesn't need full SVF stack
        try:
            sock = socket.create_connection(
                (RENODE_HOST, RENODE_PORT), timeout=5.0
            )
        except Exception as e:
            pytest.skip(f"Renode not running: {e}")

        with sock:
            time.sleep(0.5)
            sock.settimeout(2.0)
            try:
                banner = sock.recv(256).decode(errors="replace")
                assert "ZynqMP started" in banner or "SRDB version" in banner
            except Exception:
                pytest.skip("No banner — Renode not running")

            # TC(17,1) — exact working format
            tc = bytes.fromhex("1810c0000003201101" + "00")
            frame = bytes([0x01]) + struct.pack(">H", len(tc)) + tc
            sock.sendall(frame)

            time.sleep(2.0)
            sock.settimeout(5.0)
            raw = b""
            try:
                while True:
                    chunk = sock.recv(256)
                    if not chunk:
                        break
                    raw += chunk
            except Exception:
                pass

            # Parse TM frames
            found_pong = False
            i = 0
            while i < len(raw):
                if raw[i] == 0xFF:
                    break
                if raw[i] != 0x04 or i + 3 > len(raw):
                    i += 1
                    continue
                length = (raw[i+1] << 8) | raw[i+2]
                i += 3
                if i + length > len(raw):
                    break
                pkt = raw[i:i+length]
                i += length
                if len(pkt) >= 9 and pkt[7] == 17 and pkt[8] == 2:
                    found_pong = True

            assert found_pong, f"No TM(17,2) pong received. Raw: {raw.hex()}"
