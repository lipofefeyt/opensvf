"""
SVF Solar Array Equipment  -  F3 fidelity
Nonlinear I-V curve model with temperature derating.

Physics (F3):
- Single-diode simplified model: P = Isc * Voc * FF * illumination
- Short-circuit current Isc scales linearly with illumination and temperature
  (positive temp coefficient alpha_isc)
- Open-circuit voltage Voc decreases with temperature
  (negative temp coefficient beta_voc)
- Fill factor FF captures nonlinearity of I-V curve near MPP
- MPPT assumed: operating point always at maximum power

Implements: EPS-001, EPS-002, EPS-003
"""
from __future__ import annotations

import logging
from typing import Optional

from svf.core.abstractions import SyncProtocol
from svf.core.equipment import PortDefinition, PortDirection
from svf.core.native_equipment import NativeEquipment
from svf.stores.parameter_store import ParameterStore
from svf.stores.command_store import CommandStore

logger = logging.getLogger(__name__)

# Legacy exports kept for backward compatibility
MAX_POWER_W: float = 100.0
PANEL_EFFICIENCY: float = 0.90

# Derived STC parameters  -  at illumination=1, temp=T_ref: P = MAX_POWER_W * PANEL_EFFICIENCY
_P_STC       = MAX_POWER_W * PANEL_EFFICIENCY   # 90 W
_FILL_FACTOR = 0.78
_VOC_NOM     = 24.0                             # open-circuit voltage [V]
_ISC_NOM     = _P_STC / (_FILL_FACTOR * _VOC_NOM)  # ≈ 4.81 A
_TEMP_REF_C  = 28.0     # STC cell temperature [°C]
_ALPHA_ISC   = 3.5e-4   # Isc temp coefficient [1/°C]  (positive)
_BETA_VOC    = -6.5e-3  # Voc temp coefficient [V/°C]  (negative)


def make_solar_array(
    sync_protocol: SyncProtocol,
    store: ParameterStore,
    command_store: Optional[CommandStore] = None,
    equipment_id: str = "solar_array",
    hardware_profile: Optional[str] = None,
    hardware_dir: Optional[str] = None,
    # Legacy flat params  -  override voc/isc via profile instead
    max_power_w: float = MAX_POWER_W,
    panel_efficiency: float = PANEL_EFFICIENCY,
) -> NativeEquipment:
    """
    Create a Solar Array NativeEquipment.

    Inputs:
        eps.solar_array.illumination       -  solar illumination fraction (0=eclipse, 1=full sun)
        eps.solar_array.panel_temp_degc    -  panel temperature in °C (from thermal model)

    Outputs:
        eps.solar_array.generated_power    -  generated power [W]
        eps.solar_array.generated_current  -  output current at MPP [A]
        eps.solar_array.generated_voltage  -  MPP voltage [V]
        eps.solar_array.efficiency         -  instantaneous efficiency relative to STC
    """
    # Derive STC max from legacy params if caller passed them explicitly
    p_stc       = max_power_w * panel_efficiency
    fill_factor = _FILL_FACTOR
    voc_nom     = _VOC_NOM
    isc_nom     = p_stc / (fill_factor * voc_nom)
    temp_ref_c  = _TEMP_REF_C
    alpha_isc   = _ALPHA_ISC
    beta_voc    = _BETA_VOC

    if hardware_profile is not None:
        from svf.config.hardware_profile import load_hardware_profile
        p = load_hardware_profile(hardware_profile, hardware_dir)
        voc_nom     = p.get("voc_nom_v",          voc_nom)
        isc_nom     = p.get("isc_nom_a",          isc_nom)
        fill_factor = p.get("fill_factor",         fill_factor)
        temp_ref_c  = p.get("temp_ref_degc",       temp_ref_c)
        alpha_isc   = p.get("alpha_isc_per_degc",  alpha_isc)
        beta_voc    = p.get("beta_voc_v_per_degc", beta_voc)

    stc_max = isc_nom * voc_nom * fill_factor   # power at STC, full sun
    _pfx    = f"eps.{equipment_id}"

    def _step(eq: NativeEquipment, _t: float, _dt: float) -> None:
        illumination = max(0.0, min(1.0, eq.read_port(f"{_pfx}.illumination")))
        temp_c       = eq.read_port(f"{_pfx}.panel_temp_degc")
        delta_t      = temp_c - temp_ref_c

        # Temperature-derated I-V parameters
        isc = isc_nom * illumination * (1.0 + alpha_isc * delta_t)
        voc = voc_nom + beta_voc * delta_t

        if isc <= 0.0 or voc <= 0.0:
            eq.write_port(f"{_pfx}.generated_power",   0.0)
            eq.write_port(f"{_pfx}.generated_current", 0.0)
            eq.write_port(f"{_pfx}.generated_voltage", 0.0)
            eq.write_port(f"{_pfx}.efficiency",        0.0)
            return

        # MPPT assumed  -  operating at maximum power point
        p_max = isc * voc * fill_factor
        # Approximate MPP voltage from fill factor
        v_mpp = voc * (1.0 - (1.0 - fill_factor) ** 0.5)
        i_mpp = p_max / v_mpp if v_mpp > 0.0 else 0.0

        efficiency = p_max / stc_max if stc_max > 0.0 else 0.0

        eq.write_port(f"{_pfx}.generated_power",   p_max)
        eq.write_port(f"{_pfx}.generated_current", i_mpp)
        eq.write_port(f"{_pfx}.generated_voltage", v_mpp)
        eq.write_port(f"{_pfx}.efficiency",        efficiency)

    eq = NativeEquipment(
        equipment_id=equipment_id,
        ports=[
            PortDefinition(f"{_pfx}.illumination", PortDirection.IN,
                           description="Solar illumination (0=eclipse, 1=full sun)"),
            PortDefinition(f"{_pfx}.panel_temp_degc", PortDirection.IN,
                           unit="degC", description="Panel temperature"),
            PortDefinition(f"{_pfx}.generated_power", PortDirection.OUT,
                           unit="W", description="Generated power at MPP"),
            PortDefinition(f"{_pfx}.generated_current", PortDirection.OUT,
                           unit="A", description="MPP current"),
            PortDefinition(f"{_pfx}.generated_voltage", PortDirection.OUT,
                           unit="V", description="MPP voltage"),
            PortDefinition(f"{_pfx}.efficiency", PortDirection.OUT,
                           description="Array efficiency relative to STC"),
        ],
        step_fn=_step,
        sync_protocol=sync_protocol,
        store=store,
        command_store=command_store,
    )
    eq._port_values[f"{_pfx}.illumination"]    = 1.0
    eq._port_values[f"{_pfx}.panel_temp_degc"] = temp_ref_c
    return eq
