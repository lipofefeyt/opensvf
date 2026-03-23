"""
SVF NativeModelAdapter
Wraps a plain Python class as a ModelAdapter.
Writes outputs to ParameterStore and acknowledges sync after each tick.
Implements: SVF-DEV-015, SVF-DEV-031, SVF-DEV-033
"""

from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable, List

from svf.abstractions import ModelAdapter, SyncProtocol
from svf.parameter_store import ParameterStore

logger = logging.getLogger(__name__)


@runtime_checkable
class NativeModel(Protocol):
    """
    Protocol that a plain Python class must satisfy to be wrapped
    by NativeModelAdapter. No inheritance required.
    """
    def step(self, t: float, dt: float) -> dict[str, float]: ...


class NativeModelAdapter(ModelAdapter):
    """
    Wraps a plain Python class implementing the NativeModel protocol.

    After each tick:
      - Calls model.step(t, dt)
      - Writes each output to the ParameterStore
      - Calls sync_protocol.publish_ready()

    Output variable names must be declared explicitly at construction —
    the adapter never calls step() outside of on_tick() to avoid
    side effects during initialisation.

    Usage:
        class MyModel:
            def step(self, t, dt):
                return {"value": t * 2.0}

        adapter = NativeModelAdapter(
            model=MyModel(),
            model_id="my_model",
            output_names=["value"],
            sync_protocol=sync,
            store=store,
        )
    """

    def __init__(
        self,
        model: NativeModel,
        model_id: str,
        output_names: List[str],
        sync_protocol: SyncProtocol,
        store: ParameterStore,
    ) -> None:
        if not isinstance(model, NativeModel):
            raise TypeError(
                f"{type(model).__name__} does not implement the NativeModel protocol. "
                "It must have a step(t: float, dt: float) -> dict[str, float] method."
            )
        self._model = model
        self._model_id = model_id
        self._output_names = output_names
        self._sync_protocol = sync_protocol
        self._store = store

    @property
    def model_id(self) -> str:
        return self._model_id

    def initialise(self, start_time: float = 0.0) -> None:
        """No-op — NativeModelAdapter needs no initialisation."""
        logger.info(f"[{self._model_id}] NativeModelAdapter initialised")

    def on_tick(self, t: float, dt: float) -> None:
        """Step the model, write outputs to ParameterStore, acknowledge sync."""
        outputs = self._model.step(t, dt)
        stepped_t = round(t + dt, 9)

        for name, value in outputs.items():
            self._store.write(
                name=name,
                value=value,
                t=stepped_t,
                model_id=self._model_id,
            )

        logger.debug(f"[{self._model_id}] t={stepped_t:.3f} {outputs}")
        self._sync_protocol.publish_ready(model_id=self._model_id, t=t)

    def teardown(self) -> None:
        logger.info(f"[{self._model_id}] NativeModelAdapter teardown")