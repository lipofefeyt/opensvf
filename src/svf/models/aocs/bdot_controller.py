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

_DEFAULT_GAIN      = 1e4   # Am²·s/T
_DEFAULT_MAX_DIPOLE = 10.0  # Am²


def make_bdot_controller(
    sync_protocol: SyncProtocol,
    store: ParameterStore,
    command_store: Optional[CommandStore] = None,
    equipment_id: str = "bdot",
    gain: float = _DEFAULT_GAIN,
    max_dipole: float = _DEFAULT_MAX_DIPOLE,
    mag_id: str = "mag",
    mtq_id: str = "mtq",
) -> NativeEquipment:
    """
    Create a B-dot detumbling controller NativeEquipment.

    Reads MAG measurements, computes B-dot via finite difference,
    outputs MTQ dipole commands.

    Args:
        equipment_id: Instance name for this controller's own ports
                      (aocs.<id>.enable, aocs.<id>.bdot_*, aocs.<id>.active).
        gain:         B-dot gain k in m_cmd = -k * B_dot (Am²·s/T).
        max_dipole:   Dipole saturation limit (Am²).
        mag_id:       equipment_id of the magnetometer to read from.
                      Reads aocs.<mag_id>.field_x/y/z.
        mtq_id:       equipment_id of the magnetorquer to command.
                      Writes aocs.<mtq_id>.dipole_x/y/z.

    Inputs:
        aocs.<id>.enable          — enable control (0=off, 1=on)
        aocs.<mag_id>.field_x/y/z — measured magnetic field (T)

    Outputs:
        aocs.<mtq_id>.dipole_x/y/z — commanded dipole moments (Am²)
        aocs.<id>.bdot_x/y/z       — estimated B-dot (T/s, for telemetry)
        aocs.<id>.active           — 1 when controller is active
    """
    _pfx     = f"aocs.{equipment_id}"
    _mag_pfx = f"aocs.{mag_id}"
    _mtq_pfx = f"aocs.{mtq_id}"

    # Write construction-time defaults so TC(20,3) get returns a value
    if store.read("aocs.ctrl.bdot_gain") is None:
        store.write("aocs.ctrl.bdot_gain", gain, t=0.0, model_id=equipment_id)
    if store.read("aocs.ctrl.bdot_max_dipole") is None:
        store.write("aocs.ctrl.bdot_max_dipole", max_dipole, t=0.0, model_id=equipment_id)

    state: dict[str, Any] = {
        "b_prev_x":    0.0,
        "b_prev_y":    0.0,
        "b_prev_z":    0.0,
        "initialised": False,
    }

    def _bdot_step(eq: NativeEquipment, t: float, dt: float) -> None:
        enabled = eq.read_port(f"{_pfx}.enable") > 0.5

        if not enabled:
            eq.write_port(f"{_mtq_pfx}.dipole_x", 0.0)
            eq.write_port(f"{_mtq_pfx}.dipole_y", 0.0)
            eq.write_port(f"{_mtq_pfx}.dipole_z", 0.0)
            eq.write_port(f"{_pfx}.bdot_x",  0.0)
            eq.write_port(f"{_pfx}.bdot_y",  0.0)
            eq.write_port(f"{_pfx}.bdot_z",  0.0)
            eq.write_port(f"{_pfx}.active",  0.0)
            state["initialised"] = False
            return

        bx = eq.read_port(f"{_mag_pfx}.field_x")
        by = eq.read_port(f"{_mag_pfx}.field_y")
        bz = eq.read_port(f"{_mag_pfx}.field_z")

        if not state["initialised"]:
            state["b_prev_x"]    = bx
            state["b_prev_y"]    = by
            state["b_prev_z"]    = bz
            state["initialised"] = True
            eq.write_port(f"{_mtq_pfx}.dipole_x", 0.0)
            eq.write_port(f"{_mtq_pfx}.dipole_y", 0.0)
            eq.write_port(f"{_mtq_pfx}.dipole_z", 0.0)
            eq.write_port(f"{_pfx}.bdot_x", 0.0)
            eq.write_port(f"{_pfx}.bdot_y", 0.0)
            eq.write_port(f"{_pfx}.bdot_z", 0.0)
            eq.write_port(f"{_pfx}.active", 1.0)
            return

        if dt > 0:
            bdot_x = (bx - state["b_prev_x"]) / dt
            bdot_y = (by - state["b_prev_y"]) / dt
            bdot_z = (bz - state["b_prev_z"]) / dt
        else:
            bdot_x = bdot_y = bdot_z = 0.0

        # Read live gains — updated via TC(20,1) S20 set
        _gain_e = store.read("aocs.ctrl.bdot_gain")
        _gain = _gain_e.value if _gain_e is not None else gain
        _dip_e = store.read("aocs.ctrl.bdot_max_dipole")
        _max_dip = _dip_e.value if _dip_e is not None else max_dipole

        mx = max(-_max_dip, min(_max_dip, -_gain * bdot_x))
        my = max(-_max_dip, min(_max_dip, -_gain * bdot_y))
        mz = max(-_max_dip, min(_max_dip, -_gain * bdot_z))

        eq.write_port(f"{_mtq_pfx}.dipole_x", mx)
        eq.write_port(f"{_mtq_pfx}.dipole_y", my)
        eq.write_port(f"{_mtq_pfx}.dipole_z", mz)
        eq.write_port(f"{_pfx}.bdot_x", bdot_x)
        eq.write_port(f"{_pfx}.bdot_y", bdot_y)
        eq.write_port(f"{_pfx}.bdot_z", bdot_z)
        eq.write_port(f"{_pfx}.active", 1.0)

        state["b_prev_x"] = bx
        state["b_prev_y"] = by
        state["b_prev_z"] = bz

        logger.debug(
            "[%s] t=%.1f B=(%.2e,%.2e,%.2e) Bdot=(%.2e,%.2e,%.2e) m=(%.2f,%.2f,%.2f)",
            equipment_id, t, bx, by, bz, bdot_x, bdot_y, bdot_z, mx, my, mz,
        )

    return NativeEquipment(
        equipment_id=equipment_id,
        ports=[
            PortDefinition(f"{_pfx}.enable", PortDirection.IN,
                           description="Enable b-dot control (0=off, 1=on)"),
            PortDefinition(f"{_mag_pfx}.field_x", PortDirection.IN,
                           unit="T", description="MAG field X"),
            PortDefinition(f"{_mag_pfx}.field_y", PortDirection.IN,
                           unit="T", description="MAG field Y"),
            PortDefinition(f"{_mag_pfx}.field_z", PortDirection.IN,
                           unit="T", description="MAG field Z"),
            PortDefinition(f"{_mtq_pfx}.dipole_x", PortDirection.OUT,
                           unit="Am2", description="MTQ dipole X command"),
            PortDefinition(f"{_mtq_pfx}.dipole_y", PortDirection.OUT,
                           unit="Am2", description="MTQ dipole Y command"),
            PortDefinition(f"{_mtq_pfx}.dipole_z", PortDirection.OUT,
                           unit="Am2", description="MTQ dipole Z command"),
            PortDefinition(f"{_pfx}.bdot_x", PortDirection.OUT,
                           unit="T/s", description="Estimated B-dot X"),
            PortDefinition(f"{_pfx}.bdot_y", PortDirection.OUT,
                           unit="T/s", description="Estimated B-dot Y"),
            PortDefinition(f"{_pfx}.bdot_z", PortDirection.OUT,
                           unit="T/s", description="Estimated B-dot Z"),
            PortDefinition(f"{_pfx}.active", PortDirection.OUT,
                           description="Controller active flag"),
        ],
        step_fn=_bdot_step,
        sync_protocol=sync_protocol,
        store=store,
        command_store=command_store,
    )
