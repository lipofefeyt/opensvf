"""
aarch64 ZynqMP OBSW Emulation Tests

Validates that obsw_sim_aarch64 (cross-compiled for ZynqMP Cortex-A53)
runs correctly under QEMU and speaks the same pipe protocol as x86_64.

Requires: obsw_sim_aarch64 + qemu-aarch64 + aarch64 glibc

Implements: SVF-DEV-100 (ZynqMP SIL validation)
"""
from __future__ import annotations

import os
import shutil
import struct
import subprocess
import select
from pathlib import Path

import pytest

_root = Path(__file__).parent.parent.parent
OBSW_AARCH64 = _root / "obsw_sim_aarch64"
QEMU         = shutil.which("qemu-aarch64")
GLIBC        = os.environ.get("AARCH64_GLIBC", "")

pytestmark = pytest.mark.skipif(
    not OBSW_AARCH64.exists() or not QEMU or not GLIBC,
    reason="obsw_sim_aarch64 / qemu-aarch64 / AARCH64_GLIBC not available"
)


def _launch() -> subprocess.Popen:
    return subprocess.Popen(
        [QEMU, "-L", GLIBC, str(OBSW_AARCH64)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _send_sensor(proc: subprocess.Popen) -> bytes:
    """Send one sensor frame, collect until sync byte."""
    sensor_data = struct.pack("<3fB4fB3fBf",
        1e-5, 2e-5, 3e-5, 1,
        1.0, 0.0, 0.0, 0.0, 0,
        0.0, 0.0, 0.0, 0, 0.1)
    frame = bytes([0x02]) + struct.pack(">H", len(sensor_data)) + sensor_data
    assert proc.stdin is not None
    proc.stdin.write(frame)
    proc.stdin.flush()

    result = bytearray()
    for _ in range(100):
        ready = select.select([proc.stdout], [], [], 1.0)
        if ready[0]:
            b = os.read(proc.stdout.fileno(), 1)
            if b:
                result.extend(b)
                if b[0] == 0xFF:
                    break
        else:
            break
    return bytes(result)


class TestAarch64ObswSuite:

    @pytest.mark.requirement("SVF-DEV-100")
    def test_aarch64_starts_and_prints_version(self) -> None:
        """obsw_sim_aarch64 starts under QEMU and prints SRDB version."""
        import time
        proc = _launch()
        time.sleep(0.3)
        assert proc.stderr is not None
        ready = select.select([proc.stderr], [], [], 1.0)
        if ready[0]:
            stderr = os.read(proc.stderr.fileno(), 512).decode()
        else:
            stderr = ""
        proc.terminate()
        proc.wait()
        assert "Host sim started" in stderr
        assert "SRDB version" in stderr

    @pytest.mark.requirement("SVF-DEV-100")
    def test_aarch64_actuator_frame_type(self) -> None:
        """aarch64 obsw_sim responds with type-0x03 actuator frame."""
        proc = _launch()
        result = _send_sensor(proc)
        proc.terminate()
        proc.wait()
        assert len(result) > 0
        assert result[0] == 0x03, (
            f"Expected 0x03 actuator frame, got 0x{result[0]:02X}"
        )

    @pytest.mark.requirement("SVF-DEV-100")
    def test_aarch64_sync_byte_present(self) -> None:
        """aarch64 obsw_sim sends 0xFF sync byte."""
        proc = _launch()
        result = _send_sensor(proc)
        proc.terminate()
        proc.wait()
        assert 0xFF in result, "No sync byte in response"

    @pytest.mark.requirement("SVF-DEV-100")
    def test_aarch64_protocol_identical_to_x86(self) -> None:
        """
        aarch64 and x86_64 obsw_sim produce same frame structure.
        Validates endianness and struct packing are correct on aarch64.
        """
        OBSW_X86 = _root / "obsw_sim"
        if not OBSW_X86.exists():
            pytest.skip("obsw_sim (x86) not found")

        # Run aarch64
        proc_a64 = _launch()
        result_a64 = _send_sensor(proc_a64)
        proc_a64.terminate()
        proc_a64.wait()

        # Run x86
        proc_x86 = subprocess.Popen(
            [str(OBSW_X86)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        result_x86 = _send_sensor(proc_x86)
        proc_x86.terminate()
        proc_x86.wait()

        # Frame type and length must match
        assert result_a64[0] == result_x86[0], "Frame type differs"
        assert result_a64[1:3] == result_x86[1:3], "Frame length differs"
        # Both end with sync byte
        assert result_a64[-1] == 0xFF
        assert result_x86[-1] == 0xFF
