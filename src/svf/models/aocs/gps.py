"""
SVF GPS Receiver Equipment Model

Models a spaceborne GPS receiver providing position and velocity
in Earth-Centred Inertial (ECI) frame.

Position and velocity truth comes from the KDE physics engine.
Gaussian noise is added per axis. Fix is lost during eclipse
(configurable) or cold acquisition period.

Ports:
  IN:  gps.power_enable        — 1=powered
       gps.truth.pos_x/y/z     — true ECI position [m] from KDE
       gps.truth.vel_x/y/z     — true ECI velocity [m/s] from KDE
       gps.eclipse              — 1=eclipse (from CSS model)
  OUT: gps.position_x/y/z      — measured ECI position [m]
       gps.velocity_x/y/z      — measured ECI velocity [m/s]
       gps.fix                  — 1=valid fix, 0=no fix
       gps.altitude_km          — altitude above sphere [km]
       gps.status               — 0=off, 1=acquiring, 2=fix, 3=eclipse_outage

Implements: SVF-DEV-081
"""
from __future__ import annotations

import logging
import math
from typing import Optional

from svf.core.abstractions import SyncProtocol
from svf.core.native_equipment import NativeEquipment
from svf.core.equipment import PortDefinition, PortDirection
from svf.stores.parameter_store import ParameterStore
from svf.stores.command_store import CommandStore

logger = logging.getLogger(__name__)

# Earth mean radius [m]
EARTH_RADIUS_M = 6_371_000.0

# Default parameters
POSITION_NOISE_M   = 5.0
VELOCITY_NOISE_M_S = 0.05
ACQUISITION_TIME_S = 30.0
UPDATE_RATE_HZ     = 1.0
ECLIPSE_OUTAGE     = True

# Status codes
STATUS_OFF             = 0.0
STATUS_ACQUIRING       = 1.0
STATUS_FIX             = 2.0
STATUS_ECLIPSE_OUTAGE  = 3.0

try:
    import importlib.util as _importlib_util
except Exception:
    _HW_AVAILABLE = False


def _gps_step(eq: NativeEquipment, t: float, dt: float) -> None:
    import random
    powered = eq.read_port("gps.power_enable") > 0.5
    eclipse = eq.read_port("gps.eclipse") > 0.5

    if not powered:
        eq.write_port("gps.position_x", 0.0)
        eq.write_port("gps.position_y", 0.0)
        eq.write_port("gps.position_z", 0.0)
        eq.write_port("gps.velocity_x", 0.0)
        eq.write_port("gps.velocity_y", 0.0)
        eq.write_port("gps.velocity_z", 0.0)
        eq.write_port("gps.fix",        0.0)
        eq.write_port("gps.altitude_km", 0.0)
        eq.write_port("gps.status",     STATUS_OFF)
        return

    # Eclipse outage
    if ECLIPSE_OUTAGE and eclipse:
        eq.write_port("gps.fix",    0.0)
        eq.write_port("gps.status", STATUS_ECLIPSE_OUTAGE)
        return

    # Acquisition period
    if t < ACQUISITION_TIME_S:
        eq.write_port("gps.fix",    0.0)
        eq.write_port("gps.status", STATUS_ACQUIRING)
        return

    # Get truth state from KDE
    px = eq.read_port("gps.truth.pos_x")
    py = eq.read_port("gps.truth.pos_y")
    pz = eq.read_port("gps.truth.pos_z")
    vx = eq.read_port("gps.truth.vel_x")
    vy = eq.read_port("gps.truth.vel_y")
    vz = eq.read_port("gps.truth.vel_z")

    # Add Gaussian noise
    rng = eq._rng  # type: ignore[attr-defined]
    eq.write_port("gps.position_x", px + rng.gauss(0.0, POSITION_NOISE_M))
    eq.write_port("gps.position_y", py + rng.gauss(0.0, POSITION_NOISE_M))
    eq.write_port("gps.position_z", pz + rng.gauss(0.0, POSITION_NOISE_M))
    eq.write_port("gps.velocity_x", vx + rng.gauss(0.0, VELOCITY_NOISE_M_S))
    eq.write_port("gps.velocity_y", vy + rng.gauss(0.0, VELOCITY_NOISE_M_S))
    eq.write_port("gps.velocity_z", vz + rng.gauss(0.0, VELOCITY_NOISE_M_S))

    # Altitude
    r = math.sqrt(px**2 + py**2 + pz**2)
    altitude_km = (r - EARTH_RADIUS_M) / 1000.0
    eq.write_port("gps.altitude_km", altitude_km)
    eq.write_port("gps.fix",         1.0)
    eq.write_port("gps.status",      STATUS_FIX)


def make_gps(
    sync_protocol: SyncProtocol,
    store: ParameterStore,
    command_store: Optional[CommandStore] = None,
    seed: Optional[int] = None,
    hardware_profile: Optional[str] = None,
    hardware_dir: str = "srdb/data/hardware",
) -> NativeEquipment:
    """
    Create a GPS Receiver NativeEquipment.

    Args:
        seed:             Random seed for noise (deterministic replay).
        hardware_profile: SRDB hardware profile ID (e.g. 'gps_novatel_oem7').
        hardware_dir:     Directory containing hardware YAML profiles.
    """
    import random
    global POSITION_NOISE_M, VELOCITY_NOISE_M_S
    global ACQUISITION_TIME_S, UPDATE_RATE_HZ, ECLIPSE_OUTAGE

    if hardware_profile is not None:
        from svf.config.hardware_profile import load_hardware_profile
        profile = load_hardware_profile(hardware_profile)
        POSITION_NOISE_M    = profile.get("position_noise_m",     POSITION_NOISE_M)
        VELOCITY_NOISE_M_S  = profile.get("velocity_noise_m_s",   VELOCITY_NOISE_M_S)
        ACQUISITION_TIME_S  = profile.get("acquisition_time_s",   ACQUISITION_TIME_S)
        UPDATE_RATE_HZ      = profile.get("update_rate_hz",       UPDATE_RATE_HZ)
        ECLIPSE_OUTAGE      = profile.get("eclipse_outage",       ECLIPSE_OUTAGE)

    rng = random.Random(seed)

    eq = NativeEquipment(
        equipment_id="gps",
        ports=[
            PortDefinition("gps.power_enable",   PortDirection.IN,
                           description="Power on/off"),
            PortDefinition("gps.truth.pos_x",    PortDirection.IN,
                           unit="m", description="True ECI position X"),
            PortDefinition("gps.truth.pos_y",    PortDirection.IN,
                           unit="m", description="True ECI position Y"),
            PortDefinition("gps.truth.pos_z",    PortDirection.IN,
                           unit="m", description="True ECI position Z"),
            PortDefinition("gps.truth.vel_x",    PortDirection.IN,
                           unit="m/s", description="True ECI velocity X"),
            PortDefinition("gps.truth.vel_y",    PortDirection.IN,
                           unit="m/s", description="True ECI velocity Y"),
            PortDefinition("gps.truth.vel_z",    PortDirection.IN,
                           unit="m/s", description="True ECI velocity Z"),
            PortDefinition("gps.eclipse",        PortDirection.IN,
                           description="Eclipse flag from CSS"),
            PortDefinition("gps.position_x",     PortDirection.OUT,
                           unit="m", description="Measured ECI position X"),
            PortDefinition("gps.position_y",     PortDirection.OUT,
                           unit="m", description="Measured ECI position Y"),
            PortDefinition("gps.position_z",     PortDirection.OUT,
                           unit="m", description="Measured ECI position Z"),
            PortDefinition("gps.velocity_x",     PortDirection.OUT,
                           unit="m/s", description="Measured ECI velocity X"),
            PortDefinition("gps.velocity_y",     PortDirection.OUT,
                           unit="m/s", description="Measured ECI velocity Y"),
            PortDefinition("gps.velocity_z",     PortDirection.OUT,
                           unit="m/s", description="Measured ECI velocity Z"),
            PortDefinition("gps.fix",            PortDirection.OUT,
                           description="1=valid fix"),
            PortDefinition("gps.altitude_km",    PortDirection.OUT,
                           unit="km", description="Altitude above sphere"),
            PortDefinition("gps.status",         PortDirection.OUT,
                           description="0=off 1=acquiring 2=fix 3=eclipse_outage"),
        ],
        step_fn=_gps_step,
        sync_protocol=sync_protocol,
        store=store,
        command_store=command_store,
    )
    eq._rng = rng  # type: ignore[attr-defined]
    eq._port_values["gps.fix"]        = 0.0
    eq._port_values["gps.status"]     = STATUS_OFF
    eq._port_values["gps.altitude_km"] = 0.0
    return eq
