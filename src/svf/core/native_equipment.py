"""
SVF NativeEquipment
Wraps a plain Python class as an Equipment implementation.
Replaces NativeModelAdapter.
Implements: SVF-DEV-015
"""

from __future__ import annotations

import logging
from typing import Callable, Optional

from svf.core.abstractions import SyncProtocol
from svf.core.equipment import Equipment, PortDefinition, PortDirection
from svf.stores.parameter_store import ParameterStore
from svf.stores.command_store import CommandStore

logger = logging.getLogger(__name__)

# Type for the step function
StepFn = Callable[["NativeEquipment", float, float], None]


class NativeEquipment(Equipment):
    """
    Wraps a plain Python step function as Equipment.

    The step function receives the equipment instance so it can
    call read_port() and write_port():

        def my_step(eq: NativeEquipment, t: float, dt: float) -> None:
            enabled = eq.read_port("power_enable")
            speed = eq.read_port("speed") + enabled * dt * 100
            eq.write_port("speed", speed)

        eq = NativeEquipment(
            equipment_id="rw1",
            ports=[
                PortDefinition("power_enable", PortDirection.IN),
                PortDefinition("speed", PortDirection.OUT, unit="rpm"),
            ],
            step_fn=my_step,
            sync_protocol=sync,
            store=store,
        )

    For simple cases where no port access is needed in step,
    the function can just write fixed values:

        def constant_source(eq, t, dt):
            eq.write_port("power_out", 90.0)
    """

    def __init__(
        self,
        equipment_id: str,
        ports: list[PortDefinition],
        step_fn: StepFn,
        sync_protocol: SyncProtocol,
        store: ParameterStore,
        command_store: Optional[CommandStore] = None,
    ) -> None:
        self._port_definitions = ports
        self._step_fn = step_fn
        super().__init__(
            equipment_id=equipment_id,
            sync_protocol=sync_protocol,
            store=store,
            command_store=command_store,
        )

    def _declare_ports(self) -> list[PortDefinition]:
        return list(self._port_definitions)

    def initialise(self, start_time: float = 0.0) -> None:
        logger.info(f"[{self._equipment_id}] NativeEquipment initialised")

    def suggested_dt(self) -> Optional[float]:
        """Default: no preference — use SimulationMaster's fixed dt."""
        return None

    def do_step(self, t: float, dt: float) -> None:
        self._step_fn(self, t, dt)

    def teardown(self) -> None:
        logger.info(f"[{self._equipment_id}] NativeEquipment teardown")
