"""
SVF Battery Equipment
Li-Ion spacecraft battery model.

Physics:
- Piecewise non-linear SoC/voltage curve (18650 Li-Ion approximation)
- SoC updated from charge/discharge current each timestep
- SOC_MIN clamp prevents deep discharge (protection cutoff)
- Separate charge and discharge efficiency via PCDU

Voltage curve:
  SoC 0.0 → 0.1 : steep rise  3.0 V → 3.5 V
  SoC 0.1 → 0.9 : flat plateau 3.5 V → 4.0 V
  SoC 0.9 → 1.0 : steep rise  4.0 V → 4.2 V

Implements: EPS-004, EPS-005, EPS-006, EPS-007
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

CAPACITY_WH: float = 20.0
SOC_MIN: float = 0.05
SOC_MAX: float = 1.0
INITIAL_SOC: float = 0.8


def _soc_to_voltage(soc: float) -> float:
    if soc <= 0.1:
        return 3.0 + 5.0 * soc
    elif soc <= 0.9:
        return 3.5 + 0.625 * (soc - 0.1)
    else:
        return 4.0 + 2.0 * (soc - 0.9)


def make_battery(
    sync_protocol: SyncProtocol,
    store: ParameterStore,
    command_store: Optional[CommandStore] = None,
    equipment_id: str = "battery",
    initial_soc: float = INITIAL_SOC,
    capacity_wh: float = CAPACITY_WH,
) -> NativeEquipment:
    """
    Create a Battery NativeEquipment.

    Inputs:
        eps.battery.charge_current  -  charge current in Amps (positive=charging)

    Outputs:
        eps.battery.soc      -  state of charge (0.0 to 1.0)
        eps.battery.voltage  -  terminal voltage in Volts
    """
    state = {"soc": max(SOC_MIN, min(SOC_MAX, initial_soc))}

    def _step(eq: NativeEquipment, t: float, dt: float) -> None:
        charge_current = eq.read_port("eps.battery.charge_current")
        voltage = _soc_to_voltage(state["soc"])

        delta_wh = charge_current * voltage * dt / 3600.0
        state["soc"] = max(SOC_MIN, min(SOC_MAX,
                           state["soc"] + delta_wh / capacity_wh))

        eq.write_port("eps.battery.soc",     state["soc"])
        eq.write_port("eps.battery.voltage", _soc_to_voltage(state["soc"]))

    eq = NativeEquipment(
        equipment_id=equipment_id,
        ports=[
            PortDefinition("eps.battery.charge_current", PortDirection.IN,
                           unit="A", description="Charge current (positive=charging)"),
            PortDefinition("eps.battery.soc", PortDirection.OUT,
                           description="State of charge (0–1)"),
            PortDefinition("eps.battery.voltage", PortDirection.OUT,
                           unit="V", description="Terminal voltage"),
        ],
        step_fn=_step,
        sync_protocol=sync_protocol,
        store=store,
        command_store=command_store,
    )
    eq._port_values["eps.battery.soc"]     = initial_soc
    eq._port_values["eps.battery.voltage"] = _soc_to_voltage(initial_soc)
    return eq
