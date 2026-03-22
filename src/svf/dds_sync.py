"""
SVF DdsSyncProtocol
Tick acknowledgements over Cyclone DDS topics.
Implements: SVF-DEV-012, SVF-DEV-020, SVF-DEV-021, SVF-DEV-022, SVF-DEV-023
"""

import logging
import time
from dataclasses import dataclass
from typing import List

from cyclonedds.domain import DomainParticipant
from cyclonedds.topic import Topic
from cyclonedds.pub import Publisher, DataWriter
from cyclonedds.sub import Subscriber, DataReader
from cyclonedds.core import Qos, Policy
from cyclonedds.idl import IdlStruct
from cyclonedds.idl.types import bounded_str

from svf.abstractions import SyncProtocol

logger = logging.getLogger(__name__)


@dataclass
class SimReady(IdlStruct, typename="SimReady"):
    """Acknowledgement published by a model when it finishes processing a tick."""
    model_id: bounded_str(256)  # type: ignore[valid-type]
    t: float


class DdsSyncProtocol(SyncProtocol):
    """
    Exchanges tick acknowledgements over DDS.

    Uses KEEP_ALL QoS to ensure no acknowledgement is lost when multiple
    models publish to the same topic in quick succession.
    """

    TOPIC_NAME = "SVF/Sim/Ready"

    def __init__(self, participant: DomainParticipant) -> None:
        self._participant = participant

        # KEEP_ALL ensures no ack is dropped when multiple models
        # publish to the same topic before wait_for_ready reads them
        qos = Qos(Policy.History.KeepAll)

        publisher = Publisher(participant)
        subscriber = Subscriber(participant)
        topic = Topic(participant, self.TOPIC_NAME, SimReady)

        self._writer = DataWriter(publisher, topic, qos=qos)
        self._reader = DataReader(subscriber, topic, qos=qos)

        # Allow DDS discovery to settle
        time.sleep(0.05)
        logger.info("DdsSyncProtocol initialised")

    def reset(self) -> None:
        """Drain any leftover acknowledgements from the previous tick."""
        self._reader.take()

    def publish_ready(self, model_id: str, t: float) -> None:
        """Publish a readiness acknowledgement for this model and time."""
        self._writer.write(SimReady(model_id=model_id, t=t))
        logger.debug(f"Ready published: model={model_id} t={t:.3f}")

    def wait_for_ready(self, expected: List[str], timeout: float) -> bool:
        """
        Block until all expected models have published SimReady for this tick.
        Returns True if all acknowledged within timeout, False otherwise.
        """
        remaining = set(expected)
        deadline = time.monotonic() + timeout

        while remaining and time.monotonic() < deadline:
            samples = self._reader.take()
            for sample in samples:
                if sample.model_id in remaining:
                    remaining.discard(sample.model_id)
                    logger.debug(f"Ack received: model={sample.model_id} t={sample.t:.3f}")
            if remaining:
                time.sleep(0.001)

        if remaining:
            logger.warning(f"Timeout waiting for models: {remaining}")
            return False

        return True