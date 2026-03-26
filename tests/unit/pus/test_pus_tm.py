"""
Tests for PUS TM packet builder and parser.
Implements: SVF-DEV-037
"""

import pytest
import struct
from svf.pus.tm import PusTmPacket, PusTmBuilder, PusTmParser, PusTmError
from svf.pus.tc import crc16


@pytest.fixture
def builder() -> PusTmBuilder:
    return PusTmBuilder()


@pytest.fixture
def parser() -> PusTmParser:
    return PusTmParser()


@pytest.fixture
def packet() -> PusTmPacket:
    return PusTmPacket(
        apid=0x100,
        sequence_count=1,
        service=3,
        subservice=25,
        message_counter=1,
        destination_id=0x01,
        timestamp=1000,
        app_data=struct.pack(">f", 3.85),  # battery voltage
    )


@pytest.mark.requirement("SVF-DEV-037")
def test_build_and_parse_roundtrip(
    builder: PusTmBuilder,
    parser: PusTmParser,
    packet: PusTmPacket,
) -> None:
    """Build a TM packet and parse it back — roundtrip integrity."""
    raw = builder.build(packet)
    parsed = parser.parse(raw)

    assert parsed.apid == packet.apid
    assert parsed.sequence_count == packet.sequence_count
    assert parsed.service == packet.service
    assert parsed.subservice == packet.subservice
    assert parsed.message_counter == packet.message_counter
    assert parsed.destination_id == packet.destination_id
    assert parsed.timestamp == packet.timestamp
    assert parsed.app_data == packet.app_data


@pytest.mark.requirement("SVF-DEV-037")
def test_crc_appended(builder: PusTmBuilder, packet: PusTmPacket) -> None:
    """Built TM packet has valid CRC."""
    raw = builder.build(packet)
    received = struct.unpack(">H", raw[-2:])[0]
    computed = crc16(raw[:-2])
    assert received == computed


@pytest.mark.requirement("SVF-DEV-037")
def test_invalid_crc_raises(
    builder: PusTmBuilder,
    parser: PusTmParser,
    packet: PusTmPacket,
) -> None:
    """Parsing TM with corrupt CRC raises PusTmError."""
    raw = bytearray(builder.build(packet))
    raw[-1] ^= 0xFF
    with pytest.raises(PusTmError, match="CRC mismatch"):
        parser.parse(bytes(raw))


@pytest.mark.requirement("SVF-DEV-037")
def test_packet_too_short_raises(parser: PusTmParser) -> None:
    """Parsing too-short TM packet raises PusTmError."""
    with pytest.raises(PusTmError, match="too short"):
        parser.parse(b"\x00" * 10)


@pytest.mark.requirement("SVF-DEV-037")
def test_s3_hk_report_payload(
    builder: PusTmBuilder,
    parser: PusTmParser,
) -> None:
    """S3 HK report TM carries parameter values correctly."""
    soc = 0.87
    voltage = 3.95
    packet = PusTmPacket(
        apid=0x100,
        sequence_count=5,
        service=3,
        subservice=25,
        app_data=struct.pack(">ff", soc, voltage),
    )
    raw = builder.build(packet)
    parsed = parser.parse(raw)
    parsed_soc, parsed_voltage = struct.unpack_from(">ff", parsed.app_data)
    assert parsed_soc == pytest.approx(soc)
    assert parsed_voltage == pytest.approx(voltage)
