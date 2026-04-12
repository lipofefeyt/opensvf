"""
SVF KDE Equipment
NativeEquipment wrapper around the C++ Kinematics and Dynamics Engine FMU.

Bridges the opensvf-kde FMI 2.0 Co-Simulation binary into the SVF tick loop
with SRDB-canonical port names.

Port mapping:
  IN:  aocs.mtq.torque_x/y/z  ← MTQ generated torques (Nm)
  OUT: aocs.truth.rate_x/y/z  → GYRO/CSS truth input (rad/s)
       aocs.mag.true_x/y/z    → MAG truth input (T)
       aocs.attitude.quaternion_w/x/y/z → ParameterStore

Implements: KDE-001, KDE-002, KDE-003, KDE-004, SVF-DEV-061
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


def make_kde_equipment(
    sync_protocol: SyncProtocol,
    store: ParameterStore,
    command_store: Optional[CommandStore] = None,
    initial_omega: Optional[list[float]] = None,
) -> NativeEquipment:
    """
    Create a KDE NativeEquipment wrapping the SpacecraftDynamics FMU.

    Inputs:
        aocs.mtq.torque_x/y/z  — mechanical torques from MTQ (Nm)

    Outputs:
        aocs.truth.rate_x/y/z           — true angular rates (rad/s)
        aocs.mag.true_x/y/z             — true magnetic field (T)
        aocs.attitude.quaternion_w/x/y/z — true attitude quaternion
    """
    from svf.models.fmu.DynamicsFmu import DynamicsFmu

    dynamics: Optional[DynamicsFmu] = None
    sim_time: list[float] = [0.0]

    def _kde_step(eq: NativeEquipment, t: float, dt: float) -> None:
        nonlocal dynamics
        if dynamics is None:
            return

        torque = [
            eq.read_port("aocs.mtq.torque_x"),
            eq.read_port("aocs.mtq.torque_y"),
            eq.read_port("aocs.mtq.torque_z"),
        ]

        state = dynamics.step_at(t=sim_time[0], dt=dt, mechanical_torque=torque)
        sim_time[0] += dt

        eq.write_port("aocs.truth.rate_x", state["omega"][0])
        eq.write_port("aocs.truth.rate_y", state["omega"][1])
        eq.write_port("aocs.truth.rate_z", state["omega"][2])

        eq.write_port("aocs.mag.true_x", state["b_field"][0])
        eq.write_port("aocs.mag.true_y", state["b_field"][1])
        eq.write_port("aocs.mag.true_z", state["b_field"][2])

        eq.write_port("aocs.attitude.quaternion_w", state["attitude"][0])
        eq.write_port("aocs.attitude.quaternion_x", state["attitude"][1])
        eq.write_port("aocs.attitude.quaternion_y", state["attitude"][2])
        eq.write_port("aocs.attitude.quaternion_z", state["attitude"][3])

        logger.debug(
            f"[kde] t={t:.2f} ω=({state['omega'][0]:.4f},"
            f"{state['omega'][1]:.4f},{state['omega'][2]:.4f}) rad/s"
        )

    eq = NativeEquipment(
        equipment_id="kde",
        ports=[
            PortDefinition("aocs.mtq.torque_x", PortDirection.IN,
                           unit="Nm", description="MTQ torque X"),
            PortDefinition("aocs.mtq.torque_y", PortDirection.IN,
                           unit="Nm", description="MTQ torque Y"),
            PortDefinition("aocs.mtq.torque_z", PortDirection.IN,
                           unit="Nm", description="MTQ torque Z"),
            PortDefinition("aocs.truth.rate_x", PortDirection.OUT,
                           unit="rad/s", description="True angular rate X"),
            PortDefinition("aocs.truth.rate_y", PortDirection.OUT,
                           unit="rad/s", description="True angular rate Y"),
            PortDefinition("aocs.truth.rate_z", PortDirection.OUT,
                           unit="rad/s", description="True angular rate Z"),
            PortDefinition("aocs.mag.true_x", PortDirection.OUT,
                           unit="T", description="True magnetic field X"),
            PortDefinition("aocs.mag.true_y", PortDirection.OUT,
                           unit="T", description="True magnetic field Y"),
            PortDefinition("aocs.mag.true_z", PortDirection.OUT,
                           unit="T", description="True magnetic field Z"),
            PortDefinition("aocs.attitude.quaternion_w", PortDirection.OUT,
                           description="True attitude quaternion W"),
            PortDefinition("aocs.attitude.quaternion_x", PortDirection.OUT,
                           description="True attitude quaternion X"),
            PortDefinition("aocs.attitude.quaternion_y", PortDirection.OUT,
                           description="True attitude quaternion Y"),
            PortDefinition("aocs.attitude.quaternion_z", PortDirection.OUT,
                           description="True attitude quaternion Z"),
        ],
        step_fn=_kde_step,
        sync_protocol=sync_protocol,
        store=store,
        command_store=command_store,
    )

    # Lazy-initialise FMU on first initialise() call
    original_initialise = eq.initialise

    def _initialise(start_time: float = 0.0) -> None:
        nonlocal dynamics
        dynamics = DynamicsFmu(initial_omega=initial_omega)
        sim_time[0] = start_time
        logger.info("[kde] SpacecraftDynamics FMU initialised")
        original_initialise(start_time)

    eq.initialise = _initialise  # type: ignore[method-assign]
    return eq
