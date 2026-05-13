"""
SVF GPS Receiver Equipment Model

Models a spaceborne GPS receiver providing position and velocity
in Earth-Centred Inertial (ECI) frame.

Position and velocity truth comes from the KDE physics engine.
Gaussian noise is added per axis. Fix is lost during eclipse
(configurable) or cold acquisition period.

Ports:
  IN:  <id>.power_enable    — 1=powered
       <id>.truth.pos_x/y/z — true ECI position [m] from KDE
       <id>.truth.vel_x/y/z — true ECI velocity [m/s] from KDE
       <id>.eclipse          — 1=eclipse (from CSS model)
  OUT: <id>.position_x/y/z  — measured ECI position [m]
       <id>.velocity_x/y/z  — measured ECI velocity [m/s]
       <id>.fix              — 1=valid fix, 0=no fix
       <id>.altitude_km      — altitude above sphere [km]
       <id>.status           — 0=off, 1=acquiring, 2=fix, 3=eclipse_outage

Implements: SVF-DEV-081
"""
from __future__ import annotations

import logging
import math
import random
from typing import Optional

from svf.core.abstractions import SyncProtocol
from svf.core.native_equipment import NativeEquipment
from svf.core.equipment import PortDefinition, PortDirection
from svf.stores.parameter_store import ParameterStore
from svf.stores.command_store import CommandStore

logger = logging.getLogger(__name__)

_EARTH_RADIUS_M = 6_371_000.0

# Public status codes — importable by tests and external consumers
STATUS_OFF            = 0.0
STATUS_ACQUIRING      = 1.0
STATUS_FIX            = 2.0
STATUS_ECLIPSE_OUTAGE = 3.0

# Default acquisition time — exported so tests can reference it
ACQUISITION_TIME_S = 30.0


def make_gps(
    sync_protocol: SyncProtocol,
    store: ParameterStore,
    command_store: Optional[CommandStore] = None,
    equipment_id: str = "gps",
    seed: Optional[int] = None,
    hardware_profile: Optional[str] = None,
    hardware_dir: Optional[str] = None,
) -> NativeEquipment:
    """
    Create a GPS Receiver NativeEquipment.

    Args:
        equipment_id:     Instance name (e.g. 'gps', 'gps2'). Port names use
                          the form '<equipment_id>.<signal>' (no aocs. prefix).
        seed:             Random seed for noise (deterministic replay).
        hardware_profile: Profile name (e.g. 'gps_novatel_oem7').
        hardware_dir:     Directory to search for profile YAML files.
    """
    # Physics constants — per-instance locals
    position_noise_m   = 5.0
    velocity_noise_m_s = 0.05
    acquisition_time_s = ACQUISITION_TIME_S
    update_rate_hz     = 1.0  # noqa: F841 — reserved for future decimation
    eclipse_outage     = True

    if hardware_profile is not None:
        from svf.config.hardware_profile import load_hardware_profile
        p = load_hardware_profile(hardware_profile, hardware_dir)
        position_noise_m   = p.get("position_noise_m",   position_noise_m)
        velocity_noise_m_s = p.get("velocity_noise_m_s", velocity_noise_m_s)
        acquisition_time_s = p.get("acquisition_time_s", acquisition_time_s)
        update_rate_hz     = p.get("update_rate_hz",     update_rate_hz)  # noqa: F841
        eclipse_outage     = p.get("eclipse_outage",     eclipse_outage)

    rng  = random.Random(seed)
    _pfx = equipment_id  # GPS uses plain id prefix, not aocs.<id>

    def _gps_step(eq: NativeEquipment, t: float, dt: float) -> None:
        powered = eq.read_port(f"{_pfx}.power_enable") > 0.5
        eclipse = eq.read_port(f"{_pfx}.eclipse") > 0.5

        if not powered:
            eq.write_port(f"{_pfx}.position_x",  0.0)
            eq.write_port(f"{_pfx}.position_y",  0.0)
            eq.write_port(f"{_pfx}.position_z",  0.0)
            eq.write_port(f"{_pfx}.velocity_x",  0.0)
            eq.write_port(f"{_pfx}.velocity_y",  0.0)
            eq.write_port(f"{_pfx}.velocity_z",  0.0)
            eq.write_port(f"{_pfx}.fix",          0.0)
            eq.write_port(f"{_pfx}.altitude_km",  0.0)
            eq.write_port(f"{_pfx}.status",       STATUS_OFF)
            return

        if eclipse_outage and eclipse:
            eq.write_port(f"{_pfx}.fix",    0.0)
            eq.write_port(f"{_pfx}.status", STATUS_ECLIPSE_OUTAGE)
            return

        if t < acquisition_time_s:
            eq.write_port(f"{_pfx}.fix",    0.0)
            eq.write_port(f"{_pfx}.status", STATUS_ACQUIRING)
            return

        px = eq.read_port(f"{_pfx}.truth.pos_x")
        py = eq.read_port(f"{_pfx}.truth.pos_y")
        pz = eq.read_port(f"{_pfx}.truth.pos_z")
        vx = eq.read_port(f"{_pfx}.truth.vel_x")
        vy = eq.read_port(f"{_pfx}.truth.vel_y")
        vz = eq.read_port(f"{_pfx}.truth.vel_z")

        eq.write_port(f"{_pfx}.position_x", px + rng.gauss(0.0, position_noise_m))
        eq.write_port(f"{_pfx}.position_y", py + rng.gauss(0.0, position_noise_m))
        eq.write_port(f"{_pfx}.position_z", pz + rng.gauss(0.0, position_noise_m))
        eq.write_port(f"{_pfx}.velocity_x", vx + rng.gauss(0.0, velocity_noise_m_s))
        eq.write_port(f"{_pfx}.velocity_y", vy + rng.gauss(0.0, velocity_noise_m_s))
        eq.write_port(f"{_pfx}.velocity_z", vz + rng.gauss(0.0, velocity_noise_m_s))

        r           = math.sqrt(px**2 + py**2 + pz**2)
        altitude_km = (r - _EARTH_RADIUS_M) / 1000.0
        eq.write_port(f"{_pfx}.altitude_km", altitude_km)
        eq.write_port(f"{_pfx}.fix",         1.0)
        eq.write_port(f"{_pfx}.status",      STATUS_FIX)

    eq = NativeEquipment(
        equipment_id=equipment_id,
        ports=[
            PortDefinition(f"{_pfx}.power_enable",  PortDirection.IN,
                           description="Power on/off"),
            PortDefinition(f"{_pfx}.truth.pos_x",   PortDirection.IN,
                           unit="m", description="True ECI position X"),
            PortDefinition(f"{_pfx}.truth.pos_y",   PortDirection.IN,
                           unit="m", description="True ECI position Y"),
            PortDefinition(f"{_pfx}.truth.pos_z",   PortDirection.IN,
                           unit="m", description="True ECI position Z"),
            PortDefinition(f"{_pfx}.truth.vel_x",   PortDirection.IN,
                           unit="m/s", description="True ECI velocity X"),
            PortDefinition(f"{_pfx}.truth.vel_y",   PortDirection.IN,
                           unit="m/s", description="True ECI velocity Y"),
            PortDefinition(f"{_pfx}.truth.vel_z",   PortDirection.IN,
                           unit="m/s", description="True ECI velocity Z"),
            PortDefinition(f"{_pfx}.eclipse",       PortDirection.IN,
                           description="Eclipse flag"),
            PortDefinition(f"{_pfx}.position_x",    PortDirection.OUT,
                           unit="m", description="Measured ECI position X"),
            PortDefinition(f"{_pfx}.position_y",    PortDirection.OUT,
                           unit="m", description="Measured ECI position Y"),
            PortDefinition(f"{_pfx}.position_z",    PortDirection.OUT,
                           unit="m", description="Measured ECI position Z"),
            PortDefinition(f"{_pfx}.velocity_x",    PortDirection.OUT,
                           unit="m/s", description="Measured ECI velocity X"),
            PortDefinition(f"{_pfx}.velocity_y",    PortDirection.OUT,
                           unit="m/s", description="Measured ECI velocity Y"),
            PortDefinition(f"{_pfx}.velocity_z",    PortDirection.OUT,
                           unit="m/s", description="Measured ECI velocity Z"),
            PortDefinition(f"{_pfx}.fix",           PortDirection.OUT,
                           description="1=valid fix"),
            PortDefinition(f"{_pfx}.altitude_km",   PortDirection.OUT,
                           unit="km", description="Altitude above sphere"),
            PortDefinition(f"{_pfx}.status",        PortDirection.OUT,
                           description="0=off 1=acquiring 2=fix 3=eclipse_outage"),
        ],
        step_fn=_gps_step,
        sync_protocol=sync_protocol,
        store=store,
        command_store=command_store,
    )
    eq._port_values[f"{_pfx}.fix"]         = 0.0
    eq._port_values[f"{_pfx}.status"]      = STATUS_OFF
    eq._port_values[f"{_pfx}.altitude_km"] = 0.0
    return eq
