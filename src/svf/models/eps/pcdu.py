"""
SVF PCDU Equipment
Power Conditioning and Distribution Unit reference model.

Physics:
- Per-LCL switching (8 channels) with current monitoring
- MPPT: simplified efficiency tracking based on illumination
- UVLO: under-voltage lockout disconnects loads below threshold
- Power accounting: solar_power * mppt_efficiency - total_load = charge_current

Implements: PCDU-001, PCDU-002, PCDU-003, PCDU-004
"""

from __future__ import annotations

import logging
from typing import Optional

from svf.abstractions import SyncProtocol
from svf.equipment import PortDefinition, PortDirection
from svf.native_equipment import NativeEquipment
from svf.parameter_store import ParameterStore
from svf.command_store import CommandStore

logger = logging.getLogger(__name__)

# UVLO threshold — disconnect loads below this battery voltage
UVLO_THRESHOLD_V    = 3.1

# Maximum charge current
MAX_CHARGE_CURRENT  = 20.0

# MPPT efficiency model
# Simplified: efficiency peaks at illumination=0.7, degrades at extremes
MPPT_BASE_EFF       = 0.92
MPPT_PEAK_ILL       = 0.7

# Number of LCLs
N_LCLS              = 8

# Nominal load per LCL when enabled (W) — simplified equal distribution
LCL_NOMINAL_LOAD_W  = 5.0


def _mppt_efficiency(illumination: float) -> float:
    """
    Simplified MPPT efficiency curve.
    Peaks at MPPT_PEAK_ILL, degrades towards extremes.
    """
    if illumination <= 0.0:
        return 0.0
    deviation = abs(illumination - MPPT_PEAK_ILL)
    return max(0.0, MPPT_BASE_EFF - 0.15 * deviation)


def make_pcdu(
    sync_protocol: SyncProtocol,
    store: ParameterStore,
    command_store: Optional[CommandStore] = None,
) -> NativeEquipment:
    """Create a PCDU NativeEquipment with 8 LCLs."""

    # LCL state — captured in closure
    lcl_state: dict[str, float] = {
        f"lcl{i}": 1.0 for i in range(1, N_LCLS + 1)  # all on by default
    }

    def _pcdu_step(eq: NativeEquipment, t: float, dt: float) -> None:
        solar_power    = eq.read_port("eps.solar_array.generated_power")
        battery_voltage = eq.read_port("eps.battery.voltage")
        illumination   = eq.read_port("eps.solar_array.illumination")

        # ── LCL switching ─────────────────────────────────────────────
        total_load = 0.0
        for i in range(1, N_LCLS + 1):
            key = f"lcl{i}"
            enable_port = f"eps.pcdu.lcl{i}.enable"
            status_port = f"eps.pcdu.lcl{i}.status"

            cmd = eq.read_port(enable_port)
            if cmd >= 0.0:  # command received
                lcl_state[key] = 1.0 if cmd > 0.5 else 0.0
                eq.receive(enable_port, -1.0)  # consume

            eq.write_port(status_port, lcl_state[key])
            if lcl_state[key] > 0.5:
                total_load += LCL_NOMINAL_LOAD_W

        # ── UVLO ──────────────────────────────────────────────────────
        uvlo_active = 1.0 if battery_voltage < UVLO_THRESHOLD_V else 0.0
        if uvlo_active > 0.5:
            total_load = 0.0  # disconnect all loads
            logger.warning(
                f"[pcdu] UVLO active at t={t:.1f}s "
                f"(Vbat={battery_voltage:.2f}V)"
            )

        # ── MPPT ──────────────────────────────────────────────────────
        mppt_eff = _mppt_efficiency(illumination)
        effective_solar = solar_power * mppt_eff

        # ── Power balance ──────────────────────────────────────────────
        net_power      = effective_solar - total_load
        charge_current = net_power / max(battery_voltage, 0.1)
        charge_current = max(-MAX_CHARGE_CURRENT,
                             min(MAX_CHARGE_CURRENT, charge_current))

        eq.write_port("eps.pcdu.total_load",     total_load)
        eq.write_port("eps.pcdu.charge_current",  charge_current)
        eq.write_port("eps.pcdu.mppt_efficiency", mppt_eff)
        eq.write_port("eps.pcdu.uvlo_active",     uvlo_active)

    # Build port list
    ports = [
        PortDefinition("eps.solar_array.generated_power", PortDirection.IN,
                       unit="W", description="Solar power input"),
        PortDefinition("eps.battery.voltage", PortDirection.IN,
                       unit="V", description="Battery voltage for UVLO"),
        PortDefinition("eps.solar_array.illumination", PortDirection.IN,
                       description="Solar illumination for MPPT"),
        PortDefinition("eps.pcdu.total_load", PortDirection.OUT,
                       unit="W", description="Total load power"),
        PortDefinition("eps.pcdu.charge_current", PortDirection.OUT,
                       unit="A", description="Battery charge current"),
        PortDefinition("eps.pcdu.mppt_efficiency", PortDirection.OUT,
                       description="MPPT efficiency"),
        PortDefinition("eps.pcdu.uvlo_active", PortDirection.OUT,
                       description="UVLO status"),
    ]

    # Add LCL ports
    for i in range(1, N_LCLS + 1):
        ports.append(PortDefinition(
            f"eps.pcdu.lcl{i}.enable", PortDirection.IN,
            description=f"LCL{i} enable command",
        ))
        ports.append(PortDefinition(
            f"eps.pcdu.lcl{i}.status", PortDirection.OUT,
            description=f"LCL{i} status",
        ))

    eq = NativeEquipment(
        equipment_id="pcdu",
        ports=ports,
        step_fn=_pcdu_step,
        sync_protocol=sync_protocol,
        store=store,
        command_store=command_store,
    )

    # Initialise LCL enable ports to -1 (no pending command)
    for i in range(1, N_LCLS + 1):
        eq._port_values[f"eps.pcdu.lcl{i}.enable"] = -1.0

    return eq
