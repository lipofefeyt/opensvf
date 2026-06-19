"""
SVF Reaction Wheel Equipment
MIL-STD-1553 Remote Terminal model with realistic physics.

M6: Basic torque integration, speed limits
M8: Bearing friction (Coulomb + viscous), temperature modelling,
    over-temperature protection

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

_rpm_per_rad_s = 60.0 / (2.0 * math.pi)
_rad_s_per_rpm = (2.0 * math.pi) / 60.0


def make_reaction_wheel(
    sync_protocol: SyncProtocol,
    store: ParameterStore,
    command_store: Optional[CommandStore] = None,
    equipment_id: str = "rw1",
    hardware_profile: Optional[str] = None,
    hardware_dir: Optional[str] = None,
) -> NativeEquipment:
    """
    Create a ReactionWheel NativeEquipment.

    Args:
        equipment_id:     Instance name (e.g. 'rw1', 'rw2'). Port names use
                          the form 'aocs.<equipment_id>.<signal>'.
        hardware_profile: Profile name (e.g. 'rw_sinclair_rw003').
                          Overrides built-in defaults when provided.
        hardware_dir:     Directory to search for profile YAML files.
    """
    # Physics constants  -  per-instance locals, overridden by hardware profile
    max_speed_rpm          = 6000.0
    moment_of_inertia_kgms = 0.001
    coulomb_friction       = 5.0
    viscous_friction       = 0.01
    ambient_temp_c         = 20.0
    temp_rise_coeff        = 0.1
    cooling_rate           = 0.05
    max_temp_c             = 80.0
    temp_derating_factor   = 0.5

    if hardware_profile is not None:
        from svf.config.hardware_profile import load_hardware_profile
        p = load_hardware_profile(hardware_profile, hardware_dir)
        max_speed_rpm          = p.get("max_speed_rpm",                  max_speed_rpm)
        moment_of_inertia_kgms = p.get("moment_of_inertia_kgm2",        moment_of_inertia_kgms)
        coulomb_friction       = p.get("friction_coulomb_rpm_s",         coulomb_friction)
        viscous_friction       = p.get("friction_viscous_rpm_s_per_rpm", viscous_friction)
        ambient_temp_c         = p.get("temp_ambient_degc",              ambient_temp_c)
        temp_rise_coeff        = p.get("temp_rise_coeff",                temp_rise_coeff)
        max_temp_c             = p.get("temp_max_degc",                  max_temp_c)

    min_speed_rpm = -max_speed_rpm
    _pfx = f"aocs.{equipment_id}"

    def _rw_step(eq: NativeEquipment, t: float, dt: float) -> None:
        torque = eq.read_port(f"{_pfx}.torque_cmd")
        speed  = eq.read_port(f"{_pfx}.speed")
        temp   = eq.read_port(f"{_pfx}.temperature")

        effective_torque = torque
        if temp > max_temp_c:
            effective_torque *= temp_derating_factor
            logger.warning(
                "[%s] t=%.1fs over-temperature %.1f°C  -  torque derated to %.3f Nm",
                equipment_id, t, temp, effective_torque,
            )

        # Torque → angular acceleration (rpm/s)
        acceleration = (effective_torque / moment_of_inertia_kgms) * _rpm_per_rad_s

        # Bearing friction (Coulomb + viscous)
        if abs(speed) > 0.1:
            coulomb = -coulomb_friction * (1.0 if speed > 0 else -1.0)
        else:
            coulomb = 0.0
        viscous  = -viscous_friction * speed
        friction = coulomb + viscous

        new_speed = speed + (acceleration + friction) * dt
        new_speed = max(min_speed_rpm, min(max_speed_rpm, new_speed))

        # Temperature: bearing dissipation heats the wheel, ambient cools it
        omega_rad_s    = abs(speed) * _rad_s_per_rpm
        friction_power = abs(friction) * moment_of_inertia_kgms * _rad_s_per_rpm * omega_rad_s
        new_temp = temp + temp_rise_coeff * friction_power * dt - cooling_rate * (temp - ambient_temp_c) * dt
        new_temp = max(ambient_temp_c, new_temp)

        status = 0.0 if temp > max_temp_c else 1.0

        eq.write_port(f"{_pfx}.speed",       new_speed)
        eq.write_port(f"{_pfx}.temperature", new_temp)
        eq.write_port(f"{_pfx}.status",      status)

    eq = NativeEquipment(
        equipment_id=equipment_id,
        ports=[
            PortDefinition(f"{_pfx}.torque_cmd", PortDirection.IN,
                           unit="Nm",
                           description="Torque command"),
            PortDefinition(f"{_pfx}.speed", PortDirection.OUT,
                           unit="rpm",
                           description="Wheel speed"),
            PortDefinition(f"{_pfx}.temperature", PortDirection.OUT,
                           unit="degC",
                           description="Bearing temperature"),
            PortDefinition(f"{_pfx}.status", PortDirection.OUT,
                           description="Status (1=nominal, 0=over-temp)"),
        ],
        step_fn=_rw_step,
        sync_protocol=sync_protocol,
        store=store,
        command_store=command_store,
    )
    eq._port_values[f"{_pfx}.temperature"] = ambient_temp_c
    return eq
