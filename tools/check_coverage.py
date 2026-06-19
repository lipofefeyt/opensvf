"""Shim  -  logic lives in svf.tools.checkcov (installed via pip)."""
from svf.tools.checkcov import *  # noqa: F401, F403
from svf.tools.checkcov import main, fidelity_report, EQUIPMENT_FIDELITY  # noqa: F401

if __name__ == "__main__":
    main()
