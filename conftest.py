from __future__ import annotations
import sys
import os
import gc

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))


def pytest_sessionfinish(session: object, exitstatus: object) -> None:
    gc.collect()
    gc.collect()
    gc.collect()
