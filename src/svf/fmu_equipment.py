"""
SVF FmuEquipment
Wraps an FMI 3.0 FMU as an Equipment implementation.
Maps FMU variable names to Equipment port names via parameter_map.
Implements: SVF-DEV-004, SVF-DEV-014
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional, Union

from fmpy import read_model_description, extract  # type: ignore[import-untyped]
from fmpy.simulation import instantiate_fmu      # type: ignore[import-untyped]

from svf.equipment import Equipment, PortDefinition, PortDirection

logger = logging.getLogger(__name__)


class FmuEquipment(Equipment):
    """
    Wraps an FMI 3.0 FMU as an Equipment.

    FMU input variables are exposed as IN ports.
    FMU output variables are exposed as OUT ports.

    The parameter_map translates between FMU variable names and
    Equipment port names (which should be SRDB canonical names):
        parameter_map = {
            "battery_soc": "eps.battery.soc",     # FMU out -> port name
            "solar_illumination": "eps.solar_array.illumination",  # FMU in -> port name
        }

    If no mapping exists for a variable, the raw FMU name is used as the port name.

    Usage:
        equipment = FmuEquipment(
            fmu_path="models/Battery.fmu",
            equipment_id="battery",
            parameter_map={
                "soc": "eps.battery.soc",
                "voltage": "eps.battery.voltage",
                "charge_current": "eps.battery.charge_current_in",
            }
        )
        equipment.initialise()
        equipment.do_step(t=0.0, dt=1.0)
        soc = equipment.read_port("eps.battery.soc")
    """

    def __init__(
        self,
        fmu_path: Union[str, Path],
        equipment_id: str,
        parameter_map: Optional[dict[str, str]] = None,
    ) -> None:
        self._fmu_path = Path(fmu_path)
        self._parameter_map: dict[str, str] = parameter_map or {}
        self._reverse_map: dict[str, str] = {
            v: k for k, v in self._parameter_map.items()
        }
        self._instance: Optional[Any] = None
        self._model_desc: Optional[Any] = None
        self._fmu_output_names: list[str] = []
        self._fmu_input_names: list[str] = []

        if not self._fmu_path.exists():
            raise FileNotFoundError(f"FMU not found: {self._fmu_path}")

        # Read model description to discover ports before super().__init__
        # so _declare_ports() can use them
        self._model_desc = read_model_description(str(self._fmu_path))
        self._fmu_output_names = [
            v.name for v in self._model_desc.modelVariables
            if v.causality == "output"
        ]
        self._fmu_input_names = [
            v.name for v in self._model_desc.modelVariables
            if v.causality == "input"
        ]

        # Now call super().__init__ which calls _declare_ports()
        super().__init__(equipment_id)

    def _port_name(self, fmu_name: str) -> str:
        """Translate FMU variable name to port name."""
        return self._parameter_map.get(fmu_name, fmu_name)

    def _fmu_var_name(self, port_name: str) -> str:
        """Translate port name to FMU variable name."""
        return self._reverse_map.get(port_name, port_name)

    def _declare_ports(self) -> list[PortDefinition]:
        """Declare ports from FMU model description."""
        ports: list[PortDefinition] = []

        for name in self._fmu_output_names:
            ports.append(PortDefinition(
                name=self._port_name(name),
                direction=PortDirection.OUT,
            ))

        for name in self._fmu_input_names:
            ports.append(PortDefinition(
                name=self._port_name(name),
                direction=PortDirection.IN,
            ))

        return ports

    def initialise(self, start_time: float = 0.0) -> None:
        """Load and initialise the FMU."""
        logger.info(f"[{self._equipment_id}] Initialising: {self._fmu_path.name}")
        try:
            unzipdir = extract(str(self._fmu_path))
            self._instance = instantiate_fmu(
                unzipdir=unzipdir,
                model_description=self._model_desc,
                fmi_type="CoSimulation",
            )
            self._instance.setupExperiment(startTime=start_time)
            self._instance.enterInitializationMode()
            self._instance.exitInitializationMode()
        except Exception as e:
            raise RuntimeError(
                f"[{self._equipment_id}] Failed to initialise: {e}"
            ) from e
        logger.info(f"[{self._equipment_id}] Initialised at t={start_time}")

    def do_step(self, t: float, dt: float) -> None:
        """
        Step 1: Apply IN port values to FMU inputs.
        Step 2: Advance FMU by dt.
        Step 3: Read FMU outputs into OUT ports.
        """
        if self._instance is None or self._model_desc is None:
            raise RuntimeError(
                f"[{self._equipment_id}] Cannot step: not initialised."
            )

        # Step 1: apply IN port values to FMU inputs
        for fmu_name in self._fmu_input_names:
            port_name = self._port_name(fmu_name)
            value = self.read_port(port_name)
            vrs = [
                v.valueReference
                for v in self._model_desc.modelVariables
                if v.name == fmu_name
            ]
            if vrs:
                self._instance.setReal(vrs, [value])

        # Step 2: advance
        self._instance.doStep(
            currentCommunicationPoint=t,
            communicationStepSize=dt,
        )

        # Step 3: read outputs into OUT ports
        for fmu_name in self._fmu_output_names:
            vrs = [
                v.valueReference
                for v in self._model_desc.modelVariables
                if v.name == fmu_name
            ]
            if vrs:
                values = self._instance.getReal(vrs)
                port_name = self._port_name(fmu_name)
                # Use parent's internal dict directly to bypass OUT check
                self._port_values[port_name] = float(values[0])

        logger.debug(
            f"[{self._equipment_id}] t={round(t + dt, 9):.3f} "
            f"out={[(self._port_name(n), self._port_values[self._port_name(n)]) for n in self._fmu_output_names]}"
        )

    def teardown(self) -> None:
        """Terminate and clean up the FMU."""
        if self._instance is not None:
            try:
                self._instance.terminate()
                self._instance.freeInstance()
            except Exception as e:
                logger.warning(f"[{self._equipment_id}] Teardown error: {e}")
            finally:
                self._instance = None
                logger.info(f"[{self._equipment_id}] Teardown complete")
