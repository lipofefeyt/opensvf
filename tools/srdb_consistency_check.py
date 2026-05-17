"""Shim — logic lives in svf.tools.checkcons (installed via pip)."""
from svf.tools.checkcons import *  # noqa: F401, F403
from svf.tools.checkcons import (  # noqa: F401
    main,
    check_srdb_namespace,
    CheckResult,
    KNOWN_NAMESPACE_GAPS,
    _NAMESPACE_CHECK_MODELS,
)

if __name__ == "__main__":
    main()
