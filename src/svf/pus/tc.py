"""
SVF PUS Telecommand (TC) Packet
CCSDS/PUS-C telecommand packet parser and builder.
Reference: ECSS-E-ST-70-41C

PUS TC Packet Structure:
  Primary Header (6 bytes):
    - Packet Version Number     (3 bits)  = 0b000
    - Packet Type               (1 bit)   = 1 (TC)
    - Data Field Header Flag    (1 bit)   = 1
    - APID                      (11 bits)
    - Sequence Flags            (2 bits)  = 0b11 (standalone)
    - Packet Sequence Count     (14 bits)
    - Packet Data Length        (16 bits) = total bytes after primary header - 1

  Data Field Header (5 bytes):
    - CCSDS Secondary Hdr Flag  (1 bit)   = 0
    - PUS Version               (3 bits)  = 0b010 (PUS-C)
    - Ack Flags                 (4 bits)  acceptance|start|progress|completion
    - Service Type              (8 bits)
    - Subservice Type           (8 bits)
    - Source ID                 (16 bits)

  Application Data: variable length

  Packet Error Control (2 bytes): CRC-16/CCITT

Implements: SVF-DEV-037
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Optional

# PUS-C version
PUS_VERSION = 0b010

# Sequence flags — standalone packet
SEQ_STANDALONE = 0b11

# CRC-16/CCITT lookup table
def _build_crc_table() -> list[int]:
    table = []
    for i in range(256):
        crc = i << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = (crc << 1) ^ 0x1021
            else:
                crc <<= 1
        table.append(crc & 0xFFFF)
    return table

_CRC_TABLE = _build_crc_table()


def crc16(data: bytes) -> int:
    """Compute CRC-16/CCITT for the given data."""
    crc = 0xFFFF
    for byte in data:
        crc = ((crc << 8) ^ _CRC_TABLE[(crc >> 8) ^ byte]) & 0xFFFF
    return crc


class PusTcError(Exception):
    """Raised when a PUS TC packet is malformed or invalid."""
    pass


@dataclass
class PusTcPacket:
    """
    A parsed PUS-C Telecommand packet.

    Attributes:
        apid:           Application Process Identifier (11-bit, 0-2047)
        sequence_count: Packet sequence count (14-bit, 0-16383)
        service:        PUS service type (1-255)
        subservice:     PUS subservice type (1-255)
        source_id:      Source identifier (16-bit)
        ack_flags:      Acknowledgement flags (4-bit)
                        bit3=acceptance, bit2=start, bit1=progress, bit0=completion
        app_data:       Application data bytes
    """
    apid: int
    sequence_count: int
    service: int
    subservice: int
    source_id: int = 0
    ack_flags: int = 0b1001  # acceptance + completion by default
    app_data: bytes = field(default_factory=bytes)

    def __post_init__(self) -> None:
        if not (0 <= self.apid <= 0x7FF):
            raise ValueError(f"APID must be 0-2047, got {self.apid}")
        if not (0 <= self.sequence_count <= 0x3FFF):
            raise ValueError(
                f"Sequence count must be 0-16383, got {self.sequence_count}"
            )
        if not (1 <= self.service <= 255):
            raise ValueError(
                f"Service must be 1-255, got {self.service}"
            )
        if not (1 <= self.subservice <= 255):
            raise ValueError(
                f"Subservice must be 1-255, got {self.subservice}"
            )

    @property
    def ack_acceptance(self) -> bool:
        return bool(self.ack_flags & 0b1000)

    @property
    def ack_completion(self) -> bool:
        return bool(self.ack_flags & 0b0001)


class PusTcParser:
    """
    Parses raw bytes into PusTcPacket objects.

    Validates:
    - Minimum packet length
    - Packet type field (must be 1 = TC)
    - Data field header flag (must be 1)
    - PUS version (must be PUS-C = 0b010)
    - CRC-16/CCITT
    """

    MIN_PACKET_LEN = 6 + 5 + 2  # primary + data field header + CRC

    def parse(self, data: bytes) -> PusTcPacket:
        """
        Parse raw bytes into a PusTcPacket.
        Raises PusTcError if the packet is malformed or CRC fails.
        """
        if len(data) < self.MIN_PACKET_LEN:
            raise PusTcError(
                f"Packet too short: {len(data)} bytes "
                f"(minimum {self.MIN_PACKET_LEN})"
            )

        # Validate CRC before parsing
        received_crc = struct.unpack_from(">H", data, len(data) - 2)[0]
        computed_crc = crc16(data[:-2])
        if received_crc != computed_crc:
            raise PusTcError(
                f"CRC mismatch: received 0x{received_crc:04X}, "
                f"computed 0x{computed_crc:04X}"
            )

        # Parse primary header (6 bytes)
        word1, word2, data_length = struct.unpack_from(">HHH", data, 0)

        version       = (word1 >> 13) & 0x07
        packet_type   = (word1 >> 12) & 0x01
        dfh_flag      = (word1 >> 11) & 0x01
        apid          = word1 & 0x7FF

        seq_flags     = (word2 >> 14) & 0x03
        sequence_count = word2 & 0x3FFF

        if packet_type != 1:
            raise PusTcError(
                f"Not a TC packet: packet_type={packet_type} (expected 1)"
            )
        if dfh_flag != 1:
            raise PusTcError(
                "Data field header flag must be 1 for PUS packets"
            )

        # Parse data field header (5 bytes)
        dfh_byte0, service, subservice, source_id = struct.unpack_from(
            ">BBBH", data, 6
        )

        pus_version = (dfh_byte0 >> 4) & 0x07
        ack_flags   = dfh_byte0 & 0x0F

        if pus_version != PUS_VERSION:
            raise PusTcError(
                f"PUS version mismatch: got {pus_version}, "
                f"expected {PUS_VERSION} (PUS-C)"
            )

        # Application data: between data field header end and CRC
        app_data = data[11:-2]

        return PusTcPacket(
            apid=apid,
            sequence_count=sequence_count,
            service=service,
            subservice=subservice,
            source_id=source_id,
            ack_flags=ack_flags,
            app_data=bytes(app_data),
        )


class PusTcBuilder:
    """
    Builds raw PUS-C TC packet bytes from a PusTcPacket.
    """

    def build(self, packet: PusTcPacket) -> bytes:
        """
        Serialise a PusTcPacket to bytes with CRC-16.
        """
        # Data field header (5 bytes)
        dfh_byte0 = (PUS_VERSION << 4) | (packet.ack_flags & 0x0F)
        dfh = struct.pack(
            ">BBBH",
            dfh_byte0,
            packet.service,
            packet.subservice,
            packet.source_id,
        )

        # Application data
        app_data = packet.app_data

        # Data length = number of bytes after primary header - 1
        data_length = len(dfh) + len(app_data) + 2 - 1  # +2 for CRC

        # Primary header (6 bytes)
        word1 = (
            (0b000 << 13) |   # version
            (1 << 12) |       # packet type = TC
            (1 << 11) |       # data field header flag
            (packet.apid & 0x7FF)
        )
        word2 = (
            (SEQ_STANDALONE << 14) |
            (packet.sequence_count & 0x3FFF)
        )
        primary = struct.pack(">HHH", word1, word2, data_length)

        # Assemble without CRC
        raw = primary + dfh + app_data

        # Append CRC
        crc = crc16(raw)
        return raw + struct.pack(">H", crc)
