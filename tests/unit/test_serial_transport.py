"""
Unit tests for M28 UART serial transport in OBCEmulatorAdapter.
Uses unittest.mock to fake pyserial  -  no hardware required.
"""
from __future__ import annotations

import queue
import struct
import threading
import time
import types
from typing import Any
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from svf.models.dhs.obc_emulator import (
    OBCEmulatorAdapter,
    FRAME_TC,
    FRAME_SENSOR,
    FRAME_TM,
    SYNC_BYTE,
)
from svf.stores.parameter_store import ParameterStore
from svf.stores.command_store import CommandStore
from svf.core.abstractions import SyncProtocol


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _NoopSync(SyncProtocol):
    def reset(self) -> None: pass
    def publish_ready(self, model_id: str, t: float) -> None: pass
    def wait_for_ready(self, expected: list[str], timeout: float) -> bool: return True


def _make_fake_serial(rx_bytes: bytes = b"") -> MagicMock:
    """Return a mock Serial object that yields rx_bytes on read()."""
    ser = MagicMock()
    ser.is_open = True
    # Simulate non-blocking reads: return bytes in chunks
    _buf = bytearray(rx_bytes)
    _sent: list[bytes] = []

    def _read(n: int = 1) -> bytes:
        chunk = bytes(_buf[:n])
        del _buf[:n]
        return chunk

    ser.read.side_effect = _read
    ser.write.side_effect = lambda data: _sent.append(bytes(data))
    ser._sent = _sent
    return ser


def _make_adapter(serial_port: str = "/dev/ttyUSB0", baud: int = 115200) -> OBCEmulatorAdapter:
    store = ParameterStore()
    sync = _NoopSync()
    return OBCEmulatorAdapter(
        sim_path=None,
        sync_protocol=sync,
        store=store,
        serial_port=serial_port,
        baud_rate=baud,
    )


# ---------------------------------------------------------------------------
# Tests: import guard
# ---------------------------------------------------------------------------

def test_no_pyserial_raises_import_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """initialise() raises ImportError with helpful message when pyserial missing."""
    import svf.models.dhs.obc_emulator as _mod
    monkeypatch.setattr(_mod, "_HAS_PYSERIAL", False)
    adapter = _make_adapter()
    with pytest.raises(ImportError, match="pyserial"):
        adapter.initialise()


# ---------------------------------------------------------------------------
# Tests: initialise / teardown
# ---------------------------------------------------------------------------

@pytest.mark.requirement("SVF-DEV-169")
def test_initialise_opens_serial_port() -> None:
    """initialise() opens the serial port at the configured baud rate."""
    fake_ser = _make_fake_serial()
    adapter = _make_adapter(serial_port="/dev/ttyUSB0", baud=9600)

    with patch("svf.models.dhs.obc_emulator._pyserial") as mock_serial_mod:
        mock_serial_mod.Serial.return_value = fake_ser
        adapter.initialise()

    mock_serial_mod.Serial.assert_called_once_with(
        port="/dev/ttyUSB0",
        baudrate=9600,
        timeout=0,
    )
    assert adapter._serial_dev is fake_ser


def test_initialise_starts_reader_thread() -> None:
    """initialise() starts the serial reader background thread."""
    fake_ser = _make_fake_serial()
    adapter = _make_adapter()

    with patch("svf.models.dhs.obc_emulator._pyserial") as mock_serial_mod:
        mock_serial_mod.Serial.return_value = fake_ser
        adapter.initialise()

    assert adapter._reader is not None
    assert adapter._reader.is_alive()
    adapter.teardown()


def test_teardown_closes_serial_port() -> None:
    """teardown() calls close() on the serial device and clears _serial_dev."""
    fake_ser = _make_fake_serial()
    adapter = _make_adapter()

    with patch("svf.models.dhs.obc_emulator._pyserial") as mock_serial_mod:
        mock_serial_mod.Serial.return_value = fake_ser
        adapter.initialise()
        adapter.teardown()

    fake_ser.close.assert_called_once()
    assert adapter._serial_dev is None


# ---------------------------------------------------------------------------
# Tests: is_connected
# ---------------------------------------------------------------------------

def test_is_connected_open_port() -> None:
    """is_connected() returns True when serial port is open."""
    fake_ser = _make_fake_serial()
    fake_ser.is_open = True
    adapter = _make_adapter()

    with patch("svf.models.dhs.obc_emulator._pyserial") as mock_serial_mod:
        mock_serial_mod.Serial.return_value = fake_ser
        adapter.initialise()
        assert adapter.is_connected() is True
    adapter.teardown()


def test_is_connected_closed_port() -> None:
    """is_connected() returns False when serial port has been closed."""
    fake_ser = _make_fake_serial()
    adapter = _make_adapter()

    with patch("svf.models.dhs.obc_emulator._pyserial") as mock_serial_mod:
        mock_serial_mod.Serial.return_value = fake_ser
        adapter.initialise()
        fake_ser.is_open = False
        assert adapter.is_connected() is False
    adapter.teardown()


# ---------------------------------------------------------------------------
# Tests: write framing
# ---------------------------------------------------------------------------

def test_write_typed_frame_sends_correct_framing() -> None:
    """_write_typed_frame() sends [type][len_BE][body] over the serial port."""
    fake_ser = _make_fake_serial()
    adapter = _make_adapter()

    with patch("svf.models.dhs.obc_emulator._pyserial") as mock_serial_mod:
        mock_serial_mod.Serial.return_value = fake_ser
        adapter.initialise()
        body = b"\xde\xad\xbe\xef"
        adapter._write_typed_frame(FRAME_TC, body)

    assert len(fake_ser._sent) == 1
    sent = fake_ser._sent[0]
    assert sent[0] == FRAME_TC
    length = struct.unpack(">H", sent[1:3])[0]
    assert length == 4
    assert sent[3:] == body
    adapter.teardown()


def test_write_typed_frame_serial_preferred_over_socket() -> None:
    """When both _serial_dev and _sock are set, serial is used."""
    fake_ser = _make_fake_serial()
    adapter = _make_adapter()

    with patch("svf.models.dhs.obc_emulator._pyserial") as mock_serial_mod:
        mock_serial_mod.Serial.return_value = fake_ser
        adapter.initialise()
        # Manually set a socket to verify serial wins
        adapter._sock = MagicMock()
        adapter._write_typed_frame(FRAME_TC, b"\x01")
        adapter._sock = None

    assert len(fake_ser._sent) == 1  # serial got the write
    adapter.teardown()


# ---------------------------------------------------------------------------
# Tests: reader thread feeds _rx_q
# ---------------------------------------------------------------------------

def test_reader_thread_feeds_rx_queue() -> None:
    """Serial reader thread puts each received byte into _rx_q."""
    rx_data = bytes([0x01, 0x02, 0x03])
    fake_ser = MagicMock()
    fake_ser.is_open = True

    # Feed 3 bytes then block forever (simulates waiting for more data)
    _chunks = [bytes([b]) for b in rx_data]
    _chunks.append(b"")  # empty read: triggers continue loop

    call_count = 0

    def _blocking_read(n: int) -> bytes:
        nonlocal call_count
        if call_count < len(_chunks) - 1:
            result = _chunks[call_count]
            call_count += 1
            return result
        # Block until alive is False
        time.sleep(0.05)
        return b""

    fake_ser.read.side_effect = _blocking_read

    adapter = _make_adapter()
    with patch("svf.models.dhs.obc_emulator._pyserial") as mock_serial_mod:
        mock_serial_mod.Serial.return_value = fake_ser
        adapter.initialise()

        collected: list[int] = []
        deadline = time.monotonic() + 1.0
        while len(collected) < 3 and time.monotonic() < deadline:
            try:
                chunk = adapter._rx_q.get(timeout=0.1)
                if chunk is not None:
                    collected.append(chunk[0])
            except queue.Empty:
                pass

    adapter.teardown()
    assert collected == [0x01, 0x02, 0x03]


# ---------------------------------------------------------------------------
# Tests: baud_rate default
# ---------------------------------------------------------------------------

def test_default_baud_rate() -> None:
    """Default baud rate is 115200."""
    store = ParameterStore()
    sync = _NoopSync()
    adapter = OBCEmulatorAdapter(
        sim_path=None,
        sync_protocol=sync,
        store=store,
        serial_port="/dev/ttyS0",
    )
    assert adapter._baud_rate == 115200
