"""
SVF Thruster Equipment Model

Models a spacecraft thruster with propellant mass tracking,
temperature model, and minimum pulse width enforcement.

Ports:
  IN:  aocs.thr{N}.enable       — 1=fire, 0=off
       aocs.thr{N}.thrust_cmd   — commanded thrust [N]
  OUT: aocs.thr{N}.thrust       — actual thrust [N]
       aocs.thr{N}.temperature  — thruster temperature [degC]
       aocs.thr{N}.propellant   — remaining propellant [kg]
       aocs.thr{N}.status       — 0=off, 1=nominal, 2=low_prop, 3=empty, 4=over_temp

Physics:
  Δm = thrust / (Isp × g0) × dt   (propellant consumption)
  T_rise = temp_rise_coeff × thrust² × dt
  T_cool = cooling_rate × (T - T_ambient) × dt

Implements: SVF-DEV-080
"""
from __future__ import annotations

import logging
from typing import Optional

from svf.abstractions import SyncProtocol
from svf.native_equipment import NativeEquipment
from svf.equipment import PortDefinition, PortDirection
from svf.parameter_store import ParameterStore
from svf.command_store import CommandStore

logger = logging.getLogger(__name__)

# Physical constants
G0_M_S2 = 9.80665  # standard gravity [m/s²]

# Default parameters
MAX_THRUST_N          = 1.0
MIN_THRUST_N          = 0.01
ISP_S                 = 70.0
INITIAL_PROPELLANT_KG = 0.5
TEMP_RISE_COEFF       = 2.0
AMBIENT_TEMP_C        = 20.0
MAX_TEMP_C            = 120.0
COOLING_RATE          = 0.05
LOW_PROPELLANT_FRAC   = 0.1   # fraction below which status=low_prop
MIN_ON_TIME_S         = 0.01

try:
    import importlib.util as _importlib_util
except Exception:
    _HW_AVAILABLE = False

# Status codes
STATUS_OFF       = 0.0
STATUS_NOMINAL   = 1.0
STATUS_LOW_PROP  = 2.0
STATUS_EMPTY     = 3.0
STATUS_OVER_TEMP = 4.0


def _thr_step(eq: NativeEquipment, t: float, dt: float) -> None:
    enable    = eq.read_port("aocs.thr1.enable")
    thrust_cmd = eq.read_port("aocs.thr1.thrust_cmd")
    temp      = eq.read_port("aocs.thr1.temperature")
    prop      = eq.read_port("aocs.thr1.propellant")

    firing = bool(enable > 0.5) and prop > 0.0 and temp < MAX_TEMP_C

    if firing:
        # Clamp thrust command
        thrust = max(MIN_THRUST_N, min(MAX_THRUST_N, thrust_cmd))
        # Propellant consumption: Tsiolkovsky
        mass_flow = thrust / (ISP_S * G0_M_S2)
        new_prop = max(0.0, prop - mass_flow * dt)
        # Temperature rise
        temp_rise = TEMP_RISE_COEFF * (thrust ** 2) * dt
    else:
        thrust = 0.0
        new_prop = prop
        temp_rise = 0.0

    # Cooling
    temp_cool = COOLING_RATE * (temp - AMBIENT_TEMP_C) * dt
    new_temp = max(AMBIENT_TEMP_C, temp + temp_rise - temp_cool)

    # Status
    if not firing:
        status = STATUS_OFF
    elif new_temp >= MAX_TEMP_C:
        status = STATUS_OVER_TEMP
        thrust = 0.0
        logger.warning(f"[thr1] Over-temperature {new_temp:.1f}°C — thrust cut off")
    elif new_prop <= 0.0:
        status = STATUS_EMPTY
        thrust = 0.0
    elif new_prop < INITIAL_PROPELLANT_KG * LOW_PROPELLANT_FRAC:
        status = STATUS_LOW_PROP
    else:
        status = STATUS_NOMINAL

    eq.write_port("aocs.thr1.thrust",      thrust)
    eq.write_port("aocs.thr1.temperature", new_temp)
    eq.write_port("aocs.thr1.propellant",  new_prop)
    eq.write_port("aocs.thr1.status",      status)


def make_thruster(
    sync_protocol: SyncProtocol,
    store: ParameterStore,
    command_store: Optional[CommandStore] = None,
    hardware_profile: Optional[str] = None,
    hardware_dir: str = "srdb/data/hardware",
) -> NativeEquipment:
    """
    Create a Thruster NativeEquipment.

    Args:
        hardware_profile: SRDB hardware profile ID (e.g. 'thr_moog_monarc_1').
        hardware_dir:    Directory containing hardware YAML profiles.
    """
    global MAX_THRUST_N, MIN_THRUST_N, ISP_S, INITIAL_PROPELLANT_KG
    global TEMP_RISE_COEFF, AMBIENT_TEMP_C, MAX_TEMP_C, MIN_ON_TIME_S

    if hardware_profile is not None:
        from svf.hardware_profile import load_hardware_profile
        profile = load_hardware_profile(hardware_profile)
        MAX_THRUST_N        = profile.get("max_thrust_n",         MAX_THRUST_N)
        MIN_THRUST_N        = profile.get("min_thrust_n",         MIN_THRUST_N)
        ISP_S               = profile.get("isp_s",                ISP_S)
        INITIAL_PROPELLANT_KG = profile.get("initial_propellant_kg", INITIAL_PROPELLANT_KG)
        TEMP_RISE_COEFF     = profile.get("temp_rise_coeff",      TEMP_RISE_COEFF)
        AMBIENT_TEMP_C      = profile.get("temp_ambient_degc",    AMBIENT_TEMP_C)
        MAX_TEMP_C          = profile.get("temp_max_degc",        MAX_TEMP_C)
        MIN_ON_TIME_S       = profile.get("min_on_time_s",        MIN_ON_TIME_S)

    eq = NativeEquipment(
        equipment_id="thr1",
        ports=[
            PortDefinition("aocs.thr1.enable",      PortDirection.IN,
                           description="Fire command (1=fire)"),
            PortDefinition("aocs.thr1.thrust_cmd",  PortDirection.IN,
                           unit="N",
                           description="Commanded thrust"),
            PortDefinition("aocs.thr1.thrust",      PortDirection.OUT,
                           unit="N",
                           description="Actual thrust output"),
            PortDefinition("aocs.thr1.temperature", PortDirection.OUT,
                           unit="degC",
                           description="Thruster temperature"),
            PortDefinition("aocs.thr1.propellant",  PortDirection.OUT,
                           unit="kg",
                           description="Remaining propellant mass"),
            PortDefinition("aocs.thr1.status",      PortDirection.OUT,
                           description="0=off 1=nominal 2=low_prop 3=empty 4=over_temp"),
        ],
        step_fn=_thr_step,
        sync_protocol=sync_protocol,
        store=store,
        command_store=command_store,
    )
    # Set initial values
    eq._port_values["aocs.thr1.thrust"]      = 0.0
    eq._port_values["aocs.thr1.temperature"] = AMBIENT_TEMP_C
    eq._port_values["aocs.thr1.propellant"]  = INITIAL_PROPELLANT_KG
    eq._port_values["aocs.thr1.status"]      = STATUS_OFF
    return eq
