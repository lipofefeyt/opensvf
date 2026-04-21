"""
YAMCS Bridge Integration Tests

Tests the SVF↔YAMCS TCP bridge without requiring a real YAMCS server.
Simulates YAMCS as a TCP client connecting to SVF's TM/TC ports.

Implements: SVF-DEV-060
"""
from __future__ import annotations

import socket
import struct
import threading
import time

import pytest

from svf.stores.parameter_store import ParameterStore
from svf.ground.yamcs_bridge import YamcsBridge
from svf.pus.tm import PusTmPacket, PusTmBuilder


def _build_minimal_tm(service: int, subservice: int) -> bytes:
    pkt = PusTmPacket(
        apid=0x010,
        service=service,
        subservice=subservice,
        sequence_count=1,
        app_data=b"",
    )
    return PusTmBuilder().build(pkt)


def _make_bridge(tm_port: int, tc_port: int) -> YamcsBridge:
    store = ParameterStore()
    return YamcsBridge(store, tm_port=tm_port, tc_port=tc_port)


@pytest.mark.requirement("SVF-DEV-060")
def test_bridge_accepts_yamcs_connections() -> None:
    """Bridge accepts TCP connections on TM and TC ports."""
    bridge = _make_bridge(10115, 10125)
    t = threading.Thread(target=bridge.start, daemon=True)
    t.start()
    time.sleep(0.2)

    tm_sock = socket.socket()
    tc_sock = socket.socket()
    try:
        tm_sock.connect(("127.0.0.1", 10115))
        tc_sock.connect(("127.0.0.1", 10125))
        t.join(timeout=2)
        # Both connections accepted — no exception means pass
    finally:
        tm_sock.close()
        tc_sock.close()
        bridge.stop()


@pytest.mark.requirement("SVF-DEV-060")
def test_bridge_sends_tm_to_yamcs() -> None:
    """TM packets sent via bridge are received by YAMCS client."""
    bridge = _make_bridge(10215, 10225)
    t = threading.Thread(target=bridge.start, daemon=True)
    t.start()
    time.sleep(0.2)

    tm_sock = socket.socket()
    tc_sock = socket.socket()
    try:
        tm_sock.connect(("127.0.0.1", 10215))
        tc_sock.connect(("127.0.0.1", 10225))
        t.join(timeout=2)

        pkt = _build_minimal_tm(17, 2)
        bridge.send_tm(pkt)

        tm_sock.settimeout(2.0)
        received = tm_sock.recv(1024)
        assert received == pkt
    finally:
        tm_sock.close()
        tc_sock.close()
        bridge.stop()


@pytest.mark.requirement("SVF-DEV-060")
def test_bridge_receives_tc_from_yamcs() -> None:
    """TC packets sent by YAMCS operator are queued in bridge."""
    bridge = _make_bridge(10315, 10325)
    t = threading.Thread(target=bridge.start, daemon=True)
    t.start()
    time.sleep(0.2)

    tm_sock = socket.socket()
    tc_sock = socket.socket()
    try:
        tm_sock.connect(("127.0.0.1", 10315))
        tc_sock.connect(("127.0.0.1", 10325))
        t.join(timeout=2)

        # Build minimal PUS-C TC(17,1)
        raw_tc = bytes.fromhex("1801c000000320110100")
        tc_sock.sendall(raw_tc)
        time.sleep(0.1)

        received = bridge.get_tc()
        assert received == raw_tc
    finally:
        tm_sock.close()
        tc_sock.close()
        bridge.stop()


@pytest.mark.requirement("SVF-DEV-060")
def test_bridge_get_tc_returns_none_when_empty() -> None:
    """get_tc() returns None when no TC queued."""
    store = ParameterStore()
    bridge = YamcsBridge(store)
    assert bridge.get_tc() is None


@pytest.mark.requirement("SVF-DEV-060")
def test_bridge_stop_is_idempotent() -> None:
    """stop() can be called multiple times safely."""
    store = ParameterStore()
    bridge = YamcsBridge(store)
    bridge.stop()
    bridge.stop()
