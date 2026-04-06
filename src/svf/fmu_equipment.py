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

from svf.abstractions import SyncProtocol
from svf.equipment import Equipment, PortDefinition, PortDirection
from svf.parameter_store import ParameterStore
from svf.command_store import CommandStore

logger = logging.getLogger(__name__)


class FmuEquipment(Equipment):
    """
    Wraps an FMI 3.0 FMU as an Equipment.

    FMU input variables are exposed as IN ports.
    FMU output variables are exposed as OUT ports.

    The parameter_map translates FMU variable names to port names
    (SRDB canonical names preferred):
        parameter_map = {
            "battery_soc":        "eps.battery.soc",
            "solar_illumination": "eps.solar_array.illumination",
        }

    Usage:
        eq = FmuEquipment(
            fmu_path="models/fmu/EpsFmu.fmu",
            equipment_id="eps",
            sync_protocol=sync,
            store=store,
            command_store=cmd_store,
            parameter_map=EPS_PARAMETER_MAP,
        )
    """

    def __init__(
        self,
        fmu_path: Union[str, Path],
        equipment_id: str,
        sync_protocol: SyncProtocol,
        store: ParameterStore,
        command_store: Optional[CommandStore] = None,
        parameter_map: Optional[dict[str, str]] = None,
    ) -> None:
        self._fmu_path = Path(fmu_path)
        self._parameter_map: dict[str, str] = parameter_map or {}
        self._reverse_map: dict[str, str] = {
            v: k for k, v in self._parameter_map.items()
        }
        self._instance: Optional[Any] = None
        self._fmu_output_names: list[str] = []
        self._fmu_input_names: list[str] = []

        if not self._fmu_path.exists():
            raise FileNotFoundError(f"FMU not found: {self._fmu_path}")

        # Read model description before super().__init__ so
        # _declare_ports() can use the variable lists
        self._model_desc = read_model_description(str(self._fmu_path))
        self._fmu_output_names = [
            v.name for v in self._model_desc.modelVariables
            if v.causality == "output"
        ]
        self._fmu_input_names = [
            v.name for v in self._model_desc.modelVariables
            if v.causality == "input"
        ]

        super().__init__(
            equipment_id=equipment_id,
            sync_protocol=sync_protocol,
            store=store,
            command_store=command_store,
        )

    def _port_name(self, fmu_name: str) -> str:
        return self._parameter_map.get(fmu_name, fmu_name)

    def _declare_ports(self) -> list[PortDefinition]:
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
        Apply IN port values to FMU inputs, advance FMU,
        read FMU outputs into OUT ports.
        """
        if self._instance is None:
            raise RuntimeError(
                f"[{self._equipment_id}] Cannot step: not initialised."
            )

        # Apply IN ports to FMU inputs
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

        # Advance FMU
        self._instance.doStep(
            currentCommunicationPoint=t,
            communicationStepSize=dt,
        )

        # Read FMU outputs into OUT ports
        for fmu_name in self._fmu_output_names:
            vrs = [
                v.valueReference
                for v in self._model_desc.modelVariables
                if v.name == fmu_name
            ]
            if vrs:
                values = self._instance.getReal(vrs)
                port_name = self._port_name(fmu_name)
                self._port_values[port_name] = float(values[0])

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
