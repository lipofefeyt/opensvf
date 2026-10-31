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
    """Build a TM packet and parse it back  -  roundtrip integrity."""
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


# ── Optional Packet Error Control (SVF-DEV-205) ──────────────────────────────

@pytest.mark.requirement("SVF-DEV-205")
def test_parse_without_pec_keeps_full_app_data(
    builder: PusTmBuilder, packet: PusTmPacket
) -> None:
    """With pec=False the last two bytes are application data, not a CRC."""
    raw = builder.build(packet)[:-2]          # strip the CRC: a PEC-less packet
    parsed = PusTmParser(pec=False).parse(raw)
    assert parsed.service == packet.service
    assert parsed.subservice == packet.subservice
    assert parsed.app_data == packet.app_data


@pytest.mark.requirement("SVF-DEV-205")
def test_pec_less_packet_fails_default_parser(
    builder: PusTmBuilder, packet: PusTmPacket
) -> None:
    """The default parser still demands a valid CRC."""
    raw = builder.build(packet)[:-2]
    with pytest.raises(PusTmError):
        PusTmParser().parse(raw)


@pytest.mark.requirement("SVF-DEV-205")
def test_openobsw_hk_packet_parses_without_pec() -> None:
    """A TM(3,25) set 3 packet as emitted by openobsw v0.18 (no PEC)."""
    raw = bytes.fromhex(
        "0903c00000162003190000000000000000"   # primary (len 22) + PUS-C secondary
        "03" "01" "000003e8" "00" "00" "01" "0000" "05"  # set 3: SAFE, OBT 1000
    )
    pkt = PusTmParser(pec=False).parse(raw)
    assert (pkt.service, pkt.subservice) == (3, 25)
    assert pkt.app_data[0] == 3
    mode, obt = struct.unpack_from(">BI", pkt.app_data, 1)
    assert (mode, obt) == (1, 1000)
