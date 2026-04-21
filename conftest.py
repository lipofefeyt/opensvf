import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))
pytest_plugins = ["svf.plugin"]

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

"""
Root conftest — global session teardown.
DDS participants are now explicitly closed via DdsSyncProtocol.close()
in SimulationMaster._teardown(). The gc sweep here is a belt-and-suspenders
fallback for any participants created outside SimulationMaster.
"""
from __future__ import annotations

import gc

import pytest


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Final GC sweep on session end."""
    gc.collect()
    gc.collect()
    gc.collect()
