"""A NativeEquipment factory: the step function closes over the port prefix."""
from svf.core.equipment import PortDefinition, PortDirection
from svf.core.native_equipment import NativeEquipment


def make_toy_wheel(sync, store, cmd_store, equipment_id="rw1"):  # type: ignore[no-untyped-def]
    pfx = f"aocs.{equipment_id}"

    def step(eq: NativeEquipment, t: float, dt: float) -> None:
        torque = eq.read_port(f"{pfx}.torque_cmd")
        speed = eq.read_port(f"{pfx}.speed")
        eq.write_port(f"{pfx}.speed", speed + torque * 100.0 * dt)

    return NativeEquipment(
        equipment_id=equipment_id,
        ports=[
            PortDefinition(f"{pfx}.torque_cmd", PortDirection.IN, unit="Nm"),
            PortDefinition(f"{pfx}.speed", PortDirection.OUT, unit="rpm"),
        ],
        step_fn=step,
        sync_protocol=sync,
        store=store,
        command_store=cmd_store,
    )
