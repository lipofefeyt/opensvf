"""
SVF Magnetometer Equipment
Measures the local magnetic field vector in body frame.
Provides input to b-dot and other magnetic field-based algorithms.

Physics:
- Takes true magnetic field vector as input (from truth model or orbit propagator)
- Adds Gaussian noise + bias drift
- Temperature-dependent noise level
- Invalid when powered off

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


def make_magnetometer(
    sync_protocol: SyncProtocol,
    store: ParameterStore,
    command_store: Optional[CommandStore] = None,
    equipment_id: str = "mag",
    seed: Optional[int] = None,
    hardware_profile: Optional[str] = None,
    hardware_dir: Optional[str] = None,
) -> NativeEquipment:
    """
    Create a Magnetometer NativeEquipment.

    Args:
        equipment_id:     Instance name (e.g. 'mag', 'mag2'). Port names use
                          the form 'aocs.<equipment_id>.<signal>'.
        hardware_profile: Profile name to override built-in defaults.
        hardware_dir:     Directory to search for profile YAML files.

    Inputs:
        aocs.<id>.power_enable  -  power on/off
        aocs.<id>.true_x/y/z   -  true magnetic field (T) from truth model

    Outputs:
        aocs.<id>.field_x/y/z  -  measured field with noise + bias
        aocs.<id>.status       -  0=off, 1=nominal
    """
    # Physics constants  -  per-instance locals
    base_noise_std   = 1e-7
    temp_noise_coeff = 5e-9
    bias_drift_rate  = 1e-9
    ambient_temp_c   = 20.0
    nominal_temp_c   = 30.0
    temp_rise_rate   = 0.02

    if hardware_profile is not None:
        from svf.config.hardware_profile import load_hardware_profile
        p = load_hardware_profile(hardware_profile, hardware_dir)
        base_noise_std   = p.get("noise_std_tesla",         base_noise_std)
        bias_drift_rate  = p.get("bias_drift_rate_tesla_s", bias_drift_rate)
        temp_noise_coeff = p.get("temp_noise_coeff",        temp_noise_coeff)
        ambient_temp_c   = p.get("temp_ambient_degc",       ambient_temp_c)
        nominal_temp_c   = p.get("temp_nominal_degc",       nominal_temp_c)
        temp_rise_rate   = p.get("temp_rise_rate",          temp_rise_rate)

    rng  = random.Random(seed)
    _pfx = f"aocs.{equipment_id}"

    state: dict[str, Any] = {
        "temperature": ambient_temp_c,
        "bias_x":      0.0,
        "bias_y":      0.0,
        "bias_z":      0.0,
        "powered":     False,
    }

    def _mag_step(eq: NativeEquipment, t: float, dt: float) -> None:
        powered = eq.read_port(f"{_pfx}.power_enable") > 0.5

        if not powered:
            state["powered"]     = False
            state["temperature"] = max(
                ambient_temp_c,
                state["temperature"] - temp_rise_rate * 2.0 * dt,
            )
            eq.write_port(f"{_pfx}.field_x", 0.0)
            eq.write_port(f"{_pfx}.field_y", 0.0)
            eq.write_port(f"{_pfx}.field_z", 0.0)
            eq.write_port(f"{_pfx}.status",  0.0)
            return

        state["powered"]      = True
        state["temperature"] += temp_rise_rate * (
            nominal_temp_c - state["temperature"]
        ) * dt

        # Bias drift (random walk)
        drift = bias_drift_rate * math.sqrt(dt)
        state["bias_x"] += rng.gauss(0, drift)
        state["bias_y"] += rng.gauss(0, drift)
        state["bias_z"] += rng.gauss(0, drift)

        noise_std = base_noise_std + temp_noise_coeff * max(
            0.0, state["temperature"] - nominal_temp_c
        )

        true_x = eq.read_port(f"{_pfx}.true_x")
        true_y = eq.read_port(f"{_pfx}.true_y")
        true_z = eq.read_port(f"{_pfx}.true_z")

        eq.write_port(f"{_pfx}.field_x",
                      true_x + rng.gauss(0, noise_std) + state["bias_x"])
        eq.write_port(f"{_pfx}.field_y",
                      true_y + rng.gauss(0, noise_std) + state["bias_y"])
        eq.write_port(f"{_pfx}.field_z",
                      true_z + rng.gauss(0, noise_std) + state["bias_z"])
        eq.write_port(f"{_pfx}.status", 1.0)

    eq = NativeEquipment(
        equipment_id=equipment_id,
        ports=[
            PortDefinition(f"{_pfx}.power_enable", PortDirection.IN,
                           description="Power enable"),
            PortDefinition(f"{_pfx}.true_x", PortDirection.IN,
                           unit="T", description="True field X (truth model)"),
            PortDefinition(f"{_pfx}.true_y", PortDirection.IN,
                           unit="T", description="True field Y (truth model)"),
            PortDefinition(f"{_pfx}.true_z", PortDirection.IN,
                           unit="T", description="True field Z (truth model)"),
            PortDefinition(f"{_pfx}.field_x", PortDirection.OUT,
                           unit="T", description="Measured field X"),
            PortDefinition(f"{_pfx}.field_y", PortDirection.OUT,
                           unit="T", description="Measured field Y"),
            PortDefinition(f"{_pfx}.field_z", PortDirection.OUT,
                           unit="T", description="Measured field Z"),
            PortDefinition(f"{_pfx}.status", PortDirection.OUT,
                           description="Status (0=off, 1=nominal)"),
        ],
        step_fn=_mag_step,
        sync_protocol=sync_protocol,
        store=store,
        command_store=command_store,
    )
    eq._port_values[f"{_pfx}.power_enable"] = 0.0
    return eq
