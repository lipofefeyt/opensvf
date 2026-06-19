"""
SVF Thruster Equipment Model

Models a spacecraft thruster with propellant mass tracking,
temperature model, and minimum pulse width enforcement.

Ports:
  IN:  aocs.<id>.enable       -  1=fire, 0=off
       aocs.<id>.thrust_cmd   -  commanded thrust [N]
  OUT: aocs.<id>.thrust       -  actual thrust [N]
       aocs.<id>.temperature  -  thruster temperature [degC]
       aocs.<id>.propellant   -  remaining propellant [kg]
       aocs.<id>.status       -  0=off, 1=nominal, 2=low_prop, 3=empty, 4=over_temp

Physics:
  Δm = thrust / (Isp × g0) × dt   (propellant consumption)
  T_rise = temp_rise_coeff × thrust² × dt
  T_cool = cooling_rate × (T - T_ambient) × dt

Implements: SVF-DEV-080
"""
from __future__ import annotations

import logging
from typing import Optional

from svf.core.abstractions import SyncProtocol
from svf.core.native_equipment import NativeEquipment
from svf.core.equipment import PortDefinition, PortDirection
from svf.stores.parameter_store import ParameterStore
from svf.stores.command_store import CommandStore

logger = logging.getLogger(__name__)

# Physical constant
_G0_M_S2 = 9.80665

# Public status codes  -  importable by tests and external consumers
STATUS_OFF       = 0.0
STATUS_NOMINAL   = 1.0
STATUS_LOW_PROP  = 2.0
STATUS_EMPTY     = 3.0
STATUS_OVER_TEMP = 4.0

# Public defaults  -  exported for tests
INITIAL_PROPELLANT_KG = 0.5
AMBIENT_TEMP_C        = 20.0


def make_thruster(
    sync_protocol: SyncProtocol,
    store: ParameterStore,
    command_store: Optional[CommandStore] = None,
    equipment_id: str = "thr1",
    hardware_profile: Optional[str] = None,
    hardware_dir: Optional[str] = None,
) -> NativeEquipment:
    """
    Create a Thruster NativeEquipment.

    Args:
        equipment_id:     Instance name (e.g. 'thr1', 'thr2'). Port names use
                          the form 'aocs.<equipment_id>.<signal>'.
        hardware_profile: Profile name (e.g. 'thr_moog_monarc_1').
        hardware_dir:     Directory to search for profile YAML files.
    """
    # Physics constants  -  per-instance locals
    max_thrust_n           = 1.0
    min_thrust_n           = 0.01
    isp_s                  = 70.0
    initial_propellant_kg  = INITIAL_PROPELLANT_KG
    temp_rise_coeff        = 2.0
    ambient_temp_c         = AMBIENT_TEMP_C
    max_temp_c             = 120.0
    cooling_rate           = 0.05
    low_propellant_frac    = 0.1
    min_on_time_s          = 0.01  # noqa: F841  -  reserved for future use

    if hardware_profile is not None:
        from svf.config.hardware_profile import load_hardware_profile
        p = load_hardware_profile(hardware_profile, hardware_dir)
        max_thrust_n          = p.get("max_thrust_n",          max_thrust_n)
        min_thrust_n          = p.get("min_thrust_n",          min_thrust_n)
        isp_s                 = p.get("isp_s",                 isp_s)
        initial_propellant_kg = p.get("initial_propellant_kg", initial_propellant_kg)
        temp_rise_coeff       = p.get("temp_rise_coeff",       temp_rise_coeff)
        ambient_temp_c        = p.get("temp_ambient_degc",     ambient_temp_c)
        max_temp_c            = p.get("temp_max_degc",         max_temp_c)
        min_on_time_s         = p.get("min_on_time_s",         min_on_time_s)  # noqa: F841

    _pfx = f"aocs.{equipment_id}"

    def _thr_step(eq: NativeEquipment, t: float, dt: float) -> None:
        enable     = eq.read_port(f"{_pfx}.enable")
        thrust_cmd = eq.read_port(f"{_pfx}.thrust_cmd")
        temp       = eq.read_port(f"{_pfx}.temperature")
        prop       = eq.read_port(f"{_pfx}.propellant")

        firing = bool(enable > 0.5) and prop > 0.0 and temp < max_temp_c

        if firing:
            thrust     = max(min_thrust_n, min(max_thrust_n, thrust_cmd))
            mass_flow  = thrust / (isp_s * _G0_M_S2)
            new_prop   = max(0.0, prop - mass_flow * dt)
            temp_rise  = temp_rise_coeff * (thrust ** 2) * dt
        else:
            thrust    = 0.0
            new_prop  = prop
            temp_rise = 0.0

        temp_cool = cooling_rate * (temp - ambient_temp_c) * dt
        new_temp  = max(ambient_temp_c, temp + temp_rise - temp_cool)

        if not firing:
            status = STATUS_OFF
        elif new_temp >= max_temp_c:
            status = STATUS_OVER_TEMP
            thrust = 0.0
            logger.warning("[%s] t=%.1fs over-temperature %.1f°C  -  thrust cut off",
                           equipment_id, t, new_temp)
        elif new_prop <= 0.0:
            status = STATUS_EMPTY
            thrust = 0.0
        elif new_prop < initial_propellant_kg * low_propellant_frac:
            status = STATUS_LOW_PROP
        else:
            status = STATUS_NOMINAL

        eq.write_port(f"{_pfx}.thrust",      thrust)
        eq.write_port(f"{_pfx}.temperature", new_temp)
        eq.write_port(f"{_pfx}.propellant",  new_prop)
        eq.write_port(f"{_pfx}.status",      status)

    eq = NativeEquipment(
        equipment_id=equipment_id,
        ports=[
            PortDefinition(f"{_pfx}.enable",      PortDirection.IN,
                           description="Fire command (1=fire)"),
            PortDefinition(f"{_pfx}.thrust_cmd",  PortDirection.IN,
                           unit="N", description="Commanded thrust"),
            PortDefinition(f"{_pfx}.thrust",      PortDirection.OUT,
                           unit="N", description="Actual thrust output"),
            PortDefinition(f"{_pfx}.temperature", PortDirection.OUT,
                           unit="degC", description="Thruster temperature"),
            PortDefinition(f"{_pfx}.propellant",  PortDirection.OUT,
                           unit="kg", description="Remaining propellant mass"),
            PortDefinition(f"{_pfx}.status",      PortDirection.OUT,
                           description="0=off 1=nominal 2=low_prop 3=empty 4=over_temp"),
        ],
        step_fn=_thr_step,
        sync_protocol=sync_protocol,
        store=store,
        command_store=command_store,
    )
    eq._port_values[f"{_pfx}.thrust"]      = 0.0
    eq._port_values[f"{_pfx}.temperature"] = ambient_temp_c
    eq._port_values[f"{_pfx}.propellant"]  = initial_propellant_kg
    eq._port_values[f"{_pfx}.status"]      = STATUS_OFF
    return eq
