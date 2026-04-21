"""
SVF B-dot Controller
Reference implementation of the b-dot magnetic detumbling algorithm.

B-dot uses the time derivative of the measured magnetic field to
generate magnetorquer dipole commands that oppose the spacecraft
rotation. It is the standard safe mode detumbling algorithm for
small spacecraft.

Control law:
    m_cmd = -k_bdot * B_dot
where:
    B_dot  = (B_measured - B_prev) / dt   (finite difference)
    k_bdot = gain (Am²·s/T)

This is NOT the flight algorithm — that lives in the OBSW.
This is a reference implementation for:
  1. Validating MAG/MTQ model physics before OBSW is available
  2. Level 3 closed-loop testing via ObcStub rules
  3. Regression testing when OBSW b-dot is updated

Reference: Bdot law — Stickler & Alfriend (1976)
Implements: SVF-DEV-038
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from svf.core.abstractions import SyncProtocol
from svf.core.equipment import PortDefinition, PortDirection
from svf.core.native_equipment import NativeEquipment
from svf.stores.parameter_store import ParameterStore
from svf.stores.command_store import CommandStore

logger = logging.getLogger(__name__)

# Default gain (Am²·s/T) — tune for spacecraft inertia
DEFAULT_GAIN = 1e4

# Dipole saturation (Am²)
MAX_DIPOLE   = 10.0


def make_bdot_controller(
    sync_protocol: SyncProtocol,
    store: ParameterStore,
    command_store: Optional[CommandStore] = None,
    gain: float = DEFAULT_GAIN,
) -> NativeEquipment:
    """
    Create a B-dot detumbling controller NativeEquipment.

    Reads MAG measurements, computes B-dot via finite difference,
    outputs MTQ dipole commands.

    Inputs:
        aocs.mag.field_x/y/z   — measured magnetic field (T)
        aocs.bdot.enable        — enable control (0=off, 1=on)

    Outputs:
        aocs.mtq.dipole_x/y/z  — commanded dipole moments (Am²)
        aocs.bdot.bdot_x/y/z   — estimated B-dot (T/s, for telemetry)
        aocs.bdot.active        — 1 when controller is active

    Args:
        gain: B-dot gain k in m_cmd = -k * B_dot (Am²·s/T)
    """
    state: dict[str, Any] = {
        "b_prev_x": 0.0,
        "b_prev_y": 0.0,
        "b_prev_z": 0.0,
        "initialised": False,
    }

    def _bdot_step(eq: NativeEquipment, t: float, dt: float) -> None:
        enabled = eq.read_port("aocs.bdot.enable") > 0.5

        if not enabled:
            eq.write_port("aocs.mtq.dipole_x", 0.0)
            eq.write_port("aocs.mtq.dipole_y", 0.0)
            eq.write_port("aocs.mtq.dipole_z", 0.0)
            eq.write_port("aocs.bdot.bdot_x", 0.0)
            eq.write_port("aocs.bdot.bdot_y", 0.0)
            eq.write_port("aocs.bdot.bdot_z", 0.0)
            eq.write_port("aocs.bdot.active", 0.0)
            state["initialised"] = False
            return

        bx = eq.read_port("aocs.mag.field_x")
        by = eq.read_port("aocs.mag.field_y")
        bz = eq.read_port("aocs.mag.field_z")

        if not state["initialised"]:
            # First tick — no derivative available yet
            state["b_prev_x"] = bx
            state["b_prev_y"] = by
            state["b_prev_z"] = bz
            state["initialised"] = True
            eq.write_port("aocs.mtq.dipole_x", 0.0)
            eq.write_port("aocs.mtq.dipole_y", 0.0)
            eq.write_port("aocs.mtq.dipole_z", 0.0)
            eq.write_port("aocs.bdot.bdot_x", 0.0)
            eq.write_port("aocs.bdot.bdot_y", 0.0)
            eq.write_port("aocs.bdot.bdot_z", 0.0)
            eq.write_port("aocs.bdot.active", 1.0)
            return

        # Finite difference B-dot
        if dt > 0:
            bdot_x = (bx - state["b_prev_x"]) / dt
            bdot_y = (by - state["b_prev_y"]) / dt
            bdot_z = (bz - state["b_prev_z"]) / dt
        else:
            bdot_x = bdot_y = bdot_z = 0.0

        # Control law: m = -k * B_dot
        mx = max(-MAX_DIPOLE, min(MAX_DIPOLE, -gain * bdot_x))
        my = max(-MAX_DIPOLE, min(MAX_DIPOLE, -gain * bdot_y))
        mz = max(-MAX_DIPOLE, min(MAX_DIPOLE, -gain * bdot_z))

        eq.write_port("aocs.mtq.dipole_x", mx)
        eq.write_port("aocs.mtq.dipole_y", my)
        eq.write_port("aocs.mtq.dipole_z", mz)
        eq.write_port("aocs.bdot.bdot_x", bdot_x)
        eq.write_port("aocs.bdot.bdot_y", bdot_y)
        eq.write_port("aocs.bdot.bdot_z", bdot_z)
        eq.write_port("aocs.bdot.active", 1.0)

        state["b_prev_x"] = bx
        state["b_prev_y"] = by
        state["b_prev_z"] = bz

        logger.debug(
            f"[bdot] t={t:.1f} B=({bx:.2e},{by:.2e},{bz:.2e}) "
            f"Bdot=({bdot_x:.2e},{bdot_y:.2e},{bdot_z:.2e}) "
            f"m=({mx:.2f},{my:.2f},{mz:.2f})"
        )

    return NativeEquipment(
        equipment_id="bdot",
        ports=[
            PortDefinition("aocs.bdot.enable", PortDirection.IN,
                           description="Enable b-dot control (0=off, 1=on)"),
            PortDefinition("aocs.mag.field_x", PortDirection.IN,
                           unit="T", description="MAG field X"),
            PortDefinition("aocs.mag.field_y", PortDirection.IN,
                           unit="T", description="MAG field Y"),
            PortDefinition("aocs.mag.field_z", PortDirection.IN,
                           unit="T", description="MAG field Z"),
            PortDefinition("aocs.mtq.dipole_x", PortDirection.OUT,
                           unit="Am2", description="MTQ dipole X command"),
            PortDefinition("aocs.mtq.dipole_y", PortDirection.OUT,
                           unit="Am2", description="MTQ dipole Y command"),
            PortDefinition("aocs.mtq.dipole_z", PortDirection.OUT,
                           unit="Am2", description="MTQ dipole Z command"),
            PortDefinition("aocs.bdot.bdot_x", PortDirection.OUT,
                           unit="T/s", description="Estimated B-dot X"),
            PortDefinition("aocs.bdot.bdot_y", PortDirection.OUT,
                           unit="T/s", description="Estimated B-dot Y"),
            PortDefinition("aocs.bdot.bdot_z", PortDirection.OUT,
                           unit="T/s", description="Estimated B-dot Z"),
            PortDefinition("aocs.bdot.active", PortDirection.OUT,
                           description="Controller active flag"),
        ],
        step_fn=_bdot_step,
        sync_protocol=sync_protocol,
        store=store,
        command_store=command_store,
    )
