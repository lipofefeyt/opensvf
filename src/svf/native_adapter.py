"""
SVF NativeModelAdapter
Wraps a plain Python class as a ModelAdapter.
Useful for lightweight unit test models that don't need a full FMU.
Implements: SVF-DEV-015
"""

from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable

from svf.abstractions import ModelAdapter

logger = logging.getLogger(__name__)


@runtime_checkable
class NativeModel(Protocol):
    """
    Protocol that a plain Python class must satisfy to be wrapped
    by NativeModelAdapter. No inheritance required.
    """

    def step(self, t: float, dt: float) -> dict[str, float]:
        """Advance the model and return output values."""
        ...


class NativeModelAdapter(ModelAdapter):
    """
    Wraps a plain Python class implementing the NativeModel protocol.

    Usage:
        class MyModel:
            def step(self, t, dt):
                return {"value": t * 2.0}

        adapter = NativeModelAdapter(model=MyModel(), model_id="my_model")
        adapter.initialise()
        outputs = adapter.on_tick(t=0.0, dt=0.1)
    """

    def __init__(self, model: NativeModel, model_id: str) -> None:
        if not isinstance(model, NativeModel):
            raise TypeError(
                f"{type(model).__name__} does not implement the NativeModel protocol. "
                "It must have a step(t: float, dt: float) -> dict[str, float] method."
            )
        self._model = model
        self._model_id = model_id

    @property
    def model_id(self) -> str:
        return self._model_id

    def initialise(self, start_time: float = 0.0) -> None:
        logger.info(f"[{self._model_id}] NativeModelAdapter initialised")

    def on_tick(self, t: float, dt: float) -> dict[str, float]:
        outputs = self._model.step(t, dt)
        logger.debug(f"[{self._model_id}] t={t + dt:.3f} {outputs}")
        return outputs

    def teardown(self) -> None:
        logger.info(f"[{self._model_id}] NativeModelAdapter teardown")