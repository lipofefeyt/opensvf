"""
SVF DdsSyncProtocol
Tick acknowledgements over Cyclone DDS topics.
Implements: SVF-DEV-012, SVF-DEV-020, SVF-DEV-021, SVF-DEV-022, SVF-DEV-023
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from cyclonedds.domain import DomainParticipant
from cyclonedds.topic import Topic
from cyclonedds.pub import Publisher, DataWriter
from cyclonedds.sub import Subscriber, DataReader
from cyclonedds.idl import IdlStruct

from svf.abstractions import SyncProtocol

logger = logging.getLogger(__name__)


@dataclass
class SimReady(IdlStruct, typename="SimReady"):
    """Acknowledgement published by a model when it finishes processing a tick."""
    model_id: str
    t: float


class DdsSyncProtocol(SyncProtocol):
    """
    Exchanges tick acknowledgements over DDS.

    Each model publishes a SimReady message on SVF/Sim/Ready when it
    finishes processing a tick. The master reads all SimReady messages
    and blocks until all expected models have acknowledged.
    """

    TOPIC_NAME = "SVF/Sim/Ready"

    def __init__(self, participant: DomainParticipant) -> None:
        self._participant = participant
        self._pending: set[str] = set()

        publisher = Publisher(participant)
        subscriber = Subscriber(participant)
        topic = Topic(participant, self.TOPIC_NAME, SimReady)

        self._writer = DataWriter(publisher, topic)
        self._reader = DataReader(subscriber, topic)

        # Allow DDS discovery to settle
        time.sleep(0.05)
        logger.info("DdsSyncProtocol initialised")

    def reset(self) -> None:
        """Drain any leftover acknowledgements from the previous tick."""
        self._reader.take()
        self._pending.clear()

    def publish_ready(self, model_id: str, t: float) -> None:
        """Publish a readiness acknowledgement for this model and time."""
        self._writer.write(SimReady(model_id=model_id, t=t))
        logger.debug(f"Ready published: model={model_id} t={t:.3f}")

    def wait_for_ready(self, expected: list[str], timeout: float) -> bool:
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