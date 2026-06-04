"""
SVF Gyroscope Equipment — F3 fidelity
Measures angular rate in body frame.
Used for attitude rate estimation and b-dot control.

Physics (F3):
- Angle random walk (ARW) — white noise on rate
- Bias instability — first-order Gauss-Markov flicker floor
- Rate random walk — integrated white noise on bias
- Scale factor error — per-axis gain offset (PPM)
- Cross-axis coupling — misalignment between sense axes
- Temperature-dependent noise and warm-up model

Implements: SVF-DEV-038
"""

from __future__ import annotations

import logging
import math
import random
from typing import Any, Optional

from svf.core.abstractions import SyncProtocol
from svf.core.equipment import PortDefinition, PortDirection
from svf.core.native_equipment import NativeEquipment
from svf.stores.parameter_store import ParameterStore
from svf.stores.command_store import CommandStore

logger = logging.getLogger(__name__)


def make_gyroscope(
    sync_protocol: SyncProtocol,
    store: ParameterStore,
    command_store: Optional[CommandStore] = None,
    equipment_id: str = "gyro",
    seed: Optional[int] = None,
    hardware_profile: Optional[str] = None,
    hardware_dir: Optional[str] = None,
) -> NativeEquipment:
    """
    Create a Gyroscope NativeEquipment.

    Args:
        equipment_id:     Instance name (e.g. 'gyro', 'gyro2'). Port names use
                          the form 'aocs.<equipment_id>.<signal>'.
                          Truth rate ports (aocs.truth.rate_*) are shared and
                          not prefixed.
        hardware_profile: Profile name to override built-in defaults.
        hardware_dir:     Directory to search for profile YAML files.

    Inputs:
        aocs.<id>.power_enable — power on/off
        aocs.truth.rate_x/y/z  — true angular rates (shared, from dynamics)

    Outputs:
        aocs.<id>.rate_x/y/z   — measured rates with noise + bias
        aocs.<id>.temperature  — gyro temperature
        aocs.<id>.status       — 0=off, 1=nominal
    """
    # F3 noise parameters
    arw_std          = 1e-4   # angle random walk [rad/s/√Hz]
    rrw_std          = 1e-5   # rate random walk [rad/s²/√Hz] (bias random walk)
    bi_std           = 5e-6   # bias instability RMS [rad/s]
    tau_corr_s       = 3600.0 # Gauss-Markov correlation time [s]
    temp_noise_coeff = 1e-5   # additional noise per degC above nominal

    # Scale factor errors [dimensionless, applied as (1 + sf) multiplier]
    sf_x = 100e-6
    sf_y = 100e-6
    sf_z = 100e-6

    # Cross-axis coupling [rad — misalignment between sense axes]
    cxy = 1e-3   # Y-axis leakage into X measurement
    cxz = 5e-4
    cyx = 1e-3
    cyz = 5e-4
    czx = 5e-4
    czy = 1e-3

    # Thermal model
    ambient_temp_c   = 20.0
    nominal_temp_c   = 35.0
    temp_rise_rate   = 0.05
    cooling_rate     = 0.03

    if hardware_profile is not None:
        from svf.config.hardware_profile import load_hardware_profile
        p = load_hardware_profile(hardware_profile, hardware_dir)
        arw_std          = p.get("arw_rad_s_sqrthz",        arw_std)
        rrw_std          = p.get("rrw_rad_s2_sqrthz",       rrw_std)
        bi_std           = p.get("bias_instability_rad_s",  bi_std)
        tau_corr_s       = p.get("bias_corr_time_s",        tau_corr_s)
        temp_noise_coeff = p.get("temp_noise_coeff",        temp_noise_coeff)
        sf_x             = p.get("scale_factor_error_x",    sf_x)
        sf_y             = p.get("scale_factor_error_y",    sf_y)
        sf_z             = p.get("scale_factor_error_z",    sf_z)
        cxy              = p.get("misalign_xy_rad",         cxy)
        cxz              = p.get("misalign_xz_rad",         cxz)
        cyx              = p.get("misalign_yx_rad",         cyx)
        cyz              = p.get("misalign_yz_rad",         cyz)
        czx              = p.get("misalign_zx_rad",         czx)
        czy              = p.get("misalign_zy_rad",         czy)
        ambient_temp_c   = p.get("temp_ambient_degc",       ambient_temp_c)
        nominal_temp_c   = p.get("temp_nominal_degc",       nominal_temp_c)
        temp_rise_rate   = p.get("temp_rise_rate",          temp_rise_rate)
        cooling_rate     = p.get("cooling_rate",            cooling_rate)

    rng  = random.Random(seed)
    _pfx = f"aocs.{equipment_id}"

    state: dict[str, Any] = {
        # Rate random walk bias (integrated white noise)
        "rrw_x": 0.0,
        "rrw_y": 0.0,
        "rrw_z": 0.0,
        # Gauss-Markov bias instability (flicker floor)
        "gm_x": 0.0,
        "gm_y": 0.0,
        "gm_z": 0.0,
        "temperature": ambient_temp_c,
        "powered": False,
    }

    def _gyro_step(eq: NativeEquipment, t: float, dt: float) -> None:
        powered = eq.read_port(f"{_pfx}.power_enable") > 0.5

        if not powered:
            state["powered"]     = False
            state["temperature"] = max(
                ambient_temp_c,
                state["temperature"] - cooling_rate * dt,
            )
            eq.write_port(f"{_pfx}.rate_x",      0.0)
            eq.write_port(f"{_pfx}.rate_y",      0.0)
            eq.write_port(f"{_pfx}.rate_z",      0.0)
            eq.write_port(f"{_pfx}.temperature", state["temperature"])
            eq.write_port(f"{_pfx}.status",      0.0)
            return

        state["powered"]      = True
        state["temperature"] += temp_rise_rate * (
            nominal_temp_c - state["temperature"]
        ) * dt

        sqrt_dt = math.sqrt(dt)

        # Rate random walk: integrated white noise on bias
        state["rrw_x"] += rng.gauss(0, rrw_std * sqrt_dt)
        state["rrw_y"] += rng.gauss(0, rrw_std * sqrt_dt)
        state["rrw_z"] += rng.gauss(0, rrw_std * sqrt_dt)

        # Gauss-Markov bias instability (first-order, discrete)
        alpha    = math.exp(-dt / tau_corr_s) if tau_corr_s > 0 else 0.0
        sigma_gm = bi_std * math.sqrt(1.0 - alpha * alpha)
        state["gm_x"] = alpha * state["gm_x"] + rng.gauss(0, sigma_gm)
        state["gm_y"] = alpha * state["gm_y"] + rng.gauss(0, sigma_gm)
        state["gm_z"] = alpha * state["gm_z"] + rng.gauss(0, sigma_gm)

        # Total bias: RRW + Gauss-Markov
        bx = state["rrw_x"] + state["gm_x"]
        by = state["rrw_y"] + state["gm_y"]
        bz = state["rrw_z"] + state["gm_z"]

        # ARW (white noise on angle — PSD = arw_std²)
        noise_std = arw_std / sqrt_dt + temp_noise_coeff * max(
            0.0, state["temperature"] - nominal_temp_c
        )

        wx = eq.read_port("aocs.truth.rate_x")
        wy = eq.read_port("aocs.truth.rate_y")
        wz = eq.read_port("aocs.truth.rate_z")

        # Scale factor + cross-axis coupling + ARW noise + bias
        mx = (1.0 + sf_x) * wx + cxy * wy + cxz * wz + rng.gauss(0, noise_std) + bx
        my = cyx * wx + (1.0 + sf_y) * wy + cyz * wz + rng.gauss(0, noise_std) + by
        mz = czx * wx + czy * wy + (1.0 + sf_z) * wz + rng.gauss(0, noise_std) + bz

        eq.write_port(f"{_pfx}.rate_x",      mx)
        eq.write_port(f"{_pfx}.rate_y",      my)
        eq.write_port(f"{_pfx}.rate_z",      mz)
        eq.write_port(f"{_pfx}.temperature", state["temperature"])
        eq.write_port(f"{_pfx}.status",      1.0)

    eq = NativeEquipment(
        equipment_id=equipment_id,
        ports=[
            PortDefinition(f"{_pfx}.power_enable", PortDirection.IN,
                           description="Power enable"),
            PortDefinition("aocs.truth.rate_x", PortDirection.IN,
                           unit="rad/s", description="True rate X"),
            PortDefinition("aocs.truth.rate_y", PortDirection.IN,
                           unit="rad/s", description="True rate Y"),
            PortDefinition("aocs.truth.rate_z", PortDirection.IN,
                           unit="rad/s", description="True rate Z"),
            PortDefinition(f"{_pfx}.rate_x", PortDirection.OUT,
                           unit="rad/s", description="Measured rate X"),
            PortDefinition(f"{_pfx}.rate_y", PortDirection.OUT,
                           unit="rad/s", description="Measured rate Y"),
            PortDefinition(f"{_pfx}.rate_z", PortDirection.OUT,
                           unit="rad/s", description="Measured rate Z"),
            PortDefinition(f"{_pfx}.temperature", PortDirection.OUT,
                           unit="degC", description="Gyro temperature"),
            PortDefinition(f"{_pfx}.status", PortDirection.OUT,
                           description="Status (0=off, 1=nominal)"),
        ],
        step_fn=_gyro_step,
        sync_protocol=sync_protocol,
        store=store,
        command_store=command_store,
    )
    eq._port_values[f"{_pfx}.power_enable"] = 0.0
    return eq
