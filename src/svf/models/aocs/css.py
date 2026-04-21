"""
SVF Coarse Sun Sensor Equipment
Detects sun direction in body frame.
Critical for safe mode sun acquisition.

Physics:
- Six faces (±X, ±Y, ±Z) each with a photodiode
- Sun vector computed from differential illumination
- Valid only when sun is visible (illumination > threshold)
- Noise on sun vector components

Implements: SVF-DEV-038
"""

from __future__ import annotations

import logging
import math
import random
from typing import Any, Optional

from svf.core.abstractions import SyncProtocol
from svf.core.equipment import PortDefinition, PortDirection
from svf.core.native_equipment import NativeEquipment
from svf.stores.parameter_store import ParameterStore
from svf.stores.command_store import CommandStore

logger = logging.getLogger(__name__)

ECLIPSE_THRESHOLD = 0.05   # illumination below this → invalid
NOISE_STD         = 0.01   # sun vector component noise std dev


def make_css(
    sync_protocol: SyncProtocol,
    store: ParameterStore,
    command_store: Optional[CommandStore] = None,
    seed: Optional[int] = None,
) -> NativeEquipment:
    """
    Create a Coarse Sun Sensor NativeEquipment.

    Inputs:
        aocs.css.illumination  — solar illumination fraction (0=eclipse, 1=sun)
        aocs.truth.rate_x/y/z — true body rates (for sun vector propagation)

    Outputs:
        aocs.css.sun_x/y/z    — estimated sun unit vector in body frame
        aocs.css.validity      — 1=valid (sun visible), 0=invalid (eclipse)
    """
    rng = random.Random(seed)

    # Internal sun vector — starts pointing at +Z (nadir face down)
    state: dict[str, Any] = {
        "sun_x": 0.0,
        "sun_y": 0.0,
        "sun_z": 1.0,
    }

    def _css_step(eq: NativeEquipment, t: float, dt: float) -> None:
        illumination = eq.read_port("aocs.css.illumination")

        if illumination < ECLIPSE_THRESHOLD:
            eq.write_port("aocs.css.sun_x", 0.0)
            eq.write_port("aocs.css.sun_y", 0.0)
            eq.write_port("aocs.css.sun_z", 0.0)
            eq.write_port("aocs.css.validity", 0.0)
            return

        # Propagate sun vector using body rates
        wx = eq.read_port("aocs.truth.rate_x")
        wy = eq.read_port("aocs.truth.rate_y")
        wz = eq.read_port("aocs.truth.rate_z")

        sx, sy, sz = state["sun_x"], state["sun_y"], state["sun_z"]

        # Rotate sun vector by body rates (first-order)
        dsx = (wy * sz - wz * sy) * dt
        dsy = (wz * sx - wx * sz) * dt
        dsz = (wx * sy - wy * sx) * dt

        sx += dsx
        sy += dsy
        sz += dsz

        # Normalise
        mag = math.sqrt(sx*sx + sy*sy + sz*sz)
        if mag > 1e-10:
            sx /= mag
            sy /= mag
            sz /= mag

        state["sun_x"] = sx
        state["sun_y"] = sy
        state["sun_z"] = sz

        # Add noise
        eq.write_port("aocs.css.sun_x", sx + rng.gauss(0, NOISE_STD))
        eq.write_port("aocs.css.sun_y", sy + rng.gauss(0, NOISE_STD))
        eq.write_port("aocs.css.sun_z", sz + rng.gauss(0, NOISE_STD))
        eq.write_port("aocs.css.validity", 1.0)

    eq = NativeEquipment(
        equipment_id="css",
        ports=[
            PortDefinition("aocs.css.illumination", PortDirection.IN,
                           description="Solar illumination (0=eclipse, 1=sun)"),
            PortDefinition("aocs.truth.rate_x", PortDirection.IN,
                           unit="rad/s", description="True rate X"),
            PortDefinition("aocs.truth.rate_y", PortDirection.IN,
                           unit="rad/s", description="True rate Y"),
            PortDefinition("aocs.truth.rate_z", PortDirection.IN,
                           unit="rad/s", description="True rate Z"),
            PortDefinition("aocs.css.sun_x", PortDirection.OUT,
                           description="Sun vector X"),
            PortDefinition("aocs.css.sun_y", PortDirection.OUT,
                           description="Sun vector Y"),
            PortDefinition("aocs.css.sun_z", PortDirection.OUT,
                           description="Sun vector Z"),
            PortDefinition("aocs.css.validity", PortDirection.OUT,
                           description="1=sun visible"),
        ],
        step_fn=_css_step,
        sync_protocol=sync_protocol,
        store=store,
        command_store=command_store,
    )
    eq._port_values["aocs.css.illumination"] = 1.0
    eq._port_values["aocs.css.sun_z"] = 1.0
    return eq
