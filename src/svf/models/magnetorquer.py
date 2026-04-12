"""
SVF Magnetorquer Equipment
Magnetic torque actuator — generates torque by interacting
with the Earth's magnetic field.

Physics:
- Input: dipole moment commands (Am²) per axis
- Input: measured magnetic field (T) from magnetometer
- Output: generated torque = dipole × B_field
- Temperature rise proportional to dipole² (resistive heating)
- Saturation at MAX_DIPOLE_AM2

Implements: SVF-DEV-038
"""

from __future__ import annotations

import logging
from typing import Optional

from svf.abstractions import SyncProtocol
from svf.equipment import PortDefinition, PortDirection
from svf.native_equipment import NativeEquipment
from svf.parameter_store import ParameterStore
from svf.command_store import CommandStore

logger = logging.getLogger(__name__)

try:
    import importlib.util as _importlib_util
    _HW_AVAILABLE = _importlib_util.find_spec("obsw_srdb") is not None
except Exception:
    _HW_AVAILABLE = False

MAX_DIPOLE_AM2  = 10.0    # Am² saturation limit
TEMP_RISE_COEFF = 0.005   # degC per Am²² per second
COOLING_RATE    = 0.02    # degC/s towards ambient
AMBIENT_TEMP_C  = 20.0


def make_magnetorquer(
    sync_protocol: SyncProtocol,
    store: ParameterStore,
    command_store: Optional[CommandStore] = None,
    hardware_profile: Optional[str] = None,
    hardware_dir: str = "srdb/data/hardware",
) -> NativeEquipment:
    """
    Create a Magnetorquer NativeEquipment.

    Inputs:
        aocs.mtq.dipole_x/y/z  — commanded dipole moments (Am²)
        aocs.mtq.power_enable   — power on/off
        aocs.mag.field_x/y/z   — measured B field for torque calculation

    Outputs:
        aocs.mtq.torque_x/y/z  — generated torque (Nm) = dipole × B
        aocs.mtq.status         — 0=off, 1=nominal
    """
    state = {"temperature": AMBIENT_TEMP_C}

    def _mtq_step(eq: NativeEquipment, t: float, dt: float) -> None:
        powered = eq.read_port("aocs.mtq.power_enable") > 0.5

        if not powered:
            state["temperature"] = max(
                AMBIENT_TEMP_C,
                state["temperature"] - COOLING_RATE * dt
            )
            eq.write_port("aocs.mtq.torque_x", 0.0)
            eq.write_port("aocs.mtq.torque_y", 0.0)
            eq.write_port("aocs.mtq.torque_z", 0.0)
            eq.write_port("aocs.mtq.status", 0.0)
            return

        # Read and saturate dipole commands
        mx = max(-MAX_DIPOLE_AM2, min(MAX_DIPOLE_AM2,
             eq.read_port("aocs.mtq.dipole_x")))
        my = max(-MAX_DIPOLE_AM2, min(MAX_DIPOLE_AM2,
             eq.read_port("aocs.mtq.dipole_y")))
        mz = max(-MAX_DIPOLE_AM2, min(MAX_DIPOLE_AM2,
             eq.read_port("aocs.mtq.dipole_z")))

        # Read B field
        bx = eq.read_port("aocs.mtq.b_field_x")
        by = eq.read_port("aocs.mtq.b_field_y")
        bz = eq.read_port("aocs.mtq.b_field_z")

        # Torque = m × B (cross product)
        tx = my * bz - mz * by
        ty = mz * bx - mx * bz
        tz = mx * by - my * bx

        # Temperature (resistive heating)
        dipole_mag_sq = mx*mx + my*my + mz*mz
        state["temperature"] += (
            TEMP_RISE_COEFF * dipole_mag_sq * dt
            - COOLING_RATE * (state["temperature"] - AMBIENT_TEMP_C) * dt
        )

        eq.write_port("aocs.mtq.torque_x", tx)
        eq.write_port("aocs.mtq.torque_y", ty)
        eq.write_port("aocs.mtq.torque_z", tz)
        eq.write_port("aocs.mtq.status", 1.0)

    return NativeEquipment(
        equipment_id="mtq",
        ports=[
            PortDefinition("aocs.mtq.power_enable", PortDirection.IN,
                           description="Power enable"),
            PortDefinition("aocs.mtq.dipole_x", PortDirection.IN,
                           unit="Am2", description="Dipole X command"),
            PortDefinition("aocs.mtq.dipole_y", PortDirection.IN,
                           unit="Am2", description="Dipole Y command"),
            PortDefinition("aocs.mtq.dipole_z", PortDirection.IN,
                           unit="Am2", description="Dipole Z command"),
            PortDefinition("aocs.mtq.b_field_x", PortDirection.IN,
                           unit="T", description="B field X from MAG"),
            PortDefinition("aocs.mtq.b_field_y", PortDirection.IN,
                           unit="T", description="B field Y from MAG"),
            PortDefinition("aocs.mtq.b_field_z", PortDirection.IN,
                           unit="T", description="B field Z from MAG"),
            PortDefinition("aocs.mtq.torque_x", PortDirection.OUT,
                           unit="Nm", description="Generated torque X"),
            PortDefinition("aocs.mtq.torque_y", PortDirection.OUT,
                           unit="Nm", description="Generated torque Y"),
            PortDefinition("aocs.mtq.torque_z", PortDirection.OUT,
                           unit="Nm", description="Generated torque Z"),
            PortDefinition("aocs.mtq.status", PortDirection.OUT,
                           description="Status (0=off, 1=nominal)"),
        ],
        step_fn=_mtq_step,
        sync_protocol=sync_protocol,
        store=store,
        command_store=command_store,
    )
