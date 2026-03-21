"""
SVF Simulation Master
Owns the lifecycle of a single FMU: initialise, step, teardown.
Implements: SVF-DEV-001, SVF-DEV-002, SVF-DEV-005, SVF-DEV-006, SVF-DEV-007
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from fmpy import read_model_description, extract  # type: ignore[import-untyped]
from fmpy.simulation import instantiate_fmu  # type: ignore[import-untyped]

from svf.logging import CsvLogger

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
        master.teardown()

    With CSV logging:
        csv_logger = CsvLogger(output_dir="results", run_id="my_run")
        with SimulationMaster("model.fmu", dt=0.1, csv_logger=csv_logger) as master:
            master.initialise()
            for step in range(100):
                master.step()

    Or as a context manager without logging:
        with SimulationMaster("model.fmu", dt=0.1) as master:
            master.initialise()
            for step in range(100):
                master.step()
    """

    def __init__(
        self,
        fmu_path: str | Path,
        dt: float = 0.1,
        csv_logger: Optional[CsvLogger] = None,
    ) -> None:
        self.fmu_path = Path(fmu_path)
        self.dt = dt
        self._csv_logger = csv_logger
        self._time: float = 0.0
        self._instance: Optional[Any] = None
        self._model_desc: Optional[Any] = None
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

        if self._csv_logger is not None:
            self._csv_logger.open(self._output_names)

        logger.info(f"FMU initialised at t={self._time}")

    def step(self) -> dict[str, float]:
        """
        Advance simulation by one timestep (dt).
        Returns a dict of {variable_name: value} for all output variables.
        Raises SimulationError if called before initialise() or if step fails.
        """
        if self._instance is None or self._model_desc is None:
            raise SimulationError(
                "Cannot step: FMU has not been initialised. Call initialise() first."
            )

        try:
            self._instance.doStep(
                currentCommunicationPoint=self._time,
                communicationStepSize=self.dt,
            )
            self._time += self.dt

            vrs = [
                v.valueReference for v in self._model_desc.modelVariables
                if v.causality == "output"
            ]
            values = self._instance.getReal(vrs)
            outputs = dict(zip(self._output_names, values))

            if self._csv_logger is not None:
                self._csv_logger.record(time=self._time, outputs=outputs)

            logger.debug(f"t={self._time:.3f} {outputs}")
            return outputs

        except Exception as e:
            raise SimulationError(f"Step failed at t={self._time:.3f}: {e}") from e

    def teardown(self) -> None:
        """
        Terminate and clean up the FMU instance.
        Safe to call even if initialise() was never called.
        """
        if self._csv_logger is not None:
            self._csv_logger.close()

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