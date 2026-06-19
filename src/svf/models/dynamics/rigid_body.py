"""
SVF Rigid Body Attitude Dynamics - M49
Pure-Python integrator for spacecraft angular velocity and quaternion attitude.

Propagates attitude using Euler's equation (body angular velocity) and
quaternion kinematics. Designed specifically to close the B-dot detumbling
loop in SVF demos without requiring the KDE C++ FMU.

Physics:
    Euler's equation (body frame, diagonal inertia tensor):
        I * d(omega)/dt = tau - omega x (I * omega)
    Quaternion kinematics (q = [w, x, y, z], NED-to-body, scalar-first):
        dq/dt = 0.5 * q o [0, omega]
    Integration: first-order Euler, dt=1s typical.

The model also rotates the NED orbital B-field into body frame so the
magnetometer receives the correct body-frame true field.

Implements: SVF-DEV-181

Inputs (all IN ports):
    orbital.mag_field_n/e/d   T       NED B-field from OrbitalEnvironment
    aocs.mtq.torque_x/y/z     Nm      MTQ torque in body frame (from Python MTQ model)

Outputs (all OUT ports):
    aocs.body.omega_x/y/z     rad/s   True angular velocity, body frame
    aocs.body.omega_norm      rad/s   Angular velocity magnitude
    aocs.attitude.quaternion_w/x/y/z  NED-to-body attitude quaternion
    aocs.body.b_true_x/y/z    T       B-field rotated to body frame (wires to mag.true_*)
"""

from __future__ import annotations

import logging
import math
from typing import Any, Optional

from svf.core.abstractions import SyncProtocol
from svf.core.equipment import PortDefinition, PortDirection
from svf.core.native_equipment import NativeEquipment
from svf.stores.command_store import CommandStore
from svf.stores.parameter_store import ParameterStore

logger = logging.getLogger(__name__)

# Default 3U CubeSat principal-axis inertia tensor (kg*m^2)
_DEFAULT_IXX = 0.020
_DEFAULT_IYY = 0.020
_DEFAULT_IZZ = 0.008

# Default initial body rates (rad/s) - representative tumbling state
_DEFAULT_OMEGA0 = (
    3.0 * math.pi / 180.0,   # 3 deg/s about x
    2.0 * math.pi / 180.0,   # 2 deg/s about y
    1.0 * math.pi / 180.0,   # 1 deg/s about z
)


def _quat_kinematics_delta(
    q: list[float], omega: tuple[float, float, float]
) -> list[float]:
    """
    Compute dq/dt = 0.5 * q o [0, omega] for quaternion q = [w, x, y, z].
    omega is body angular velocity in body frame (rad/s).
    """
    qw, qx, qy, qz = q
    ox, oy, oz = omega
    return [
        0.5 * (-qx*ox - qy*oy - qz*oz),
        0.5 * ( qw*ox + qz*oy - qy*oz),
        0.5 * ( qw*oy - qz*ox + qx*oz),
        0.5 * ( qw*oz + qy*ox - qx*oy),
    ]


def _quat_normalize(q: list[float]) -> list[float]:
    n = math.sqrt(q[0]*q[0] + q[1]*q[1] + q[2]*q[2] + q[3]*q[3])
    if n < 1e-12:
        return [1.0, 0.0, 0.0, 0.0]
    return [v / n for v in q]


def _rotate_ned_to_body(
    q: list[float], v_ned: tuple[float, float, float]
) -> tuple[float, float, float]:
    """
    Rotate vector v_ned from NED to body frame using quaternion q = [w, x, y, z].
    q represents the NED-to-body rotation: v_body = R(q) * v_ned.
    """
    qw, qx, qy, qz = q
    vx, vy, vz = v_ned
    # Direction cosine matrix (NED to body)
    r00 = 1.0 - 2.0*(qy*qy + qz*qz)
    r01 = 2.0*(qx*qy + qw*qz)
    r02 = 2.0*(qx*qz - qw*qy)
    r10 = 2.0*(qx*qy - qw*qz)
    r11 = 1.0 - 2.0*(qx*qx + qz*qz)
    r12 = 2.0*(qy*qz + qw*qx)
    r20 = 2.0*(qx*qz + qw*qy)
    r21 = 2.0*(qy*qz - qw*qx)
    r22 = 1.0 - 2.0*(qx*qx + qy*qy)
    return (
        r00*vx + r01*vy + r02*vz,
        r10*vx + r11*vy + r12*vz,
        r20*vx + r21*vy + r22*vz,
    )


def make_rigid_body_dynamics(
    sync_protocol: SyncProtocol,
    store: ParameterStore,
    command_store: Optional[CommandStore] = None,
    equipment_id: str = "rigid_body",
    ixx: float = _DEFAULT_IXX,
    iyy: float = _DEFAULT_IYY,
    izz: float = _DEFAULT_IZZ,
    omega0: tuple[float, float, float] = _DEFAULT_OMEGA0,
    q0: tuple[float, float, float, float] = (1.0, 0.0, 0.0, 0.0),
) -> NativeEquipment:
    """
    Create a RigidBodyDynamics NativeEquipment.

    Args:
        equipment_id: Instance name (default 'rigid_body').
        ixx, iyy, izz: Principal-axis moments of inertia (kg*m^2).
        omega0:  Initial angular velocity (rad/s) in body frame (x, y, z).
        q0:      Initial attitude quaternion [w, x, y, z] (NED-to-body).

    Inputs:
        orbital.mag_field_n/e/d  - NED B-field from OrbitalEnvironment (T)
        aocs.mtq.torque_x/y/z   - MTQ torque in body frame (Nm)

    Outputs:
        aocs.body.omega_x/y/z   - Angular velocity, body frame (rad/s)
        aocs.body.omega_norm    - Angular velocity magnitude (rad/s)
        aocs.attitude.quaternion_w/x/y/z - NED-to-body attitude quaternion
        aocs.body.b_true_x/y/z  - B-field in body frame (T), wires to mag.true_*
    """
    state: dict[str, Any] = {
        "omega": list(omega0),              # [wx, wy, wz] rad/s body frame
        "q":     list(q0),                  # [qw, qx, qy, qz] NED-to-body
    }

    def _step(eq: NativeEquipment, t: float, dt: float) -> None:
        omega = state["omega"]
        q     = state["q"]

        # Read inputs
        bn = eq.read_port("orbital.mag_field_n")
        be = eq.read_port("orbital.mag_field_e")
        bd = eq.read_port("orbital.mag_field_d")
        tx = eq.read_port("aocs.mtq.torque_x")
        ty = eq.read_port("aocs.mtq.torque_y")
        tz = eq.read_port("aocs.mtq.torque_z")

        wx, wy, wz = omega[0], omega[1], omega[2]

        # Euler's equation (principal axes): I * alpha = tau - omega x (I * omega)
        # alpha = I^-1 * (tau - omega x (I * omega))
        iwx = ixx * wx
        iwy = iyy * wy
        iwz = izz * wz
        # omega x (I * omega) = [wy*iwz - wz*iwy, wz*iwx - wx*iwz, wx*iwy - wy*iwx]
        gyro_x = wy*iwz - wz*iwy
        gyro_y = wz*iwx - wx*iwz
        gyro_z = wx*iwy - wy*iwx

        ax = (tx - gyro_x) / ixx
        ay = (ty - gyro_y) / iyy
        az = (tz - gyro_z) / izz

        # Euler integration of angular velocity
        omega[0] += ax * dt
        omega[1] += ay * dt
        omega[2] += az * dt

        # Quaternion kinematics
        dq = _quat_kinematics_delta(q, (omega[0], omega[1], omega[2]))
        for i in range(4):
            q[i] += dq[i] * dt
        state["q"] = _quat_normalize(q)
        q = state["q"]

        # Rotate NED B-field to body frame
        bx, by, bz = _rotate_ned_to_body(q, (bn, be, bd))

        # Compute omega magnitude
        omega_norm = math.sqrt(omega[0]**2 + omega[1]**2 + omega[2]**2)

        # Write outputs
        eq.write_port("aocs.body.omega_x",            omega[0])
        eq.write_port("aocs.body.omega_y",            omega[1])
        eq.write_port("aocs.body.omega_z",            omega[2])
        eq.write_port("aocs.body.omega_norm",         omega_norm)
        eq.write_port("aocs.attitude.quaternion_w",   q[0])
        eq.write_port("aocs.attitude.quaternion_x",   q[1])
        eq.write_port("aocs.attitude.quaternion_y",   q[2])
        eq.write_port("aocs.attitude.quaternion_z",   q[3])
        eq.write_port("aocs.body.b_true_x",           bx)
        eq.write_port("aocs.body.b_true_y",           by)
        eq.write_port("aocs.body.b_true_z",           bz)

        logger.debug(
            "[%s] t=%.1f omega=(%.4f,%.4f,%.4f) |w|=%.4f deg/s",
            equipment_id, t,
            math.degrees(omega[0]),
            math.degrees(omega[1]),
            math.degrees(omega[2]),
            math.degrees(omega_norm),
        )

    return NativeEquipment(
        equipment_id=equipment_id,
        ports=[
            # Inputs
            PortDefinition("orbital.mag_field_n", PortDirection.IN,
                           unit="T", description="NED north B-field from orbital env"),
            PortDefinition("orbital.mag_field_e", PortDirection.IN,
                           unit="T", description="NED east B-field from orbital env"),
            PortDefinition("orbital.mag_field_d", PortDirection.IN,
                           unit="T", description="NED down B-field from orbital env"),
            PortDefinition("aocs.mtq.torque_x", PortDirection.IN,
                           unit="Nm", description="MTQ torque X in body frame"),
            PortDefinition("aocs.mtq.torque_y", PortDirection.IN,
                           unit="Nm", description="MTQ torque Y in body frame"),
            PortDefinition("aocs.mtq.torque_z", PortDirection.IN,
                           unit="Nm", description="MTQ torque Z in body frame"),
            # Outputs
            PortDefinition("aocs.body.omega_x", PortDirection.OUT,
                           unit="rad/s", description="True angular velocity X"),
            PortDefinition("aocs.body.omega_y", PortDirection.OUT,
                           unit="rad/s", description="True angular velocity Y"),
            PortDefinition("aocs.body.omega_z", PortDirection.OUT,
                           unit="rad/s", description="True angular velocity Z"),
            PortDefinition("aocs.body.omega_norm", PortDirection.OUT,
                           unit="rad/s", description="Angular velocity magnitude"),
            PortDefinition("aocs.attitude.quaternion_w", PortDirection.OUT,
                           description="Attitude quaternion W (NED-to-body)"),
            PortDefinition("aocs.attitude.quaternion_x", PortDirection.OUT,
                           description="Attitude quaternion X"),
            PortDefinition("aocs.attitude.quaternion_y", PortDirection.OUT,
                           description="Attitude quaternion Y"),
            PortDefinition("aocs.attitude.quaternion_z", PortDirection.OUT,
                           description="Attitude quaternion Z"),
            PortDefinition("aocs.body.b_true_x", PortDirection.OUT,
                           unit="T", description="True B-field in body frame X"),
            PortDefinition("aocs.body.b_true_y", PortDirection.OUT,
                           unit="T", description="True B-field in body frame Y"),
            PortDefinition("aocs.body.b_true_z", PortDirection.OUT,
                           unit="T", description="True B-field in body frame Z"),
        ],
        step_fn=_step,
        sync_protocol=sync_protocol,
        store=store,
        command_store=command_store,
    )
