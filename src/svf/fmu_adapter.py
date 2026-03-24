"""
SVF FmuModelAdapter
Wraps an FMI 3.0 FMU and implements the ModelAdapter interface.
Reads commands from CommandStore, writes outputs to ParameterStore.
Supports optional parameter_map for SRDB canonical name mapping.
Implements: SVF-DEV-014, SVF-DEV-031, SVF-DEV-033, SVF-DEV-035, SVF-DEV-036
"""

import logging
from pathlib import Path
from typing import Any, Optional, Union

from fmpy import read_model_description, extract  # type: ignore[import-untyped]
from fmpy.simulation import instantiate_fmu      # type: ignore[import-untyped]

from svf.abstractions import ModelAdapter, SyncProtocol
from svf.parameter_store import ParameterStore
from svf.command_store import CommandStore
from svf.logging import CsvLogger

logger = logging.getLogger(__name__)


class FmuModelAdapter(ModelAdapter):
    """
    Wraps an FMI 3.0 FMU as a ModelAdapter.

    On each tick:
      1. Reads pending commands from CommandStore and applies to FMU inputs
      2. Steps the FMU via fmpy
      3. Writes each output variable to the ParameterStore
      4. Optionally records to CsvLogger
      5. Publishes sync acknowledgement via SyncProtocol

    Parameter mapping:
      The optional parameter_map translates between FMU variable names
      and SRDB canonical names. For outputs: FMU name -> canonical name.
      For inputs: canonical name -> FMU name (reverse lookup).

      Example:
          parameter_map = {
              "battery_soc": "eps.battery.soc",
              "solar_illumination": "eps.solar_array.illumination",
          }

      If no mapping exists for a variable, the raw FMU name is used.
    """

    def __init__(
        self,
        fmu_path: Union[str, Path],
        model_id: str,
        sync_protocol: SyncProtocol,
        store: ParameterStore,
        command_store: Optional[CommandStore] = None,
        csv_logger: Optional[CsvLogger] = None,
        parameter_map: Optional[dict[str, str]] = None,
    ) -> None:
        self._fmu_path = Path(fmu_path)
        self._model_id = model_id
        self._sync_protocol = sync_protocol
        self._store = store
        self._command_store = command_store
        self._csv_logger = csv_logger

        # FMU name -> canonical name (outputs)
        self._parameter_map: dict[str, str] = parameter_map or {}
        # canonical name -> FMU name (inputs, reverse lookup)
        self._reverse_map: dict[str, str] = {
            v: k for k, v in self._parameter_map.items()
        }

        self._instance: Optional[Any] = None
        self._model_desc: Optional[Any] = None
        self._output_names: list[str] = []
        self._input_names: list[str] = []

        if not self._fmu_path.exists():
            raise FileNotFoundError(f"FMU not found: {self._fmu_path}")

    def _canonical(self, fmu_name: str) -> str:
        """Translate FMU variable name to canonical SRDB name."""
        return self._parameter_map.get(fmu_name, fmu_name)

    def _fmu_name(self, canonical: str) -> str:
        """Translate canonical SRDB name to FMU variable name."""
        return self._reverse_map.get(canonical, canonical)

    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def output_names(self) -> list[str]:
        """Canonical output parameter names."""
        return [self._canonical(n) for n in self._output_names]

    @property
    def input_names(self) -> list[str]:
        """Canonical input parameter names."""
        return [self._canonical(n) for n in self._input_names]

    def initialise(self, start_time: float = 0.0) -> None:
        """Load and initialise the FMU ready for ticking."""
        logger.info(f"[{self._model_id}] Initialising FMU: {self._fmu_path.name}")

        try:
            self._model_desc = read_model_description(str(self._fmu_path))
        except Exception as e:
            raise RuntimeError(
                f"[{self._model_id}] Failed to read model description: {e}"
            ) from e

        self._output_names = [
            v.name for v in self._model_desc.modelVariables
            if v.causality == "output"
        ]
        self._input_names = [
            v.name for v in self._model_desc.modelVariables
            if v.causality == "input"
        ]
        logger.info(
            f"[{self._model_id}] Outputs: {self.output_names} "
            f"Inputs: {self.input_names}"
        )

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
                f"[{self._model_id}] Failed to initialise FMU: {e}"
            ) from e

        if self._csv_logger is not None:
            self._csv_logger.open(self.output_names)

        logger.info(f"[{self._model_id}] Initialised at t={start_time}")

    def on_tick(self, t: float, dt: float) -> None:
        """
        Apply pending commands, step the FMU, write outputs to store.
        """
        if self._instance is None or self._model_desc is None:
            raise RuntimeError(
                f"[{self._model_id}] Cannot tick: not initialised."
            )

        try:
            # Step 1: apply pending commands using canonical -> FMU name
            if self._command_store is not None:
                for fmu_input_name in self._input_names:
                    canonical = self._canonical(fmu_input_name)
                    entry = self._command_store.take(canonical)
                    # Also try raw FMU name if canonical lookup fails
                    if entry is None:
                        entry = self._command_store.take(fmu_input_name)
                    if entry is not None:
                        vrs = [
                            v.valueReference
                            for v in self._model_desc.modelVariables
                            if v.name == fmu_input_name
                        ]
                        if vrs:
                            self._instance.setReal(vrs, [entry.value])
                            logger.info(
                                f"[{self._model_id}] Applied command "
                                f"{canonical}={entry.value} "
                                f"from {entry.source_id}"
                            )

            # Step 2: advance the FMU
            self._instance.doStep(
                currentCommunicationPoint=t,
                communicationStepSize=dt,
            )

            # Step 3: read outputs and write to ParameterStore
            vrs = [
                v.valueReference for v in self._model_desc.modelVariables
                if v.causality == "output"
            ]
            values = self._instance.getReal(vrs)
            stepped_t = round(t + dt, 9)

            outputs: dict[str, float] = {}
            for fmu_name, value in zip(self._output_names, values):
                canonical = self._canonical(fmu_name)
                self._store.write(
                    name=canonical,
                    value=value,
                    t=stepped_t,
                    model_id=self._model_id,
                )
                outputs[canonical] = value

            if self._csv_logger is not None:
                self._csv_logger.record(time=stepped_t, outputs=outputs)

            logger.debug(f"[{self._model_id}] t={stepped_t:.3f} {outputs}")

        except Exception as e:
            raise RuntimeError(
                f"[{self._model_id}] Tick failed at t={t:.3f}: {e}"
            ) from e

        self._sync_protocol.publish_ready(model_id=self._model_id, t=t)

    def teardown(self) -> None:
        """Terminate and clean up the FMU instance."""
        if self._csv_logger is not None:
            self._csv_logger.close()

        if self._instance is not None:
            try:
                self._instance.terminate()
                self._instance.freeInstance()
            except Exception as e:
                logger.warning(f"[{self._model_id}] Error during teardown: {e}")
            finally:
                self._instance = None
                logger.info(f"[{self._model_id}] Teardown complete")