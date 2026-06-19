"""
SVF SharedMemorySyncProtocol
Sub-ms tick synchronisation via POSIX shared memory.
Implements: SVF-DEV-018
"""

from __future__ import annotations

import logging
import time
import uuid
from multiprocessing.shared_memory import SharedMemory
from typing import Optional

from svf.core.abstractions import SyncProtocol

logger = logging.getLogger(__name__)


class SharedMemorySyncProtocol(SyncProtocol):
    """
    SyncProtocol backed by a POSIX shared memory segment.

    Layout: one byte per registered model (0 = not ready, 1 = ready).
    Single-byte writes are atomic on all architectures  -  no locks needed.
    ``wait_for_ready()`` spin-polls the flags, avoiding kernel scheduling
    overhead and achieving sub-ms tick-to-tick latency.

    Multi-process use::

        # SVF master process
        sync = SharedMemorySyncProtocol(model_ids=["mag"], create=True)
        # share sync.name with worker process

        # Worker process
        sync = SharedMemorySyncProtocol(
            model_ids=["mag"], name=shared_name, create=False
        )

    Args:
        model_ids: Ordered list of model IDs to track.  Slot indices are
                   assigned in list order  -  must match across all peers.
        name:      Shared memory segment name.  Auto-generated if None.
        create:    True to create and own the segment; False to attach.
    """

    def __init__(
        self,
        model_ids: list[str],
        name: Optional[str] = None,
        create: bool = True,
    ) -> None:
        if not model_ids:
            raise ValueError("model_ids must not be empty")
        self._model_ids = list(model_ids)
        self._slot_map: dict[str, int] = {mid: i for i, mid in enumerate(model_ids)}
        self._size = len(model_ids)
        self._is_creator = create
        self._closed = False

        _name = name or f"svfshm{uuid.uuid4().hex[:12]}"

        if create:
            self._shm = SharedMemory(name=_name, create=True, size=self._size)
        else:
            self._shm = SharedMemory(name=_name, create=False)

        _buf = self._shm.buf
        if _buf is None:
            raise RuntimeError("SharedMemory.buf is None immediately after open")
        self._buf: memoryview = _buf

        if create:
            for i in range(self._size):
                self._buf[i] = 0
        logger.info(
            "SharedMemorySyncProtocol %s shm='%s' slots=%d",
            "created" if create else "attached",
            self._shm.name,
            len(model_ids),
        )

    @property
    def name(self) -> str:
        """Shared memory segment name  -  pass to peers so they can attach."""
        return self._shm.name

    def reset(self) -> None:
        """Clear all ready flags. Call before each tick."""
        for i in range(self._size):
            self._buf[i] = 0

    def publish_ready(self, model_id: str, t: float) -> None:
        """Set the ready flag for *model_id*."""
        idx = self._slot_map[model_id]
        self._buf[idx] = 1
        logger.debug("ShmSync ready: model=%s slot=%d t=%.6f", model_id, idx, t)

    def wait_for_ready(self, expected: list[str], timeout: float) -> bool:
        """
        Spinwait until all *expected* models have published ready.

        Returns True if all acknowledged within *timeout* seconds, False otherwise.
        """
        indices = [self._slot_map[mid] for mid in expected]
        deadline = time.monotonic() + timeout

        while time.monotonic() < deadline:
            if all(self._buf[i] == 1 for i in indices):
                return True

        missing = [mid for mid, i in zip(expected, indices) if self._buf[i] != 1]
        if missing:
            logger.warning("ShmSync timeout  -  missing: %s", missing)
            return False
        return True

    def close(self) -> None:
        """Release the buffer and unlink the segment (creator only)."""
        if self._closed:
            return
        self._closed = True
        try:
            self._buf.release()
        except Exception:
            pass
        try:
            self._shm.close()
        except Exception:
            pass
        if self._is_creator:
            try:
                self._shm.unlink()
            except Exception:
                pass
        logger.info("SharedMemorySyncProtocol closed shm='%s'", self._shm.name)

    def __del__(self) -> None:
        pass  # Never unlink in __del__  -  explicit close() is the only safe path
