"""
Tests for PUS TC packet parser and builder.
Implements: SVF-DEV-037
"""

import pytest
import struct
from svf.pus.tc import (
    PusTcPacket, PusTcParser, PusTcBuilder,
    PusTcError, crc16
)


@pytest.fixture
def builder() -> PusTcBuilder:
    return PusTcBuilder()


@pytest.fixture
def parser() -> PusTcParser:
    return PusTcParser()


@pytest.fixture
def packet() -> PusTcPacket:
    return PusTcPacket(
        apid=0x100,
        sequence_count=1,
        service=20,
        subservice=1,
        source_id=0x01,
        ack_flags=0b1001,
        app_data=struct.pack(">f", 0.1),  # torque value
    )


@pytest.mark.requirement("SVF-DEV-037")
def test_build_and_parse_roundtrip(
    builder: PusTcBuilder,
    parser: PusTcParser,
    packet: PusTcPacket,
) -> None:
    """Build a TC packet and parse it back — roundtrip integrity."""
    raw = builder.build(packet)
    parsed = parser.parse(raw)

    assert parsed.apid == packet.apid
    assert parsed.sequence_count == packet.sequence_count
    assert parsed.service == packet.service
    assert parsed.subservice == packet.subservice
    assert parsed.source_id == packet.source_id
    assert parsed.ack_flags == packet.ack_flags
    assert parsed.app_data == packet.app_data


@pytest.mark.requirement("SVF-DEV-037")
def test_crc_is_appended(
    builder: PusTcBuilder,
    packet: PusTcPacket,
) -> None:
    """Built packet has valid CRC-16 in last two bytes."""
    raw = builder.build(packet)
    received_crc = struct.unpack(">H", raw[-2:])[0]
    computed_crc = crc16(raw[:-2])
    assert received_crc == computed_crc


@pytest.mark.requirement("SVF-DEV-037")
def test_invalid_crc_raises(
    builder: PusTcBuilder,
    parser: PusTcParser,
    packet: PusTcPacket,
) -> None:
    """Parsing a packet with corrupt CRC raises PusTcError."""
    raw = bytearray(builder.build(packet))
    raw[-1] ^= 0xFF  # corrupt CRC
    with pytest.raises(PusTcError, match="CRC mismatch"):
        parser.parse(bytes(raw))


@pytest.mark.requirement("SVF-DEV-037")
def test_packet_too_short_raises(parser: PusTcParser) -> None:
    """Parsing a too-short packet raises PusTcError."""
    with pytest.raises(PusTcError, match="too short"):
        parser.parse(b"\x00" * 5)


@pytest.mark.requirement("SVF-DEV-037")
def test_wrong_packet_type_raises(
    builder: PusTcBuilder,
    parser: PusTcParser,
    packet: PusTcPacket,
) -> None:
    """Parsing a TM packet as TC raises PusTcError."""
    raw = bytearray(builder.build(packet))
    # Clear packet type bit (bit 12 of word1)
    word1 = struct.unpack_from(">H", raw, 0)[0]
    word1 &= ~(1 << 12)
    struct.pack_into(">H", raw, 0, word1)
    # Fix CRC
    crc = crc16(bytes(raw[:-2]))
    struct.pack_into(">H", raw, len(raw) - 2, crc)
    with pytest.raises(PusTcError, match="Not a TC packet"):
        parser.parse(bytes(raw))


@pytest.mark.requirement("SVF-DEV-037")
def test_ack_flags(packet: PusTcPacket) -> None:
    """Ack flags are parsed correctly."""
    assert packet.ack_acceptance is True
    assert packet.ack_completion is True


@pytest.mark.requirement("SVF-DEV-037")
def test_invalid_apid_raises() -> None:
    """APID out of range raises ValueError."""
    with pytest.raises(ValueError, match="APID"):
        PusTcPacket(apid=0x800, sequence_count=1,
                    service=20, subservice=1)


@pytest.mark.requirement("SVF-DEV-037")
def test_service_20_subservice_1_with_float_payload(
    builder: PusTcBuilder,
    parser: PusTcParser,
) -> None:
    """S20 parameter set TC carries float payload correctly."""
    value = 0.15
    packet = PusTcPacket(
        apid=0x101,
        sequence_count=42,
        service=20,
        subservice=1,
        app_data=struct.pack(">Hf", 0x2021, value),  # param_id + value
    )
    raw = builder.build(packet)
    parsed = parser.parse(raw)

    param_id, parsed_value = struct.unpack_from(">Hf", parsed.app_data)
    assert param_id == 0x2021
    assert parsed_value == pytest.approx(value)
