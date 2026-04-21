"""
SVF YAMCS Bridge

Connects a running SVF simulation to a YAMCS ground station.

YAMCS connects TO SVF (SVF is the TCP server):
  Port 10015 — TM downlink: SVF sends PUS TM packets to YAMCS
  Port 10025 — TC uplink:   YAMCS sends PUS TC packets to SVF

Usage:
    bridge = YamcsBridge(obc, store)
    bridge.start()          # opens TCP sockets
    # ... run simulation ...
    bridge.stop()

Implements: SVF-DEV-060
"""

from __future__ import annotations

import logging
import queue
import socket
import struct
import threading
from typing import Optional

from svf.stores.parameter_store import ParameterStore
from svf.pus.tc import PusTcPacket
from svf.pus.tm import PusTmPacket

logger = logging.getLogger(__name__)

TM_PORT = 10015
TC_PORT = 10025


class YamcsBridge:
    """
    TCP bridge between SVF and YAMCS.

    YAMCS connects as a client to both ports.
    SVF listens and accepts one connection per port.

    TM flow: SVF → YAMCS (push each tick)
    TC flow: YAMCS → SVF (background reader, queued)
    """

    def __init__(
        self,
        store: ParameterStore,
        tm_port: int = TM_PORT,
        tc_port: int = TC_PORT,
    ) -> None:
        self._store = store
        self._tm_port = tm_port
        self._tc_port = tc_port

        self._tm_conn: Optional[socket.socket] = None
        self._tc_conn: Optional[socket.socket] = None
        self._tm_server: Optional[socket.socket] = None
        self._tc_server: Optional[socket.socket] = None

        self._tc_queue: queue.Queue[bytes] = queue.Queue()
        self._alive = False
        self._tc_reader: Optional[threading.Thread] = None
        self._tm_seq: int = 0

    def start(self) -> None:
        """Open TCP servers and wait for YAMCS to connect."""
        self._alive = True

        # TM server — YAMCS connects here to receive TM
        self._tm_server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._tm_server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._tm_server.bind(("127.0.0.1", self._tm_port))
        self._tm_server.listen(1)
        self._tm_server.settimeout(10.0)
        logger.info(f"[yamcs] TM server listening on port {self._tm_port}")

        # TC server — YAMCS connects here to send TC
        self._tc_server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._tc_server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._tc_server.bind(("127.0.0.1", self._tc_port))
        self._tc_server.listen(1)
        self._tc_server.settimeout(10.0)
        logger.info(f"[yamcs] TC server listening on port {self._tc_port}")

        # Accept YAMCS connections
        try:
            self._tm_conn, addr = self._tm_server.accept()
            logger.info(f"[yamcs] TM link connected from {addr}")
        except socket.timeout:
            logger.warning("[yamcs] TM link: no YAMCS connection within timeout")

        try:
            self._tc_conn, addr = self._tc_server.accept()
            logger.info(f"[yamcs] TC link connected from {addr}")
            self._tc_reader = threading.Thread(
                target=self._read_tc_loop,
                name="yamcs-tc-reader",
                daemon=True,
            )
            self._tc_reader.start()
        except socket.timeout:
            logger.warning("[yamcs] TC link: no YAMCS connection within timeout")

    def stop(self) -> None:
        """Close all connections."""
        self._alive = False
        for sock in [self._tm_conn, self._tc_conn,
                     self._tm_server, self._tc_server]:
            if sock:
                try:
                    sock.close()
                except Exception:
                    pass
        logger.info("[yamcs] Bridge stopped")

    def send_tm(self, packet: bytes) -> None:
        """Send a raw PUS TM packet to YAMCS."""
        if self._tm_conn is None:
            return
        try:
            self._tm_conn.sendall(packet)
        except Exception as e:
            logger.warning(f"[yamcs] TM send failed: {e}")
            self._tm_conn = None

    def get_tc(self) -> Optional[bytes]:
        """Get next TC from YAMCS queue (non-blocking)."""
        try:
            return self._tc_queue.get_nowait()
        except queue.Empty:
            return None

    def _read_tc_loop(self) -> None:
        """Background thread — reads TC packets from YAMCS."""
        conn = self._tc_conn
        if conn is None:
            return
        buf = bytearray()
        try:
            while self._alive:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                buf.extend(chunk)
                # Parse CCSDS primary header (6 bytes) to get packet length
                while len(buf) >= 6:
                    data_len = struct.unpack(">H", buf[4:6])[0]
                    total = 6 + data_len + 1
                    if len(buf) < total:
                        break
                    pkt = bytes(buf[:total])
                    buf = buf[total:]
                    self._tc_queue.put(pkt)
                    logger.info(
                        f"[yamcs] TC received "
                        f"svc={pkt[7] if len(pkt)>7 else '?'}"
                    )
        except Exception as e:
            logger.debug(f"[yamcs] TC reader: {e}")
