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

from svf.abstractions import SyncProtocol
from svf.equipment import PortDefinition, PortDirection
from svf.native_equipment import NativeEquipment
from svf.parameter_store import ParameterStore
from svf.command_store import CommandStore

logger = logging.getLogger(__name__)

# Noise parameters
BASE_NOISE_STD   = 1e-7    # T — baseline white noise std dev
TEMP_NOISE_COEFF = 5e-9    # T/degC additional noise above nominal
BIAS_DRIFT_RATE  = 1e-9    # T/s bias drift rate

# Temperature model
AMBIENT_TEMP_C   = 20.0
NOMINAL_TEMP_C   = 30.0
TEMP_RISE_RATE   = 0.02


def make_magnetometer(
    sync_protocol: SyncProtocol,
    store: ParameterStore,
    command_store: Optional[CommandStore] = None,
    seed: Optional[int] = None,
) -> NativeEquipment:
    """
    Create a Magnetometer NativeEquipment.

    Inputs:
        aocs.mag.field_x/y/z  — true magnetic field (T) from truth model
        aocs.mag.power_enable  — power on/off

    Outputs:
        aocs.mag.field_x/y/z  — measured field with noise
        aocs.mag.status        — 0=off, 1=nominal, 2=fault
    """
    rng = random.Random(seed)

    state: dict[str, Any] = {
        "temperature": AMBIENT_TEMP_C,
        "bias_x": 0.0,
        "bias_y": 0.0,
        "bias_z": 0.0,
        "powered": False,
    }

    def _mag_step(eq: NativeEquipment, t: float, dt: float) -> None:
        powered = eq.read_port("aocs.mag.power_enable") > 0.5

        if not powered:
            state["powered"] = False
            state["temperature"] = max(
                AMBIENT_TEMP_C,
                state["temperature"] - TEMP_RISE_RATE * 2.0 * dt
            )
            eq.write_port("aocs.mag.field_x", 0.0)
            eq.write_port("aocs.mag.field_y", 0.0)
            eq.write_port("aocs.mag.field_z", 0.0)
            eq.write_port("aocs.mag.status", 0.0)
            return

        state["powered"] = True
        state["temperature"] += TEMP_RISE_RATE * (
            NOMINAL_TEMP_C - state["temperature"]
        ) * dt

        # Bias drift
        state["bias_x"] += rng.gauss(0, BIAS_DRIFT_RATE * math.sqrt(dt))
        state["bias_y"] += rng.gauss(0, BIAS_DRIFT_RATE * math.sqrt(dt))
        state["bias_z"] += rng.gauss(0, BIAS_DRIFT_RATE * math.sqrt(dt))

        # Noise level
        noise_std = BASE_NOISE_STD + TEMP_NOISE_COEFF * max(
            0.0, state["temperature"] - NOMINAL_TEMP_C
        )

        # True field + noise + bias
        true_x = eq.read_port("aocs.mag.true_x")
        true_y = eq.read_port("aocs.mag.true_y")
        true_z = eq.read_port("aocs.mag.true_z")

        eq.write_port("aocs.mag.field_x",
                      true_x + rng.gauss(0, noise_std) + state["bias_x"])
        eq.write_port("aocs.mag.field_y",
                      true_y + rng.gauss(0, noise_std) + state["bias_y"])
        eq.write_port("aocs.mag.field_z",
                      true_z + rng.gauss(0, noise_std) + state["bias_z"])
        eq.write_port("aocs.mag.status", 1.0)

    eq = NativeEquipment(
        equipment_id="mag",
        ports=[
            PortDefinition("aocs.mag.power_enable", PortDirection.IN,
                           description="Power enable"),
            PortDefinition("aocs.mag.true_x", PortDirection.IN,
                           unit="T", description="True field X (truth model)"),
            PortDefinition("aocs.mag.true_y", PortDirection.IN,
                           unit="T", description="True field Y (truth model)"),
            PortDefinition("aocs.mag.true_z", PortDirection.IN,
                           unit="T", description="True field Z (truth model)"),
            PortDefinition("aocs.mag.field_x", PortDirection.OUT,
                           unit="T", description="Measured field X"),
            PortDefinition("aocs.mag.field_y", PortDirection.OUT,
                           unit="T", description="Measured field Y"),
            PortDefinition("aocs.mag.field_z", PortDirection.OUT,
                           unit="T", description="Measured field Z"),
            PortDefinition("aocs.mag.status", PortDirection.OUT,
                           description="Status (0=off, 1=nominal)"),
        ],
        step_fn=_mag_step,
        sync_protocol=sync_protocol,
        store=store,
        command_store=command_store,
    )
    eq._port_values["aocs.mag.power_enable"] = 0.0
    return eq
