"""
SVF Magnetorquer Equipment
Magnetic torque actuator — generates torque by interacting
with the Earth's magnetic field.

Physics:
- Input: dipole moment commands (Am²) per axis
- Input: measured magnetic field (T) from magnetometer
- Output: generated torque = dipole × B_field
- Temperature rise proportional to dipole² (resistive heating)
- Saturation at max_dipole_am2

Implements: SVF-DEV-038
"""

from __future__ import annotations

import logging
import math
from typing import Optional

from svf.core.abstractions import SyncProtocol
from svf.core.equipment import PortDefinition, PortDirection
from svf.core.native_equipment import NativeEquipment
from svf.stores.parameter_store import ParameterStore
from svf.stores.command_store import CommandStore

logger = logging.getLogger(__name__)


def make_magnetorquer(
    sync_protocol: SyncProtocol,
    store: ParameterStore,
    command_store: Optional[CommandStore] = None,
    equipment_id: str = "mtq",
    hardware_profile: Optional[str] = None,
    hardware_dir: Optional[str] = None,
) -> NativeEquipment:
    """
    Create a Magnetorquer NativeEquipment.

    Args:
        equipment_id:     Instance name (e.g. 'mtq', 'mtq2'). Port names use
                          the form 'aocs.<equipment_id>.<signal>'.
        hardware_profile: Profile name to override built-in defaults.
        hardware_dir:     Directory to search for profile YAML files.

    Inputs:
        aocs.<id>.power_enable   — power on/off
        aocs.<id>.dipole_x/y/z  — commanded dipole moments (Am²)
        aocs.<id>.b_field_x/y/z — measured B field for torque calculation

    Outputs:
        aocs.<id>.torque_x/y/z  — generated torque (Nm) = dipole × B
        aocs.<id>.status        — 0=off, 1=nominal
        aocs.<id>.power_w       — power consumption (W)
    """
    # Physics constants — per-instance locals
    max_dipole_am2  = 10.0
    temp_rise_coeff = 0.005
    resistance_ohm  = 5.0
    rated_voltage_v = 5.0
    cooling_rate    = 0.02
    ambient_temp_c  = 20.0

    if hardware_profile is not None:
        from svf.config.hardware_profile import load_hardware_profile
        p = load_hardware_profile(hardware_profile, hardware_dir)
        max_dipole_am2  = p.get("max_dipole_am2",  max_dipole_am2)
        resistance_ohm  = p.get("resistance_ohm",  resistance_ohm)
        temp_rise_coeff = p.get("temp_rise_coeff", temp_rise_coeff)
        ambient_temp_c  = p.get("temp_ambient_degc", ambient_temp_c)

    _pfx   = f"aocs.{equipment_id}"
    state  = {"temperature": ambient_temp_c}

    def _mtq_step(eq: NativeEquipment, t: float, dt: float) -> None:
        powered = eq.read_port(f"{_pfx}.power_enable") > 0.5

        if not powered:
            state["temperature"] = max(
                ambient_temp_c,
                state["temperature"] - cooling_rate * dt,
            )
            eq.write_port(f"{_pfx}.torque_x", 0.0)
            eq.write_port(f"{_pfx}.torque_y", 0.0)
            eq.write_port(f"{_pfx}.torque_z", 0.0)
            eq.write_port(f"{_pfx}.status",   0.0)
            eq.write_port(f"{_pfx}.power_w",  0.0)
            return

        # Read and saturate dipole commands
        mx = max(-max_dipole_am2, min(max_dipole_am2,
             eq.read_port(f"{_pfx}.dipole_x")))
        my = max(-max_dipole_am2, min(max_dipole_am2,
             eq.read_port(f"{_pfx}.dipole_y")))
        mz = max(-max_dipole_am2, min(max_dipole_am2,
             eq.read_port(f"{_pfx}.dipole_z")))

        bx = eq.read_port(f"{_pfx}.b_field_x")
        by = eq.read_port(f"{_pfx}.b_field_y")
        bz = eq.read_port(f"{_pfx}.b_field_z")

        # Torque = m × B (cross product)
        tx = my * bz - mz * by
        ty = mz * bx - mx * bz
        tz = mx * by - my * bx

        # Temperature (resistive heating)
        dipole_mag_sq = mx*mx + my*my + mz*mz
        state["temperature"] += (
            temp_rise_coeff * dipole_mag_sq * dt
            - cooling_rate * (state["temperature"] - ambient_temp_c) * dt
        )

        eq.write_port(f"{_pfx}.torque_x", tx)
        eq.write_port(f"{_pfx}.torque_y", ty)
        eq.write_port(f"{_pfx}.torque_z", tz)
        eq.write_port(f"{_pfx}.status",   1.0)

        duty    = min(1.0, math.sqrt(mx**2 + my**2 + mz**2) / max_dipole_am2)
        power_w = (rated_voltage_v ** 2 / resistance_ohm) * duty
        eq.write_port(f"{_pfx}.power_w", power_w)

    return NativeEquipment(
        equipment_id=equipment_id,
        ports=[
            PortDefinition(f"{_pfx}.power_enable", PortDirection.IN,
                           description="Power enable"),
            PortDefinition(f"{_pfx}.dipole_x", PortDirection.IN,
                           unit="Am2", description="Dipole X command"),
            PortDefinition(f"{_pfx}.dipole_y", PortDirection.IN,
                           unit="Am2", description="Dipole Y command"),
            PortDefinition(f"{_pfx}.dipole_z", PortDirection.IN,
                           unit="Am2", description="Dipole Z command"),
            PortDefinition(f"{_pfx}.b_field_x", PortDirection.IN,
                           unit="T", description="B field X from MAG"),
            PortDefinition(f"{_pfx}.b_field_y", PortDirection.IN,
                           unit="T", description="B field Y from MAG"),
            PortDefinition(f"{_pfx}.b_field_z", PortDirection.IN,
                           unit="T", description="B field Z from MAG"),
            PortDefinition(f"{_pfx}.torque_x", PortDirection.OUT,
                           unit="Nm", description="Generated torque X"),
            PortDefinition(f"{_pfx}.torque_y", PortDirection.OUT,
                           unit="Nm", description="Generated torque Y"),
            PortDefinition(f"{_pfx}.torque_z", PortDirection.OUT,
                           unit="Nm", description="Generated torque Z"),
            PortDefinition(f"{_pfx}.status", PortDirection.OUT,
                           description="Status (0=off, 1=nominal)"),
            PortDefinition(f"{_pfx}.power_w", PortDirection.OUT,
                           unit="W", description="Power consumption"),
        ],
        step_fn=_mtq_step,
        sync_protocol=sync_protocol,
        store=store,
        command_store=command_store,
    )
