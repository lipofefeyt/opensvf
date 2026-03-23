"""
SVF NativeModelAdapter
Wraps a plain Python class as a ModelAdapter.
Publishes telemetry to DDS and acknowledges sync after each tick.
Implements: SVF-DEV-015
"""

import logging
from typing import Protocol, runtime_checkable, List

from cyclonedds.domain import DomainParticipant
from cyclonedds.topic import Topic
from cyclonedds.pub import Publisher, DataWriter
from cyclonedds.core import Qos, Policy

from svf.abstractions import ModelAdapter, SyncProtocol
from svf.fmu_adapter import TelemetrySample

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
            participant=participant,
            sync_protocol=sync,
        )
    """

    TOPIC_PREFIX = "SVF/Telemetry/"

    def __init__(
        self,
        model: NativeModel,
        model_id: str,
        output_names: List[str],
        participant: DomainParticipant,
        sync_protocol: SyncProtocol,
    ) -> None:
        if not isinstance(model, NativeModel):
            raise TypeError(
                f"{type(model).__name__} does not implement the NativeModel protocol. "
                "It must have a step(t: float, dt: float) -> dict[str, float] method."
            )
        self._model = model
        self._model_id = model_id
        self._output_names = output_names
        self._participant = participant
        self._sync_protocol = sync_protocol
        self._writers: dict[str, DataWriter[TelemetrySample]] = {}

    @property
    def model_id(self) -> str:
        return self._model_id

    def initialise(self, start_time: float = 0.0) -> None:
        """Create DDS writers for each declared output variable."""
        publisher = Publisher(self._participant)
        qos = Qos(Policy.History.KeepAll)
        for name in self._output_names:
            topic = Topic(
                self._participant,
                f"{self.TOPIC_PREFIX}{name}",
                TelemetrySample,
            )
            self._writers[name] = DataWriter(publisher, topic, qos=qos)
        logger.info(f"[{self._model_id}] NativeModelAdapter initialised")

    def on_tick(self, t: float, dt: float) -> None:
        """Step the model, publish telemetry, acknowledge sync."""
        outputs = self._model.step(t, dt)
        stepped_t = round(t + dt, 9)

        for name, value in outputs.items():
            if name in self._writers:
                self._writers[name].write(TelemetrySample(
                    model_id=self._model_id,
                    variable=name,
                    t=stepped_t,
                    value=value,
                ))

        logger.debug(f"[{self._model_id}] t={stepped_t:.3f} {outputs}")
        self._sync_protocol.publish_ready(model_id=self._model_id, t=t)

    def teardown(self) -> None:
        logger.info(f"[{self._model_id}] NativeModelAdapter teardown")