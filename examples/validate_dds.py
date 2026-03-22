"""
SVF - Cyclone DDS validation script
Publishes and subscribes to a local DDS topic in a single process.
Closes: #17 (M2 spike)
Implements: SVF-DEV-010
"""

from dataclasses import dataclass
import time

from cyclonedds.domain import DomainParticipant
from cyclonedds.topic import Topic
from cyclonedds.pub import Publisher, DataWriter
from cyclonedds.sub import Subscriber, DataReader
from cyclonedds.core import Qos, Policy
from cyclonedds.idl import IdlStruct
from cyclonedds.idl.annotations import key


@dataclass
class HelloMessage(IdlStruct, typename="HelloMessage"):
    message: str
    value: float


def main() -> None:
    print("Cyclone DDS hello-world validation")
    print("-" * 40)

    # Create a domain participant — the entry point for all DDS communication
    participant = DomainParticipant()

    # Define a topic — the named channel messages flow through
    topic = Topic(participant, "SVFHello", HelloMessage)

    # Publisher side
    publisher = Publisher(participant)
    writer = DataWriter(publisher, topic)

    # Subscriber side
    subscriber = Subscriber(participant)
    reader = DataReader(subscriber, topic)

    # Give DDS a moment to discover the local reader/writer
    time.sleep(0.1)

    # Publish a message
    msg = HelloMessage(message="SVF DDS is alive", value=42.0)
    writer.write(msg)
    print(f"Published:  message='{msg.message}', value={msg.value}")

    # Give the message time to arrive
    time.sleep(0.1)

    # Read it back
    samples = reader.take()
    if samples:
        for sample in samples:
            print(f"Received:   message='{sample.message}', value={sample.value}")
        print("\nValidation complete - Cyclone DDS is working correctly.")
    else:
        print("\nNo messages received - something went wrong.")


if __name__ == "__main__":
    main()