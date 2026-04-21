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
from typing import Optional

from svf.core.abstractions import SyncProtocol
from svf.core.equipment import PortDefinition, PortDirection
from svf.core.native_equipment import NativeEquipment
from svf.stores.parameter_store import ParameterStore
from svf.stores.command_store import CommandStore
try:
    import importlib.util as _importlib_util
except Exception:
    _HW_AVAILABLE = False

logger = logging.getLogger(__name__)

# Speed limits
MAX_SPEED_RPM          = 6000.0
MOMENT_OF_INERTIA_KGMS = 0.001   # kg·m² — RW rotor inertia
MIN_SPEED_RPM   = -6000.0

# Friction coefficients
COULOMB_FRICTION = 5.0    # rpm/s constant drag (direction-opposing)
VISCOUS_FRICTION = 0.01   # rpm/s per rpm (speed-dependent drag, τ=100s)

# Temperature model
AMBIENT_TEMP_C       = 20.0   # degC ambient
TEMP_RISE_COEFF      = 0.1    # degC per Joule of bearing dissipation
COOLING_RATE         = 0.05   # degC per second towards ambient
MAX_TEMP_C           = 80.0   # degC over-temperature threshold
TEMP_DERATING_FACTOR = 0.5    # torque reduction above max temp


def _rw_step(eq: NativeEquipment, t: float, dt: float) -> None:
    """
    Reaction wheel physics with bearing friction and temperature.
    """
    torque = eq.read_port("aocs.rw1.torque_cmd")
    speed  = eq.read_port("aocs.rw1.speed")
    temp   = eq.read_port("aocs.rw1.temperature")

    # Over-temperature protection — derate torque
    effective_torque = torque
    if temp > MAX_TEMP_C:
        effective_torque *= TEMP_DERATING_FACTOR
        logger.warning(
            f"[rw1] Over-temperature {temp:.1f}°C — "
            f"torque derated to {effective_torque:.3f} Nm"
        )

    # Torque → angular acceleration
    # α [rad/s²] = τ [Nm] / J [kg·m²]
    # α [rpm/s]  = α [rad/s²] × 60 / (2π)
    _RPM_PER_RAD_S = 60.0 / (2.0 * 3.14159265358979)
    acceleration = (effective_torque / MOMENT_OF_INERTIA_KGMS) * _RPM_PER_RAD_S

    # Bearing friction (Coulomb + viscous)
    if abs(speed) > 0.1:
        coulomb = -COULOMB_FRICTION * (1.0 if speed > 0 else -1.0)
    else:
        coulomb = 0.0
    viscous = -VISCOUS_FRICTION * speed
    friction = coulomb + viscous

    # Integrate speed
    new_speed = speed + (acceleration + friction) * dt
    new_speed = max(MIN_SPEED_RPM, min(MAX_SPEED_RPM, new_speed))

    # Temperature model
    # Power dissipated by bearing friction [W] = friction_torque × ω [rad/s]
    # friction_torque [Nm] = |friction [rpm/s]| × J / (60/2π)
    _RPM_S_TO_RAD_S2 = (2.0 * 3.14159265358979) / 60.0
    omega_rad_s = abs(speed) * _RPM_S_TO_RAD_S2
    friction_power = abs(friction) * MOMENT_OF_INERTIA_KGMS * _RPM_S_TO_RAD_S2 * omega_rad_s
    temp_rise = TEMP_RISE_COEFF * friction_power * dt
    temp_cool   = COOLING_RATE * (temp - AMBIENT_TEMP_C) * dt
    new_temp    = temp + temp_rise - temp_cool
    new_temp    = max(AMBIENT_TEMP_C, new_temp)

    # Status: 1=nominal, 0=over-temperature (based on input temp before cooling)
    status = 0.0 if temp > MAX_TEMP_C else 1.0

    eq.write_port("aocs.rw1.speed",       new_speed)
    eq.write_port("aocs.rw1.temperature", new_temp)
    eq.write_port("aocs.rw1.status",      status)


def make_reaction_wheel(
    sync_protocol: SyncProtocol,
    store: ParameterStore,
    command_store: Optional[CommandStore] = None,
    hardware_profile: Optional[str] = None,
    hardware_dir: str = "srdb/data/hardware",
) -> NativeEquipment:
    """
    Create a ReactionWheel NativeEquipment.

    Args:
        hardware_profile: SRDB hardware profile ID (e.g. 'rw_sinclair_rw003').
                         If None, uses built-in default constants.
        hardware_dir:    Directory containing hardware YAML profiles.

    Example:
        rw = make_reaction_wheel(sync, store, profile='rw_sinclair_rw003')
    """
    global MAX_SPEED_RPM, MIN_SPEED_RPM, COULOMB_FRICTION
    global VISCOUS_FRICTION, TEMP_RISE_COEFF, MAX_TEMP_C, AMBIENT_TEMP_C
    global MOMENT_OF_INERTIA_KGMS

    if hardware_profile is not None:
        from svf.config.hardware_profile import load_hardware_profile
        profile = load_hardware_profile(hardware_profile)
    eq = NativeEquipment(
        equipment_id="rw1",
        ports=[
            PortDefinition("aocs.rw1.torque_cmd", PortDirection.IN,
                           unit="Nm",
                           description="Torque command from 1553 bus SA1"),
            PortDefinition("aocs.rw1.speed", PortDirection.OUT,
                           unit="rpm",
                           description="Wheel speed"),
            PortDefinition("aocs.rw1.temperature", PortDirection.OUT,
                           unit="degC",
                           description="Bearing temperature"),
            PortDefinition("aocs.rw1.status", PortDirection.OUT,
                           description="Status (1=nominal, 0=over-temp)"),
        ],
        step_fn=_rw_step,
        sync_protocol=sync_protocol,
        store=store,
        command_store=command_store,
    )
    # Set initial temperature to ambient
    eq._port_values["aocs.rw1.temperature"] = AMBIENT_TEMP_C
    return eq
