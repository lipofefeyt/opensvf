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

from svf.core.abstractions import SyncProtocol
from svf.core.equipment import PortDefinition, PortDirection
from svf.core.native_equipment import NativeEquipment
from svf.stores.parameter_store import ParameterStore
from svf.stores.command_store import CommandStore

logger = logging.getLogger(__name__)


def make_gyroscope(
    sync_protocol: SyncProtocol,
    store: ParameterStore,
    command_store: Optional[CommandStore] = None,
    equipment_id: str = "gyro",
    seed: Optional[int] = None,
    hardware_profile: Optional[str] = None,
    hardware_dir: Optional[str] = None,
) -> NativeEquipment:
    """
    Create a Gyroscope NativeEquipment.

    Args:
        equipment_id:     Instance name (e.g. 'gyro', 'gyro2'). Port names use
                          the form 'aocs.<equipment_id>.<signal>'.
                          Truth rate ports (aocs.truth.rate_*) are shared and
                          not prefixed.
        hardware_profile: Profile name to override built-in defaults.
        hardware_dir:     Directory to search for profile YAML files.

    Inputs:
        aocs.<id>.power_enable — power on/off
        aocs.truth.rate_x/y/z  — true angular rates (shared, from dynamics)

    Outputs:
        aocs.<id>.rate_x/y/z   — measured rates with noise + bias
        aocs.<id>.temperature  — gyro temperature
        aocs.<id>.status       — 0=off, 1=nominal
    """
    # Physics constants — per-instance locals
    arw_std          = 1e-4
    bias_instability = 1e-5
    temp_noise_coeff = 1e-5
    ambient_temp_c   = 20.0
    nominal_temp_c   = 35.0
    temp_rise_rate   = 0.05
    cooling_rate     = 0.03

    if hardware_profile is not None:
        from svf.config.hardware_profile import load_hardware_profile
        p = load_hardware_profile(hardware_profile, hardware_dir)
        arw_std          = p.get("arw_rad_s_sqrthz",       arw_std)
        bias_instability = p.get("bias_drift_rate_rad_s2",  bias_instability)
        temp_noise_coeff = p.get("temp_noise_coeff",        temp_noise_coeff)
        ambient_temp_c   = p.get("temp_ambient_degc",       ambient_temp_c)
        nominal_temp_c   = p.get("temp_nominal_degc",       nominal_temp_c)
        temp_rise_rate   = p.get("temp_rise_rate",          temp_rise_rate)
        cooling_rate     = p.get("cooling_rate",            cooling_rate)

    rng  = random.Random(seed)
    _pfx = f"aocs.{equipment_id}"

    state: dict[str, Any] = {
        "bias_x":      0.0,
        "bias_y":      0.0,
        "bias_z":      0.0,
        "temperature": ambient_temp_c,
        "powered":     False,
    }

    def _gyro_step(eq: NativeEquipment, t: float, dt: float) -> None:
        powered = eq.read_port(f"{_pfx}.power_enable") > 0.5

        if not powered:
            state["powered"]     = False
            state["temperature"] = max(
                ambient_temp_c,
                state["temperature"] - cooling_rate * dt,
            )
            eq.write_port(f"{_pfx}.rate_x",      0.0)
            eq.write_port(f"{_pfx}.rate_y",      0.0)
            eq.write_port(f"{_pfx}.rate_z",      0.0)
            eq.write_port(f"{_pfx}.temperature", state["temperature"])
            eq.write_port(f"{_pfx}.status",      0.0)
            return

        state["powered"]      = True
        state["temperature"] += temp_rise_rate * (
            nominal_temp_c - state["temperature"]
        ) * dt

        # Bias drift (random walk)
        bias_noise = bias_instability * math.sqrt(dt)
        state["bias_x"] += rng.gauss(0, bias_noise)
        state["bias_y"] += rng.gauss(0, bias_noise)
        state["bias_z"] += rng.gauss(0, bias_noise)

        noise_std = arw_std / math.sqrt(dt) + temp_noise_coeff * max(
            0.0, state["temperature"] - nominal_temp_c
        )

        wx = eq.read_port("aocs.truth.rate_x")
        wy = eq.read_port("aocs.truth.rate_y")
        wz = eq.read_port("aocs.truth.rate_z")

        eq.write_port(f"{_pfx}.rate_x",
                      wx + rng.gauss(0, noise_std) + state["bias_x"])
        eq.write_port(f"{_pfx}.rate_y",
                      wy + rng.gauss(0, noise_std) + state["bias_y"])
        eq.write_port(f"{_pfx}.rate_z",
                      wz + rng.gauss(0, noise_std) + state["bias_z"])
        eq.write_port(f"{_pfx}.temperature", state["temperature"])
        eq.write_port(f"{_pfx}.status",      1.0)

    eq = NativeEquipment(
        equipment_id=equipment_id,
        ports=[
            PortDefinition(f"{_pfx}.power_enable", PortDirection.IN,
                           description="Power enable"),
            PortDefinition("aocs.truth.rate_x", PortDirection.IN,
                           unit="rad/s", description="True rate X"),
            PortDefinition("aocs.truth.rate_y", PortDirection.IN,
                           unit="rad/s", description="True rate Y"),
            PortDefinition("aocs.truth.rate_z", PortDirection.IN,
                           unit="rad/s", description="True rate Z"),
            PortDefinition(f"{_pfx}.rate_x", PortDirection.OUT,
                           unit="rad/s", description="Measured rate X"),
            PortDefinition(f"{_pfx}.rate_y", PortDirection.OUT,
                           unit="rad/s", description="Measured rate Y"),
            PortDefinition(f"{_pfx}.rate_z", PortDirection.OUT,
                           unit="rad/s", description="Measured rate Z"),
            PortDefinition(f"{_pfx}.temperature", PortDirection.OUT,
                           unit="degC", description="Gyro temperature"),
            PortDefinition(f"{_pfx}.status", PortDirection.OUT,
                           description="Status (0=off, 1=nominal)"),
        ],
        step_fn=_gyro_step,
        sync_protocol=sync_protocol,
        store=store,
        command_store=command_store,
    )
    eq._port_values[f"{_pfx}.power_enable"] = 0.0
    return eq
