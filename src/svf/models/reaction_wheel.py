"""
SVF Reaction Wheel Equipment
Simple reaction wheel model acting as MIL-STD-1553 Remote Terminal.
Receives torque commands via 1553 bus, produces speed telemetry.
No OBC model required — test procedures inject commands directly
via the 1553 bus subaddress mapping.
Implements: SVF-DEV-038
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

MAX_SPEED_RPM = 6000.0
FRICTION_COEFF = 0.05


def _rw_step(eq: NativeEquipment, t: float, dt: float) -> None:
    """
    Reaction wheel physics.
    Integrates torque command to produce speed.
    """
    torque = eq.read_port("aocs.rw1.torque_cmd")
    speed = eq.read_port("aocs.rw1.speed")

    acceleration = torque * 100.0
    friction = -FRICTION_COEFF * speed
    new_speed = speed + (acceleration + friction) * dt
    new_speed = max(-MAX_SPEED_RPM, min(MAX_SPEED_RPM, new_speed))

    eq.write_port("aocs.rw1.speed", new_speed)
    eq.write_port("aocs.rw1.status", 1.0)


def make_reaction_wheel(
    sync_protocol: SyncProtocol,
    store: ParameterStore,
    command_store: Optional[CommandStore] = None,
) -> NativeEquipment:
    """
    Create a ReactionWheel NativeEquipment as 1553 Remote Terminal.
    Torque commands arrive via 1553 bus subaddress mapping.
    Speed telemetry is read back by the bus RT_to_BC mapping.
    """
    return NativeEquipment(
        equipment_id="rw1",
        ports=[
            PortDefinition("aocs.rw1.torque_cmd", PortDirection.IN,
                           unit="Nm",
                           description="Torque command from 1553 bus SA1"),
            PortDefinition("aocs.rw1.speed", PortDirection.OUT,
                           unit="rpm",
                           description="Wheel speed telemetry to 1553 bus SA2"),
            PortDefinition("aocs.rw1.status", PortDirection.OUT,
                           description="Equipment status (1=nominal)"),
        ],
        step_fn=_rw_step,
        sync_protocol=sync_protocol,
        store=store,
        command_store=command_store,
    )
