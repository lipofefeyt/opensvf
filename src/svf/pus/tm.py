"""
SVF PUS Telemetry (TM) Packet
CCSDS/PUS-C telemetry packet builder and parser.
Reference: ECSS-E-ST-70-41C

PUS TM Packet Structure:
  Primary Header (6 bytes):
    - Packet Version Number     (3 bits)  = 0b000
    - Packet Type               (1 bit)   = 0 (TM)
    - Data Field Header Flag    (1 bit)   = 1
    - APID                      (11 bits)
    - Sequence Flags            (2 bits)  = 0b11
    - Packet Sequence Count     (14 bits)
    - Packet Data Length        (16 bits)

  Data Field Header (10 bytes):
    - CCSDS Secondary Hdr Flag  (1 bit)   = 0
    - PUS Version               (3 bits)  = 0b010
    - Spacecraft Time Ref       (4 bits)
    - Service Type              (8 bits)
    - Subservice Type           (8 bits)
    - Message Counter           (16 bits)
    - Destination ID            (16 bits)
    - Time                      (32 bits) CUC timestamp

  Application Data: variable length
  Packet Error Control (2 bytes): CRC-16/CCITT

Implements: SVF-DEV-037
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

from svf.pus.tc import PUS_VERSION, SEQ_STANDALONE, crc16, PusTcError


class PusTmError(Exception):
    """Raised when a PUS TM packet is malformed."""
    pass


@dataclass
class PusTmPacket:
    """
    A PUS-C Telemetry packet.

    Attributes:
        apid:            Application Process Identifier (11-bit)
        sequence_count:  Packet sequence count (14-bit)
        service:         PUS service type
        subservice:      PUS subservice type
        message_counter: Message counter (16-bit)
        destination_id:  Destination identifier (16-bit)
        timestamp:       CUC timestamp (32-bit, seconds since epoch)
        app_data:        Application data bytes
    """
    apid: int
    sequence_count: int
    service: int
    subservice: int
    message_counter: int = 0
    destination_id: int = 0
    timestamp: int = 0
    app_data: bytes = field(default_factory=bytes)

    def __post_init__(self) -> None:
        if not (0 <= self.apid <= 0x7FF):
            raise ValueError(f"APID must be 0-2047, got {self.apid}")
        if not (1 <= self.service <= 255):
            raise ValueError(f"Service must be 1-255, got {self.service}")
        if not (1 <= self.subservice <= 255):
            raise ValueError(
                f"Subservice must be 1-255, got {self.subservice}"
            )


class PusTmBuilder:
    """Builds raw PUS-C TM packet bytes."""

    def build(self, packet: PusTmPacket) -> bytes:
        """Serialise a PusTmPacket to bytes with CRC-16."""
        # Data field header (10 bytes)
        dfh_byte0 = (PUS_VERSION << 4) & 0xFF
        dfh = struct.pack(
            ">BBBHHI",
            dfh_byte0,
            packet.service,
            packet.subservice,
            packet.message_counter,
            packet.destination_id,
            packet.timestamp,
        )

        app_data = packet.app_data
        data_length = len(dfh) + len(app_data) + 2 - 1

        word1 = (
            (0b000 << 13) |
            (0 << 12) |       # packet type = TM
            (1 << 11) |       # data field header flag
            (packet.apid & 0x7FF)
        )
        word2 = (
            (SEQ_STANDALONE << 14) |
            (packet.sequence_count & 0x3FFF)
        )
        primary = struct.pack(">HHH", word1, word2, data_length)
        raw = primary + dfh + app_data
        crc = crc16(raw)
        return raw + struct.pack(">H", crc)


class PusTmParser:
    """Parses raw bytes into PusTmPacket objects."""

    MIN_PACKET_LEN = 6 + 10 + 2  # primary + dfh + CRC

    def parse(self, data: bytes) -> PusTmPacket:
        """Parse raw bytes into a PusTmPacket. Validates CRC."""
        if len(data) < self.MIN_PACKET_LEN:
            raise PusTmError(
                f"TM packet too short: {len(data)} bytes "
                f"(minimum {self.MIN_PACKET_LEN})"
            )

        received_crc = struct.unpack_from(">H", data, len(data) - 2)[0]
        computed_crc = crc16(data[:-2])
        if received_crc != computed_crc:
            raise PusTmError(
                f"CRC mismatch: received 0x{received_crc:04X}, "
                f"computed 0x{computed_crc:04X}"
            )

        word1, word2, data_length = struct.unpack_from(">HHH", data, 0)
        apid = word1 & 0x7FF
        sequence_count = word2 & 0x3FFF

        dfh_byte0, service, subservice, msg_counter, dest_id, timestamp = \
            struct.unpack_from(">BBBHHI", data, 6)

        app_data = data[17:-2]

        return PusTmPacket(
            apid=apid,
            sequence_count=sequence_count,
            service=service,
            subservice=subservice,
            message_counter=msg_counter,
            destination_id=dest_id,
            timestamp=timestamp,
            app_data=bytes(app_data),
        )
