"""
Root conftest — global session teardown.
Prevents DDS corrupted double-linked list crash on pytest exit.
"""
from __future__ import annotations

import gc
from typing import Generator

import pytest


@pytest.fixture(autouse=True, scope="function")
def _dds_gc() -> Generator[None, None, None]:
    """Force GC after each test to clean up DDS participants."""
    yield
    gc.collect()


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Final GC sweep on session end."""
    gc.collect()
    gc.collect()
    gc.collect()
