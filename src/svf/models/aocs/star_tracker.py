"""
SVF Star Tracker Equipment
Attitude sensor model with quaternion output, noise,
sun blinding and acquisition time.

Physics:
- Internal attitude propagator: constant-rate rotation
- Measurement noise: white noise + bias on quaternion components
- Sun blinding: output invalid when sun_angle < sun_exclusion_deg
- Acquisition: acquisition_time_s from cold start before valid output
- Temperature: rises under operation, affects noise level

Interface: SpaceWire (primary), MIL1553_RT (secondary)

Implements: SVF-DEV-038
"""

from __future__ import annotations

from typing import Any, Optional

import logging
import math
import random

from svf.core.abstractions import SyncProtocol
from svf.core.equipment import PortDefinition, PortDirection
from svf.core.native_equipment import NativeEquipment
from svf.stores.parameter_store import ParameterStore
from svf.stores.command_store import CommandStore

logger = logging.getLogger(__name__)

# ST modes
MODE_OFF       = 0
MODE_ACQUIRING = 1
MODE_TRACKING  = 2


def _normalise_quaternion(
    w: float, x: float, y: float, z: float
) -> tuple[float, float, float, float]:
    """Normalise quaternion to unit length."""
    mag = math.sqrt(w*w + x*x + y*y + z*z)
    if mag < 1e-10:
        return 1.0, 0.0, 0.0, 0.0
    return w/mag, x/mag, y/mag, z/mag


def _propagate_quaternion(
    w: float, x: float, y: float, z: float,
    rate_x: float, rate_y: float, rate_z: float,
    dt: float,
) -> tuple[float, float, float, float]:
    """
    Propagate quaternion by angular rate over dt seconds.
    Uses first-order quaternion kinematics.
    """
    half_dt = 0.5 * dt
    dw = -(rate_x*x + rate_y*y + rate_z*z) * half_dt
    dx =  (rate_x*w + rate_z*y - rate_y*z) * half_dt
    dy =  (rate_y*w - rate_z*x + rate_x*z) * half_dt
    dz =  (rate_z*w + rate_y*x - rate_x*y) * half_dt
    return _normalise_quaternion(w+dw, x+dx, y+dy, z+dz)


def make_star_tracker(
    sync_protocol: SyncProtocol,
    store: ParameterStore,
    command_store: Optional[CommandStore] = None,
    equipment_id: str = "str1",
    initial_quaternion: tuple[float, float, float, float] = (1.0, 0.0, 0.0, 0.0),
    body_rate_rad_s: tuple[float, float, float] = (0.0, 0.001, 0.0),
    seed: Optional[int] = None,
    hardware_profile: Optional[str] = None,
    hardware_dir: Optional[str] = None,
) -> NativeEquipment:
    """
    Create a StarTracker NativeEquipment.

    Args:
        equipment_id:       Instance name (e.g. 'str1', 'str2'). Port names
                            use the form 'aocs.<equipment_id>.<signal>'.
        initial_quaternion: Starting attitude (w, x, y, z)
        body_rate_rad_s:    Constant body rate for propagation (rad/s)
        seed:               Random seed for reproducible noise
        hardware_profile:   Profile name (e.g. 'str_redwire_ct633').
                            Overrides built-in defaults when provided.
        hardware_dir:       Directory to search for profile YAML files.
    """
    # Physics constants  -  per-instance locals, overridden by hardware profile
    sun_exclusion_deg  = 30.0
    sun_degraded_deg   = 45.0
    acquisition_time_s = 10.0
    base_noise_std     = 0.0001
    temp_noise_coeff   = 0.00001
    ambient_temp_c     = 20.0
    nominal_temp_c     = 35.0
    temp_rise_rate     = 0.1
    cooling_rate       = 0.05

    if hardware_profile is not None:
        from svf.config.hardware_profile import load_hardware_profile
        p = load_hardware_profile(hardware_profile, hardware_dir)
        sun_exclusion_deg  = p.get("sun_exclusion_deg",  sun_exclusion_deg)
        sun_degraded_deg   = p.get("sun_degraded_deg",   sun_degraded_deg)
        acquisition_time_s = p.get("acquisition_time_s", acquisition_time_s)
        base_noise_std     = p.get("base_noise_std",     base_noise_std)
        temp_noise_coeff   = p.get("temp_noise_coeff",   temp_noise_coeff)
        ambient_temp_c     = p.get("temp_ambient_degc",  ambient_temp_c)
        nominal_temp_c     = p.get("temp_nominal_degc",  nominal_temp_c)
        temp_rise_rate     = p.get("temp_rise_rate",     temp_rise_rate)
        cooling_rate       = p.get("cooling_rate",       cooling_rate)

    rng = random.Random(seed)
    _pfx = f"aocs.{equipment_id}"

    state: dict[str, Any] = {
        "q_w": initial_quaternion[0],
        "q_x": initial_quaternion[1],
        "q_y": initial_quaternion[2],
        "q_z": initial_quaternion[3],
        "rate": body_rate_rad_s,
        "mode": MODE_OFF,
        "acq_elapsed": 0.0,
        "temperature": ambient_temp_c,
        "powered": False,
    }

    def _st_step(eq: NativeEquipment, t: float, dt: float) -> None:
        power_enable = eq.read_port(f"{_pfx}.power_enable")
        sun_angle    = eq.read_port(f"{_pfx}.sun_angle")

        powered = power_enable > 0.5

        if powered and not state["powered"]:
            state["mode"] = MODE_ACQUIRING
            state["acq_elapsed"] = 0.0
            logger.info("[%s] Powered on at t=%.1fs  -  acquiring", equipment_id, t)
        elif not powered and state["powered"]:
            state["mode"] = MODE_OFF
            state["acq_elapsed"] = 0.0
            logger.info("[%s] Powered off at t=%.1fs", equipment_id, t)
        state["powered"] = powered

        # Temperature model
        if powered:
            state["temperature"] += temp_rise_rate * (
                nominal_temp_c - state["temperature"]
            ) * dt
        else:
            state["temperature"] -= cooling_rate * (
                state["temperature"] - ambient_temp_c
            ) * dt
        state["temperature"] = max(ambient_temp_c, state["temperature"])

        state["q_w"], state["q_x"], state["q_y"], state["q_z"] = \
            _propagate_quaternion(
                state["q_w"], state["q_x"],
                state["q_y"], state["q_z"],
                state["rate"][0], state["rate"][1], state["rate"][2],
                dt,
            )

        # Variable acquisition time  -  faster when spacecraft is slow
        gx = eq._port_values.get("aocs.gyro.rate_x", 0.0)
        gy = eq._port_values.get("aocs.gyro.rate_y", 0.0)
        gz = eq._port_values.get("aocs.gyro.rate_z", 0.0)
        gyro_rate = math.sqrt(gx**2 + gy**2 + gz**2)
        rate_factor = 1.0 + min(2.0, gyro_rate / 0.5)
        effective_acq_time = acquisition_time_s * rate_factor

        if state["mode"] == MODE_ACQUIRING:
            state["acq_elapsed"] += dt
            progress = min(1.0, state["acq_elapsed"] / effective_acq_time)
            if state["acq_elapsed"] >= effective_acq_time:
                state["mode"] = MODE_TRACKING
                logger.info("[%s] Acquisition complete at t=%.1fs", equipment_id, t)
        elif state["mode"] == MODE_TRACKING:
            progress = 1.0
        else:
            progress = 0.0

        blinded = powered and (sun_angle < sun_exclusion_deg)
        if blinded:
            state["mode"] = MODE_ACQUIRING
            state["acq_elapsed"] = 0.0
            logger.warning(
                "[%s] Sun blinding at t=%.1fs (sun_angle=%.1f°)",
                equipment_id, t, sun_angle,
            )

        valid = (
            powered
            and state["mode"] == MODE_TRACKING
            and not blinded
        )

        base_noise = base_noise_std + temp_noise_coeff * (
            state["temperature"] - nominal_temp_c
        )
        sun_proximity_factor = 1.0
        if powered and sun_exclusion_deg < sun_angle < sun_degraded_deg:
            proximity = 1.0 - (sun_angle - sun_exclusion_deg) / (
                sun_degraded_deg - sun_exclusion_deg
            )
            sun_proximity_factor = 1.0 + 9.0 * proximity

        if valid:
            noise_std = base_noise * sun_proximity_factor
            q_w = state["q_w"] + rng.gauss(0, noise_std)
            q_x = state["q_x"] + rng.gauss(0, noise_std)
            q_y = state["q_y"] + rng.gauss(0, noise_std)
            q_z = state["q_z"] + rng.gauss(0, noise_std)
            q_w, q_x, q_y, q_z = _normalise_quaternion(q_w, q_x, q_y, q_z)
        elif powered and state["mode"] == MODE_ACQUIRING and progress > 0.5:
            acq_noise = base_noise * 100.0 * (1.0 - progress)
            q_w = state["q_w"] + rng.gauss(0, acq_noise)
            q_x = state["q_x"] + rng.gauss(0, acq_noise)
            q_y = state["q_y"] + rng.gauss(0, acq_noise)
            q_z = state["q_z"] + rng.gauss(0, acq_noise)
            q_w, q_x, q_y, q_z = _normalise_quaternion(q_w, q_x, q_y, q_z)
        else:
            q_w, q_x, q_y, q_z = 0.0, 0.0, 0.0, 0.0

        eq.write_port(f"{_pfx}.quaternion_w",        q_w)
        eq.write_port(f"{_pfx}.quaternion_x",        q_x)
        eq.write_port(f"{_pfx}.quaternion_y",        q_y)
        eq.write_port(f"{_pfx}.quaternion_z",        q_z)
        eq.write_port(f"{_pfx}.validity",            1.0 if valid else 0.0)
        eq.write_port(f"{_pfx}.mode",                float(state["mode"]))
        eq.write_port(f"{_pfx}.temperature",         state["temperature"])
        eq.write_port(f"{_pfx}.acquisition_progress", progress)

    eq = NativeEquipment(
        equipment_id=equipment_id,
        ports=[
            PortDefinition(f"{_pfx}.power_enable", PortDirection.IN,
                           description="Power enable (0=off, 1=on)"),
            PortDefinition(f"{_pfx}.sun_angle", PortDirection.IN,
                           unit="deg",
                           description="Sun angle for blinding detection"),
            PortDefinition(f"{_pfx}.quaternion_w", PortDirection.OUT,
                           description="Attitude quaternion W"),
            PortDefinition(f"{_pfx}.quaternion_x", PortDirection.OUT,
                           description="Attitude quaternion X"),
            PortDefinition(f"{_pfx}.quaternion_y", PortDirection.OUT,
                           description="Attitude quaternion Y"),
            PortDefinition(f"{_pfx}.quaternion_z", PortDirection.OUT,
                           description="Attitude quaternion Z"),
            PortDefinition(f"{_pfx}.validity", PortDirection.OUT,
                           description="Measurement validity (0=invalid, 1=valid)"),
            PortDefinition(f"{_pfx}.mode", PortDirection.OUT,
                           description="ST mode (0=off, 1=acquiring, 2=tracking)"),
            PortDefinition(f"{_pfx}.temperature", PortDirection.OUT,
                           unit="degC",
                           description="Detector temperature"),
            PortDefinition(f"{_pfx}.acquisition_progress", PortDirection.OUT,
                           description="Acquisition progress (0.0-1.0)"),
        ],
        step_fn=_st_step,
        sync_protocol=sync_protocol,
        store=store,
        command_store=command_store,
    )
    eq._port_values[f"{_pfx}.temperature"] = ambient_temp_c
    eq._port_values[f"{_pfx}.sun_angle"]   = 90.0  # safe default
    return eq
