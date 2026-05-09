"""
SVF YAMCS Bridge

Connects a running SVF simulation to a YAMCS ground station.

YAMCS connects TO SVF (SVF is the TCP server for TM, UDP server for TC):
  Port 10015 — TM downlink: SVF sends PUS TM packets to YAMCS (TCP)
  Port 10025 — TC uplink:   YAMCS sends PUS TC packets to SVF (UDP)

Usage:
    bridge = YamcsBridge(store)
    bridge.start()          # opens sockets, waits for YAMCS
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

logger = logging.getLogger(__name__)

TM_PORT = 10015
TC_PORT = 10025


class YamcsBridge:
    """
    Bridge between SVF and YAMCS ground station.

    TM flow: SVF -> YAMCS via TCP (YAMCS connects as client to port 10015)
    TC flow: YAMCS -> SVF via UDP (YAMCS sends datagrams to port 10025)
    """

    def __init__(
        self,
        store: "ParameterStore",
        tm_port: int = TM_PORT,
        tc_port: int = TC_PORT,
    ) -> None:
        self._store = store
        self._tm_port = tm_port
        self._tc_port = tc_port

        self._tm_conn: Optional[socket.socket] = None
        self._tm_server: Optional[socket.socket] = None
        self._tc_server: Optional[socket.socket] = None

        self._tc_queue: "queue.Queue[bytes]" = queue.Queue()
        self._alive = False

    def start(self) -> None:
        """Open sockets and wait for YAMCS TM connection."""
        self._alive = True

        # TM - TCP server, YAMCS connects and holds the connection
        self._tm_server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._tm_server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._tm_server.bind(("0.0.0.0", self._tm_port))
        self._tm_server.listen(1)
        self._tm_server.settimeout(10.0)
        logger.info(f"[yamcs] TM server listening on TCP port {self._tm_port}")

        # TC - UDP server, YAMCS fires datagrams (no connection state)
        self._tc_server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._tc_server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._tc_server.bind(("0.0.0.0", self._tc_port))
        logger.info(f"[yamcs] TC server listening on UDP port {self._tc_port}")

        # Wait for YAMCS TM connection
        try:
            self._tm_conn, addr = self._tm_server.accept()
            logger.info(f"[yamcs] TM link connected from {addr}")
        except socket.timeout:
            logger.warning(
                "[yamcs] TM link: no YAMCS connection within timeout")

        # Start UDP TC reader
        threading.Thread(
            target=self._read_tc_udp_loop,
            name="yamcs-tc-reader",
            daemon=True,
        ).start()

    def stop(self) -> None:
        """Close all connections."""
        self._alive = False
        for sock in [self._tm_conn, self._tm_server, self._tc_server]:
            if sock:
                try:
                    sock.close()
                except Exception:
                    pass
        logger.info("[yamcs] Bridge stopped")

    def send_tm(self, packet: bytes) -> None:
        """Send a raw PUS TM packet to YAMCS over TCP."""
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

    def _read_tc_udp_loop(self) -> None:
        """Background thread - reads TC datagrams from YAMCS via UDP."""
        logger.info("[yamcs] TC UDP reader started")
        self._tc_server.settimeout(1.0)
        while self._alive:
            try:
                data, addr = self._tc_server.recvfrom(4096)
                if not data:
                    continue
                svc = data[7] if len(data) > 7 else "?"
                sub = data[8] if len(data) > 8 else "?"
                logger.info(
                    f"[yamcs] TC received from {addr} "
                    f"svc={svc} subsvc={sub} "
                    f"({len(data)} bytes): {data.hex()}"
                )
                self._tc_queue.put(data)
            except socket.timeout:
                continue
            except Exception as e:
                if self._alive:
                    logger.debug(f"[yamcs] TC UDP reader: {e}")
