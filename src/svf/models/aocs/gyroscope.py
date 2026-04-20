"""
SVF Gyroscope Equipment
Measures angular rate in body frame.
Used for attitude rate estimation and b-dot control.

Physics:
- Measures true body rates with noise + bias drift
- Scale factor error (simplified)
- Temperature-dependent noise
- Bias drift random walk

Implements: SVF-DEV-038
"""

from __future__ import annotations

import logging
import math
import random
from typing import Any, Optional

from svf.abstractions import SyncProtocol
from svf.equipment import PortDefinition, PortDirection
from svf.native_equipment import NativeEquipment
from svf.parameter_store import ParameterStore
from svf.command_store import CommandStore

logger = logging.getLogger(__name__)

try:
    import importlib.util as _importlib_util
except Exception:
    _HW_AVAILABLE = False

# Noise parameters
ARW_STD          = 1e-4    # rad/s/√Hz angle random walk
BIAS_INSTABILITY = 1e-5    # rad/s bias instability
TEMP_NOISE_COEFF = 1e-5    # rad/s/degC additional noise

# Temperature
AMBIENT_TEMP_C   = 20.0
NOMINAL_TEMP_C   = 35.0
TEMP_RISE_RATE   = 0.05
COOLING_RATE     = 0.03


def make_gyroscope(
    sync_protocol: SyncProtocol,
    store: ParameterStore,
    command_store: Optional[CommandStore] = None,
    seed: Optional[int] = None,
    hardware_profile: Optional[str] = None,
    hardware_dir: str = "srdb/data/hardware",
) -> NativeEquipment:
    """
    Create a Gyroscope NativeEquipment.

    Inputs:
        aocs.truth.rate_x/y/z — true angular rates (rad/s)
        aocs.gyro.power_enable — power on/off

    Outputs:
        aocs.gyro.rate_x/y/z  — measured rates with noise + bias
        aocs.gyro.temperature  — gyro temperature
        aocs.gyro.status       — 0=off, 1=nominal
    """
    rng = random.Random(seed)

    state: dict[str, Any] = {
        "bias_x": 0.0,
        "bias_y": 0.0,
        "bias_z": 0.0,
        "temperature": AMBIENT_TEMP_C,
        "powered": False,
    }

    def _gyro_step(eq: NativeEquipment, t: float, dt: float) -> None:
        powered = eq.read_port("aocs.gyro.power_enable") > 0.5

        if not powered:
            state["powered"] = False
            state["temperature"] = max(
                AMBIENT_TEMP_C,
                state["temperature"] - COOLING_RATE * dt
            )
            eq.write_port("aocs.gyro.rate_x", 0.0)
            eq.write_port("aocs.gyro.rate_y", 0.0)
            eq.write_port("aocs.gyro.rate_z", 0.0)
            eq.write_port("aocs.gyro.temperature", state["temperature"])
            eq.write_port("aocs.gyro.status", 0.0)
            return

        state["powered"] = True
        state["temperature"] += TEMP_RISE_RATE * (
            NOMINAL_TEMP_C - state["temperature"]
        ) * dt

        # Bias drift (random walk)
        bias_noise = BIAS_INSTABILITY * math.sqrt(dt)
        state["bias_x"] += rng.gauss(0, bias_noise)
        state["bias_y"] += rng.gauss(0, bias_noise)
        state["bias_z"] += rng.gauss(0, bias_noise)

        # Measurement noise
        noise_std = (ARW_STD / math.sqrt(dt) + TEMP_NOISE_COEFF *
                     max(0.0, state["temperature"] - NOMINAL_TEMP_C))

        # True rates + noise + bias
        wx = eq.read_port("aocs.truth.rate_x")
        wy = eq.read_port("aocs.truth.rate_y")
        wz = eq.read_port("aocs.truth.rate_z")

        eq.write_port("aocs.gyro.rate_x",
                      wx + rng.gauss(0, noise_std) + state["bias_x"])
        eq.write_port("aocs.gyro.rate_y",
                      wy + rng.gauss(0, noise_std) + state["bias_y"])
        eq.write_port("aocs.gyro.rate_z",
                      wz + rng.gauss(0, noise_std) + state["bias_z"])
        eq.write_port("aocs.gyro.temperature", state["temperature"])
        eq.write_port("aocs.gyro.status", 1.0)


    global BIAS_INSTABILITY, ARW_STD
    if hardware_profile is not None:
        from svf.hardware_profile import load_hardware_profile
        profile = load_hardware_profile(hardware_profile)
        ARW_STD          = profile.get("arw_rad_s_sqrthz",        ARW_STD)
        BIAS_INSTABILITY = profile.get("bias_drift_rate_rad_s2",   BIAS_INSTABILITY)
    eq = NativeEquipment(
        equipment_id="gyro",
        ports=[
            PortDefinition("aocs.gyro.power_enable", PortDirection.IN,
                           description="Power enable"),
            PortDefinition("aocs.truth.rate_x", PortDirection.IN,
                           unit="rad/s", description="True rate X"),
            PortDefinition("aocs.truth.rate_y", PortDirection.IN,
                           unit="rad/s", description="True rate Y"),
            PortDefinition("aocs.truth.rate_z", PortDirection.IN,
                           unit="rad/s", description="True rate Z"),
            PortDefinition("aocs.gyro.rate_x", PortDirection.OUT,
                           unit="rad/s", description="Measured rate X"),
            PortDefinition("aocs.gyro.rate_y", PortDirection.OUT,
                           unit="rad/s", description="Measured rate Y"),
            PortDefinition("aocs.gyro.rate_z", PortDirection.OUT,
                           unit="rad/s", description="Measured rate Z"),
            PortDefinition("aocs.gyro.temperature", PortDirection.OUT,
                           unit="degC", description="Gyro temperature"),
            PortDefinition("aocs.gyro.status", PortDirection.OUT,
                           description="Status (0=off, 1=nominal)"),
        ],
        step_fn=_gyro_step,
        sync_protocol=sync_protocol,
        store=store,
        command_store=command_store,
    )
    eq._port_values["aocs.gyro.power_enable"] = 0.0
    return eq
