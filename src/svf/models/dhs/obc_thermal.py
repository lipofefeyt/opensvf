"""
SVF OBC Thermal Input Model

The simulator-owned OBC temperature that OBCEmulatorAdapter sends to
openobsw in the wire protocol v4 sensor frame (``obc_temperature_raw`` and
``thermal_valid``). openobsw writes a valid reading into its S20 parameter
``obc_temperature`` (0x0001) before S12 monitoring and housekeeping, so a
procedure can raise and clear a thermal anomaly in any OBSW mode, without a
TC, through the equipment fault engine::

    ctx.inject_equipment_fault("obc_thermal", "dhs.obc_thermal.temperature_raw",
                               "stuck", 1300.0)
    ctx.clear_equipment_faults("obc_thermal")

The value is what the simulator applied, in openobsw SRDB raw counts
(degC = 0.1 * raw - 40). What the flight software reported back is a
different parameter, ``dhs.obc.obc_temperature`` from HK set 1.

Fidelity F1: a constant nominal value, no thermal physics.

Ports:
  OUT: dhs.obc_thermal.temperature_raw  -  raw counts sent to the OBSW
       dhs.obc_thermal.status           -  1 = valid, 0 = invalid (OBSW keeps
                                           its last obc_temperature)

Implements: SVF-DEV-219
"""
from __future__ import annotations

from typing import Optional

from svf.core.abstractions import SyncProtocol
from svf.core.equipment import PortDefinition, PortDirection
from svf.core.native_equipment import NativeEquipment
from svf.stores.command_store import CommandStore
from svf.stores.parameter_store import ParameterStore

TEMPERATURE_RAW_PORT = "dhs.obc_thermal.temperature_raw"
STATUS_PORT = "dhs.obc_thermal.status"

# openobsw srdb/data/parameters.yaml obc_temperature: int16, degC = 0.1 * raw - 40.
NOMINAL_RAW = 650.0    # 25 degC


def raw_to_degc(raw: float) -> float:
    """openobsw obc_temperature raw counts to degC."""
    return 0.1 * raw - 40.0


def degc_to_raw(degc: float) -> float:
    """degC to openobsw obc_temperature raw counts."""
    return (degc + 40.0) * 10.0


def make_obc_thermal(
    sync_protocol: SyncProtocol,
    store: ParameterStore,
    command_store: Optional[CommandStore] = None,
    equipment_id: str = "obc_thermal",
    nominal_raw: float = NOMINAL_RAW,
) -> NativeEquipment:
    """
    Create the OBC thermal input equipment.

    Args:
        equipment_id: Instance name, the target of ``inject_equipment_fault``.
        nominal_raw:  Value written every tick, in raw counts.
    """
    def _step(eq: NativeEquipment, t: float, dt: float) -> None:
        eq.write_port(TEMPERATURE_RAW_PORT, nominal_raw)
        eq.write_port(STATUS_PORT, 1.0)

    eq = NativeEquipment(
        equipment_id=equipment_id,
        ports=[
            PortDefinition(TEMPERATURE_RAW_PORT, PortDirection.OUT,
                           description="OBC temperature sent to the OBSW "
                                       "(raw, degC = 0.1 * raw - 40)"),
            PortDefinition(STATUS_PORT, PortDirection.OUT,
                           description="OBC thermal input validity (1=valid)"),
        ],
        step_fn=_step,
        sync_protocol=sync_protocol,
        store=store,
        command_store=command_store,
    )
    eq._port_values[TEMPERATURE_RAW_PORT] = nominal_raw
    eq._port_values[STATUS_PORT] = 1.0
    return eq
