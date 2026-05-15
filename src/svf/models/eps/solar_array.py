"""
SVF Solar Array Equipment
Illumination-driven power generation model.

Physics:
- Generated power proportional to solar illumination fraction
- Panel efficiency accounts for solar cell and harness losses
- Zero output during eclipse (illumination = 0)

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

MAX_POWER_W: float = 100.0
PANEL_EFFICIENCY: float = 0.90


def make_solar_array(
    sync_protocol: SyncProtocol,
    store: ParameterStore,
    command_store: Optional[CommandStore] = None,
    equipment_id: str = "solar_array",
    max_power_w: float = MAX_POWER_W,
    panel_efficiency: float = PANEL_EFFICIENCY,
) -> NativeEquipment:
    """
    Create a Solar Array NativeEquipment.

    Inputs:
        eps.solar_array.illumination  — solar illumination (0=eclipse, 1=full sun)

    Outputs:
        eps.solar_array.generated_power — generated power in Watts
    """

    def _step(eq: NativeEquipment, t: float, dt: float) -> None:
        illumination = max(0.0, min(1.0, eq.read_port("eps.solar_array.illumination")))
        generated = illumination * max_power_w * panel_efficiency
        eq.write_port("eps.solar_array.generated_power", generated)

    eq = NativeEquipment(
        equipment_id=equipment_id,
        ports=[
            PortDefinition("eps.solar_array.illumination", PortDirection.IN,
                           description="Solar illumination (0=eclipse, 1=full sun)"),
            PortDefinition("eps.solar_array.generated_power", PortDirection.OUT,
                           unit="W", description="Generated power"),
        ],
        step_fn=_step,
        sync_protocol=sync_protocol,
        store=store,
        command_store=command_store,
    )
    eq._port_values["eps.solar_array.illumination"] = 1.0
    return eq
