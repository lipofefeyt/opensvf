"""
SVF OBC Equipment
Simple On-Board Computer model acting as MIL-STD-1553 Bus Controller.
Forwards telecommands to RTs and monitors for bus faults.
Implements FDIR: detects RT timeout and flags fault.
Implements: SVF-DEV-038
"""

from __future__ import annotations

import logging
from typing import Optional

from svf.abstractions import SyncProtocol
from svf.equipment import PortDefinition, PortDirection, InterfaceType
from svf.native_equipment import NativeEquipment
from svf.parameter_store import ParameterStore
from svf.command_store import CommandStore

logger = logging.getLogger(__name__)


def _obc_step(eq: NativeEquipment, t: float, dt: float) -> None:
    """
    OBC step function.
    Forwards commands to RT via bc_out port.
    Monitors RT telemetry for FDIR.
    """
    # Forward any pending torque command to bus output
    torque = eq.read_port("rw1_torque_cmd_in")
    eq.write_port("rw1_torque_cmd_out", torque)

    # Read RW speed telemetry from bus
    speed = eq.read_port("rw1_speed_in")
    eq.write_port("rw1_speed_monitor", speed)

    # FDIR: detect missing telemetry (speed stays at 0 after commanding)
    # Simple heuristic — flag fault if speed is 0 while torque commanded
    if abs(torque) > 0.01 and abs(speed) < 0.1 and t > 2.0:
        eq.write_port("fdir.rw1_fault", 1.0)
        logger.warning(f"[obc] FDIR: RW1 not responding at t={t:.1f}s")
    else:
        eq.write_port("fdir.rw1_fault", 0.0)


def make_obc(
    sync_protocol: SyncProtocol,
    store: ParameterStore,
    command_store: Optional[CommandStore] = None,
) -> NativeEquipment:
    """
    Create an OBC NativeEquipment acting as 1553 Bus Controller.
    """
    return NativeEquipment(
        equipment_id="obc",
        ports=[
            # Commands coming in from test procedure
            PortDefinition("rw1_torque_cmd_in", PortDirection.IN,
                           unit="Nm",
                           description="Torque command for RW1 from test procedure"),

            # Commands going out to 1553 bus
            PortDefinition("rw1_torque_cmd_out", PortDirection.OUT,
                           unit="Nm",
                           description="Torque command forwarded to 1553 bus"),

            # Telemetry coming back from 1553 bus
            PortDefinition("rw1_speed_in", PortDirection.IN,
                           unit="rpm",
                           description="RW1 speed telemetry from 1553 bus"),

            # Monitored telemetry written to ParameterStore
            PortDefinition("rw1_speed_monitor", PortDirection.OUT,
                           unit="rpm",
                           description="RW1 speed as seen by OBC"),

            # FDIR output
            PortDefinition("fdir.rw1_fault", PortDirection.OUT,
                           description="FDIR: RW1 fault flag (0=nominal, 1=fault)"),
        ],
        step_fn=_obc_step,
        sync_protocol=sync_protocol,
        store=store,
        command_store=command_store,
    )
