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


def make_css(
    sync_protocol: SyncProtocol,
    store: ParameterStore,
    command_store: Optional[CommandStore] = None,
    equipment_id: str = "css",
    seed: Optional[int] = None,
    hardware_profile: Optional[str] = None,
    hardware_dir: Optional[str] = None,
) -> NativeEquipment:
    """
    Create a Coarse Sun Sensor NativeEquipment.

    Args:
        equipment_id:     Instance name (e.g. 'css', 'css2'). Port names use
                          the form 'aocs.<equipment_id>.<signal>'.
                          Truth rate ports (aocs.truth.rate_*) are shared and
                          not prefixed.
        hardware_profile: Profile name to override built-in defaults.
        hardware_dir:     Directory to search for profile YAML files.

    Inputs:
        aocs.<id>.illumination  -  solar illumination fraction (0=eclipse, 1=sun)
        aocs.truth.rate_x/y/z  -  true body rates (shared, from dynamics)

    Outputs:
        aocs.<id>.sun_x/y/z    -  estimated sun unit vector in body frame
        aocs.<id>.validity      -  1=valid (sun visible), 0=invalid (eclipse)
    """
    eclipse_threshold = 0.05
    noise_std         = 0.01

    if hardware_profile is not None:
        from svf.config.hardware_profile import load_hardware_profile
        p = load_hardware_profile(hardware_profile, hardware_dir)
        eclipse_threshold = p.get("eclipse_threshold", eclipse_threshold)
        noise_std         = p.get("noise_std",         noise_std)

    rng  = random.Random(seed)
    _pfx = f"aocs.{equipment_id}"

    state: dict[str, Any] = {
        "sun_x": 0.0,
        "sun_y": 0.0,
        "sun_z": 1.0,
    }

    def _css_step(eq: NativeEquipment, t: float, dt: float) -> None:
        illumination = eq.read_port(f"{_pfx}.illumination")

        if illumination < eclipse_threshold:
            eq.write_port(f"{_pfx}.sun_x",   0.0)
            eq.write_port(f"{_pfx}.sun_y",   0.0)
            eq.write_port(f"{_pfx}.sun_z",   0.0)
            eq.write_port(f"{_pfx}.validity", 0.0)
            return

        wx = eq.read_port("aocs.truth.rate_x")
        wy = eq.read_port("aocs.truth.rate_y")
        wz = eq.read_port("aocs.truth.rate_z")

        sx, sy, sz = state["sun_x"], state["sun_y"], state["sun_z"]

        # Rotate sun vector by body rates (first-order)
        sx += (wy * sz - wz * sy) * dt
        sy += (wz * sx - wx * sz) * dt
        sz += (wx * sy - wy * sx) * dt

        mag = math.sqrt(sx*sx + sy*sy + sz*sz)
        if mag > 1e-10:
            sx /= mag
            sy /= mag
            sz /= mag

        state["sun_x"] = sx
        state["sun_y"] = sy
        state["sun_z"] = sz

        eq.write_port(f"{_pfx}.sun_x",   sx + rng.gauss(0, noise_std))
        eq.write_port(f"{_pfx}.sun_y",   sy + rng.gauss(0, noise_std))
        eq.write_port(f"{_pfx}.sun_z",   sz + rng.gauss(0, noise_std))
        eq.write_port(f"{_pfx}.validity", 1.0)

    eq = NativeEquipment(
        equipment_id=equipment_id,
        ports=[
            PortDefinition(f"{_pfx}.illumination", PortDirection.IN,
                           description="Solar illumination (0=eclipse, 1=sun)"),
            PortDefinition("aocs.truth.rate_x", PortDirection.IN,
                           unit="rad/s", description="True rate X"),
            PortDefinition("aocs.truth.rate_y", PortDirection.IN,
                           unit="rad/s", description="True rate Y"),
            PortDefinition("aocs.truth.rate_z", PortDirection.IN,
                           unit="rad/s", description="True rate Z"),
            PortDefinition(f"{_pfx}.sun_x", PortDirection.OUT,
                           description="Sun vector X"),
            PortDefinition(f"{_pfx}.sun_y", PortDirection.OUT,
                           description="Sun vector Y"),
            PortDefinition(f"{_pfx}.sun_z", PortDirection.OUT,
                           description="Sun vector Z"),
            PortDefinition(f"{_pfx}.validity", PortDirection.OUT,
                           description="1=sun visible"),
        ],
        step_fn=_css_step,
        sync_protocol=sync_protocol,
        store=store,
        command_store=command_store,
    )
    eq._port_values[f"{_pfx}.illumination"] = 1.0
    eq._port_values[f"{_pfx}.sun_z"]        = 1.0
    return eq
