"""
SVF Simulation Master
Owns the lifecycle of a single FMU: initialise, step, teardown.
Implements: SVF-DEV-001, SVF-DEV-002, SVF-DEV-006, SVF-DEV-007
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from fmpy import read_model_description
from fmpy.simulation import (
    apply_start_values,
    instantiate_fmu,
)
from fmpy import extract

logger = logging.getLogger(__name__)


class SimulationError(Exception):
    """Raised when the simulation master encounters a non-recoverable error."""
    pass


class SimulationMaster:
    """
    Manages the lifecycle of a single FMU simulation.

    Usage:
        master = SimulationMaster("path/to/model.fmu", dt=0.1)
        master.initialise(start_time=0.0)
        for step in range(100):
            outputs = master.step()
            print(outputs)
        master.teardown()

    Or as a context manager:
        with SimulationMaster("path/to/model.fmu", dt=0.1) as master:
            for step in range(100):
                print(master.step())
    """

    def __init__(self, fmu_path: str | Path, dt: float = 0.1) -> None:
        self.fmu_path = Path(fmu_path)
        self.dt = dt
        self._time: float = 0.0
        self._instance: Optional[object] = None
        self._unzipdir: Optional[str] = None
        self._output_names: list[str] = []

        if not self.fmu_path.exists():
            raise SimulationError(f"FMU not found: {self.fmu_path}")

    def initialise(self, start_time: float = 0.0) -> None:
        """
        Load and initialise the FMU, ready for stepping.
        Raises SimulationError with a descriptive message on failure.
        """
        self._time = start_time
        logger.info(f"Initialising FMU: {self.fmu_path.name}")

        try:
            self._model_desc = read_model_description(str(self.fmu_path))
        except Exception as e:
            raise SimulationError(
                f"Failed to read model description from {self.fmu_path.name}: {e}"
            ) from e

        # Collect output variable names for reporting
        self._output_names = [
            v.name for v in self._model_desc.modelVariables
            if v.causality == "output"
        ]
        logger.info(f"Output variables: {self._output_names}")

        try:
            self._unzipdir = extract(str(self.fmu_path))
            self._instance = instantiate_fmu(
                unzipdir=self._unzipdir,
                model_description=self._model_desc,
                fmi_type="CoSimulation",
            )
            self._instance.setupExperiment(startTime=self._time)
            self._instance.enterInitializationMode()
            self._instance.exitInitializationMode()
        except Exception as e:
            raise SimulationError(
                f"Failed to initialise FMU {self.fmu_path.name}: {e}"
            ) from e

        logger.info(f"FMU initialised at t={self._time}")

    def step(self) -> dict[str, float]:
        """
        Advance simulation by one timestep (dt).
        Returns a dict of {variable_name: value} for all output variables.
        Raises SimulationError if called before initialise() or if the step fails.
        """
        if self._instance is None:
            raise SimulationError("Cannot step: FMU has not been initialised. Call initialise() first.")

        try:
            self._instance.doStep(
                currentCommunicationPoint=self._time,
                communicationStepSize=self.dt,
            )
            self._time += self.dt

            # Read output variable values by their value references
            vrs = [
                v.valueReference for v in self._model_desc.modelVariables
                if v.causality == "output"
            ]
            values = self._instance.getReal(vrs)
            outputs = dict(zip(self._output_names, values))

            logger.debug(f"t={self._time:.3f} {outputs}")
            return outputs

        except Exception as e:
            raise SimulationError(
                f"Step failed at t={self._time:.3f}: {e}"
            ) from e

    def teardown(self) -> None:
        """
        Terminate and clean up the FMU instance.
        Safe to call even if initialise() was never called.
        """
        if self._instance is not None:
            try:
                self._instance.terminate()
                self._instance.freeInstance()
            except Exception as e:
                logger.warning(f"Error during FMU teardown: {e}")
            finally:
                self._instance = None
                logger.info("FMU teardown complete")

    @property
    def time(self) -> float:
        """Current simulation time in seconds."""
        return self._time

    @property
    def output_names(self) -> list[str]:
        """Names of all output variables exposed by the FMU."""
        return list(self._output_names)

    def __enter__(self) -> "SimulationMaster":
        return self

    def __exit__(self, *args: object) -> None:
        self.teardown()