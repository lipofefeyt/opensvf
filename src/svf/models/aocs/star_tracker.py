"""
SVF Star Tracker Equipment
Attitude sensor model with quaternion output, noise,
sun blinding and acquisition time.

Physics:
- Internal attitude propagator: constant-rate rotation
- Measurement noise: white noise + bias on quaternion components
- Sun blinding: output invalid when sun_angle < SUN_EXCLUSION_DEG
- Acquisition: ACQUISITION_TIME_S from cold start before valid output
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

# Sun exclusion angle — below this the ST is blinded
SUN_EXCLUSION_DEG   = 30.0   # degrees — hard exclusion cone
SUN_DEGRADED_DEG    = 45.0   # degrees — accuracy degradation begins

# Acquisition time from cold start
ACQUISITION_TIME_S  = 10.0

# Noise parameters
BASE_NOISE_STD      = 0.0001   # quaternion component std dev (nominal)
TEMP_NOISE_COEFF    = 0.00001  # additional noise per degC above nominal

# Temperature model
AMBIENT_TEMP_C      = 20.0
NOMINAL_TEMP_C      = 35.0    # operating temperature
TEMP_RISE_RATE      = 0.1     # degC/s towards operating temp
COOLING_RATE        = 0.05    # degC/s towards ambient when off

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
    initial_quaternion: tuple[float, float, float, float] = (1.0, 0.0, 0.0, 0.0),
    body_rate_rad_s: tuple[float, float, float] = (0.0, 0.001, 0.0),
    seed: Optional[int] = None,
) -> NativeEquipment:
    """
    Create a StarTracker NativeEquipment.

    Args:
        initial_quaternion: Starting attitude (w, x, y, z)
        body_rate_rad_s:    Constant body rate for propagation (rad/s)
        seed:               Random seed for reproducible noise
    """
    rng = random.Random(seed)

    # Internal state — captured in closure
    state: dict[str, Any] = {
        "q_w": initial_quaternion[0],
        "q_x": initial_quaternion[1],
        "q_y": initial_quaternion[2],
        "q_z": initial_quaternion[3],
        "rate": body_rate_rad_s,
        "mode": MODE_OFF,
        "acq_elapsed": 0.0,
        "temperature": AMBIENT_TEMP_C,
        "powered": False,
    }

    def _st_step(eq: NativeEquipment, t: float, dt: float) -> None:
        power_enable = eq.read_port("aocs.str1.power_enable")
        sun_angle    = eq.read_port("aocs.str1.sun_angle")

        powered = power_enable > 0.5

        # Power state transitions
        if powered and not state["powered"]:
            state["mode"] = MODE_ACQUIRING
            state["acq_elapsed"] = 0.0
            logger.info(f"[str1] Powered on at t={t:.1f}s — acquiring")
        elif not powered and state["powered"]:
            state["mode"] = MODE_OFF
            state["acq_elapsed"] = 0.0
            logger.info(f"[str1] Powered off at t={t:.1f}s")
        state["powered"] = powered

        # Temperature model
        if powered:
            state["temperature"] += TEMP_RISE_RATE * (
                NOMINAL_TEMP_C - state["temperature"]
            ) * dt
        else:
            state["temperature"] -= COOLING_RATE * (
                state["temperature"] - AMBIENT_TEMP_C
            ) * dt
        state["temperature"] = max(AMBIENT_TEMP_C, state["temperature"])

        # Propagate attitude
        state["q_w"], state["q_x"], state["q_y"], state["q_z"] = \
            _propagate_quaternion(
                state["q_w"], state["q_x"],
                state["q_y"], state["q_z"],
                state["rate"][0], state["rate"][1], state["rate"][2],
                dt,
            )

        # Variable acquisition time — faster if spacecraft is slow
        # Safe read — default 0.0 if gyro not connected
        gx = eq._port_values.get("aocs.gyro.rate_x", 0.0)
        gy = eq._port_values.get("aocs.gyro.rate_y", 0.0)
        gz = eq._port_values.get("aocs.gyro.rate_z", 0.0)
        gyro_rate = math.sqrt(gx**2 + gy**2 + gz**2)
        # At 0 rate: nominal ACQ_TIME. At >0.5 rad/s: up to 3x longer
        rate_factor = 1.0 + min(2.0, gyro_rate / 0.5)
        effective_acq_time = ACQUISITION_TIME_S * rate_factor

        # Acquisition progress
        if state["mode"] == MODE_ACQUIRING:
            state["acq_elapsed"] += dt
            progress = min(1.0, state["acq_elapsed"] / effective_acq_time)
            if state["acq_elapsed"] >= effective_acq_time:
                state["mode"] = MODE_TRACKING
                logger.info(f"[str1] Acquisition complete at t={t:.1f}s")
        elif state["mode"] == MODE_TRACKING:
            progress = 1.0
        else:
            progress = 0.0

        # Sun blinding check
        blinded = powered and (sun_angle < SUN_EXCLUSION_DEG)
        if blinded:
            state["mode"] = MODE_ACQUIRING
            state["acq_elapsed"] = 0.0
            logger.warning(
                f"[str1] Sun blinding at t={t:.1f}s "
                f"(sun_angle={sun_angle:.1f}°)"
            )

        # Validity
        valid = (
            powered
            and state["mode"] == MODE_TRACKING
            and not blinded
        )

        # Measurement noise — increases near sun exclusion cone
        base_noise = BASE_NOISE_STD + TEMP_NOISE_COEFF * (
            state["temperature"] - NOMINAL_TEMP_C
        )
        # Degrade accuracy near sun exclusion boundary
        sun_proximity_factor = 1.0
        if powered and SUN_EXCLUSION_DEG < sun_angle < SUN_DEGRADED_DEG:
            # Linearly degrade from 1x to 10x noise as sun approaches
            proximity = 1.0 - (sun_angle - SUN_EXCLUSION_DEG) / (
                SUN_DEGRADED_DEG - SUN_EXCLUSION_DEG
            )
            sun_proximity_factor = 1.0 + 9.0 * proximity

        # During acquisition: output degraded quaternion (not zero)
        # Noise reduces as acquisition progresses
        if valid:
            noise_std = base_noise * sun_proximity_factor
            q_w = state["q_w"] + rng.gauss(0, noise_std)
            q_x = state["q_x"] + rng.gauss(0, noise_std)
            q_y = state["q_y"] + rng.gauss(0, noise_std)
            q_z = state["q_z"] + rng.gauss(0, noise_std)
            q_w, q_x, q_y, q_z = _normalise_quaternion(q_w, q_x, q_y, q_z)
        elif powered and state["mode"] == MODE_ACQUIRING and progress > 0.5:
            # Half-acquired: output very noisy estimate
            acq_noise = base_noise * 100.0 * (1.0 - progress)
            q_w = state["q_w"] + rng.gauss(0, acq_noise)
            q_x = state["q_x"] + rng.gauss(0, acq_noise)
            q_y = state["q_y"] + rng.gauss(0, acq_noise)
            q_z = state["q_z"] + rng.gauss(0, acq_noise)
            q_w, q_x, q_y, q_z = _normalise_quaternion(q_w, q_x, q_y, q_z)
        else:
            q_w, q_x, q_y, q_z = 0.0, 0.0, 0.0, 0.0

        eq.write_port("aocs.str1.quaternion_w",        q_w)
        eq.write_port("aocs.str1.quaternion_x",        q_x)
        eq.write_port("aocs.str1.quaternion_y",        q_y)
        eq.write_port("aocs.str1.quaternion_z",        q_z)
        eq.write_port("aocs.str1.validity",            1.0 if valid else 0.0)
        eq.write_port("aocs.str1.mode",                float(state["mode"]))
        eq.write_port("aocs.str1.temperature",         state["temperature"])
        eq.write_port("aocs.str1.acquisition_progress", progress)

    eq = NativeEquipment(
        equipment_id="str1",
        ports=[
            PortDefinition("aocs.str1.power_enable", PortDirection.IN,
                           description="Power enable (0=off, 1=on)"),
            PortDefinition("aocs.str1.sun_angle", PortDirection.IN,
                           unit="deg",
                           description="Sun angle for blinding detection"),
            PortDefinition("aocs.str1.quaternion_w", PortDirection.OUT,
                           description="Attitude quaternion W"),
            PortDefinition("aocs.str1.quaternion_x", PortDirection.OUT,
                           description="Attitude quaternion X"),
            PortDefinition("aocs.str1.quaternion_y", PortDirection.OUT,
                           description="Attitude quaternion Y"),
            PortDefinition("aocs.str1.quaternion_z", PortDirection.OUT,
                           description="Attitude quaternion Z"),
            PortDefinition("aocs.str1.validity", PortDirection.OUT,
                           description="Measurement validity (0=invalid, 1=valid)"),
            PortDefinition("aocs.str1.mode", PortDirection.OUT,
                           description="ST mode (0=off, 1=acquiring, 2=tracking)"),
            PortDefinition("aocs.str1.temperature", PortDirection.OUT,
                           unit="degC",
                           description="Detector temperature"),
            PortDefinition("aocs.str1.acquisition_progress", PortDirection.OUT,
                           description="Acquisition progress (0.0-1.0)"),
        ],
        step_fn=_st_step,
        sync_protocol=sync_protocol,
        store=store,
        command_store=command_store,
    )
    eq._port_values["aocs.str1.temperature"] = AMBIENT_TEMP_C
    eq._port_values["aocs.str1.sun_angle"]   = 90.0  # safe default
    return eq
