"""
SVF FmuModelAdapter
Wraps an FMI 3.0 FMU and implements the ModelAdapter interface.
Writes outputs to ParameterStore and acknowledges sync after each tick.
Implements: SVF-DEV-014, SVF-DEV-031, SVF-DEV-033
"""

import logging
from pathlib import Path
from typing import Any, Optional, Union

from fmpy import read_model_description, extract  # type: ignore[import-untyped]
from fmpy.simulation import instantiate_fmu      # type: ignore[import-untyped]

from svf.abstractions import ModelAdapter, SyncProtocol
from svf.parameter_store import ParameterStore
from svf.logging import CsvLogger

logger = logging.getLogger(__name__)


class FmuModelAdapter(ModelAdapter):
    """
    Wraps an FMI 3.0 FMU as a ModelAdapter.

    After each tick:
      - Steps the FMU via fmpy
      - Writes each output variable to the ParameterStore
      - Optionally records to CsvLogger
      - Publishes sync acknowledgement via SyncProtocol

    Usage:
        store = ParameterStore()
        adapter = FmuModelAdapter(
            fmu_path="models/power.fmu",
            model_id="power",
            sync_protocol=sync,
            store=store,
        )
        adapter.initialise(start_time=0.0)
        adapter.on_tick(t=0.0, dt=0.1)
        adapter.teardown()
    """

    def __init__(
        self,
        fmu_path: Union[str, Path],
        model_id: str,
        sync_protocol: SyncProtocol,
        store: ParameterStore,
        csv_logger: Optional[CsvLogger] = None,
    ) -> None:
        self._fmu_path = Path(fmu_path)
        self._model_id = model_id
        self._sync_protocol = sync_protocol
        self._store = store
        self._csv_logger = csv_logger
        self._instance: Optional[Any] = None
        self._model_desc: Optional[Any] = None
        self._output_names: list[str] = []

        if not self._fmu_path.exists():
            raise FileNotFoundError(f"FMU not found: {self._fmu_path}")

    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def output_names(self) -> list[str]:
        return list(self._output_names)

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
        logger.info(f"[{self._model_id}] Output variables: {self._output_names}")

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
            self._csv_logger.open(self._output_names)

        logger.info(f"[{self._model_id}] Initialised at t={start_time}")

    def on_tick(self, t: float, dt: float) -> None:
        """
        Step the FMU, write outputs to ParameterStore, acknowledge sync.
        Raises RuntimeError on any failure.
        """
        if self._instance is None or self._model_desc is None:
            raise RuntimeError(
                f"[{self._model_id}] Cannot tick: not initialised."
            )

        try:
            self._instance.doStep(
                currentCommunicationPoint=t,
                communicationStepSize=dt,
            )

            vrs = [
                v.valueReference for v in self._model_desc.modelVariables
                if v.causality == "output"
            ]
            values = self._instance.getReal(vrs)
            outputs = dict(zip(self._output_names, values))

            stepped_t = round(t + dt, 9)

            # Write all outputs to ParameterStore
            for name, value in outputs.items():
                self._store.write(
                    name=name,
                    value=value,
                    t=stepped_t,
                    model_id=self._model_id,
                )

            if self._csv_logger is not None:
                self._csv_logger.record(time=stepped_t, outputs=outputs)

            logger.debug(f"[{self._model_id}] t={stepped_t:.3f} {outputs}")

        except Exception as e:
            raise RuntimeError(
                f"[{self._model_id}] Tick failed at t={t:.3f}: {e}"
            ) from e

        # Adapter speaks for itself
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