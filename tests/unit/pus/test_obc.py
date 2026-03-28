"""
Tests for OBC Equipment as PUS TC router.
Implements: PUS-010, 1553-010
"""

import pytest
import struct
from svf.abstractions import SyncProtocol
from svf.parameter_store import ParameterStore
from svf.command_store import CommandStore
from svf.models.obc import ObcEquipment, ObcConfig
from svf.models.ttc import TtcEquipment
from svf.pus.tc import PusTcPacket, PusTcBuilder
from svf.pus.services import HkReportDefinition


class _NoSync(SyncProtocol):
    def reset(self) -> None: pass
    def publish_ready(self, model_id: str, t: float) -> None: pass
    def wait_for_ready(self, expected: list[str], timeout: float) -> bool:
        return True


@pytest.fixture
def sync() -> _NoSync:
    return _NoSync()


@pytest.fixture
def store() -> ParameterStore:
    return ParameterStore()


@pytest.fixture
def cmd_store() -> CommandStore:
    return CommandStore()


@pytest.fixture
def obc(
    sync: _NoSync, store: ParameterStore, cmd_store: CommandStore
) -> ObcEquipment:
    config = ObcConfig(
        apid=0x101,
        param_id_map={
            0x2021: "aocs.rw1.torque_cmd",
            0x2022: "aocs.rw1.speed",
        },
    )
    eq = ObcEquipment(config, sync, store, cmd_store)
    eq.initialise()
    return eq


@pytest.fixture
def ttc(
    obc: ObcEquipment,
    sync: _NoSync,
    store: ParameterStore,
    cmd_store: CommandStore,
) -> TtcEquipment:
    eq = TtcEquipment(obc, sync, store, cmd_store)
    eq.initialise()
    return eq


# ── S17 are-you-alive tests ───────────────────────────────────────────────────

@pytest.mark.requirement("PUS-010")
def test_obc_responds_to_are_you_alive(obc: ObcEquipment) -> None:
    """OBC generates TM(17,2) in response to TC(17,1)."""
    tc = PusTcPacket(apid=0x100, sequence_count=1, service=17, subservice=1)
    raw = PusTcBuilder().build(tc)
    responses = obc.receive_tc(raw, t=0.0)

    tm_17 = [r for r in responses if r.service == 17 and r.subservice == 2]
    assert len(tm_17) == 1


@pytest.mark.requirement("PUS-009", "PUS-010")
def test_obc_generates_s1_acceptance_and_completion(
    obc: ObcEquipment,
) -> None:
    """OBC generates TM(1,1) and TM(1,7) for any valid TC."""
    tc = PusTcPacket(apid=0x100, sequence_count=1, service=17, subservice=1)
    raw = PusTcBuilder().build(tc)
    responses = obc.receive_tc(raw, t=0.0)

    subservices = [r.subservice for r in responses if r.service == 1]
    assert 1 in subservices  # TM(1,1) acceptance
    assert 7 in subservices  # TM(1,7) completion


@pytest.mark.requirement("PUS-009", "PUS-010")
def test_obc_generates_s1_failure_on_bad_crc(obc: ObcEquipment) -> None:
    """OBC generates TM(1,2) when TC has invalid CRC."""
    raw = bytearray(PusTcBuilder().build(
        PusTcPacket(apid=0x100, sequence_count=1, service=17, subservice=1)
    ))
    raw[-1] ^= 0xFF  # corrupt CRC
    responses = obc.receive_tc(bytes(raw), t=0.0)

    tm_1_2 = [r for r in responses if r.service == 1 and r.subservice == 2]
    assert len(tm_1_2) == 1


# ── S20 parameter management tests ───────────────────────────────────────────

@pytest.mark.requirement("PUS-010", "PUS-008")
def test_obc_s20_set_injects_into_command_store(
    obc: ObcEquipment, cmd_store: CommandStore
) -> None:
    """OBC routes S20 set TC to CommandStore using SRDB canonical name."""
    tc = PusTcPacket(
        apid=0x100, sequence_count=2,
        service=20, subservice=1,
        app_data=struct.pack(">Hf", 0x2021, 0.15),
    )
    raw = PusTcBuilder().build(tc)
    obc.receive_tc(raw, t=0.0)

    entry = cmd_store.peek("aocs.rw1.torque_cmd")
    assert entry is not None
    assert entry.value == pytest.approx(0.15, abs=1e-5)


@pytest.mark.requirement("PUS-010", "PUS-008")
def test_obc_s20_get_returns_tm_20_4(
    obc: ObcEquipment, store: ParameterStore
) -> None:
    """OBC responds to S20 get with TM(20,4) containing current value."""
    store.write("aocs.rw1.speed", 1500.0, t=0.0, model_id="rw1")

    tc = PusTcPacket(
        apid=0x100, sequence_count=3,
        service=20, subservice=3,
        app_data=struct.pack(">H", 0x2022),
    )
    raw = PusTcBuilder().build(tc)
    responses = obc.receive_tc(raw, t=0.0)

    tm_20_4 = [r for r in responses if r.service == 20 and r.subservice == 4]
    assert len(tm_20_4) == 1
    param_id, value = struct.unpack_from(">Hf", tm_20_4[0].app_data)
    assert param_id == 0x2022
    assert value == pytest.approx(1500.0, abs=0.1)


# ── S3 housekeeping tests ─────────────────────────────────────────────────────

@pytest.mark.requirement("PUS-005", "PUS-010")
def test_obc_essential_hk_auto_enabled(
    sync: _NoSync, store: ParameterStore, cmd_store: CommandStore
) -> None:
    """Essential HK reports are enabled automatically at initialise()."""
    config = ObcConfig(
        apid=0x101,
        essential_hk=[
            HkReportDefinition(
                report_id=0,
                parameter_names=["eps.battery.soc"],
                period_s=1.0,
            )
        ],
    )
    obc = ObcEquipment(config, sync, store, cmd_store)
    obc.initialise()

    assert obc._s3._definitions[0].enabled is True


@pytest.mark.requirement("PUS-005", "PUS-010")
def test_obc_generates_hk_report_on_step(
    sync: _NoSync, store: ParameterStore, cmd_store: CommandStore
) -> None:
    """OBC generates TM(3,25) on each tick for enabled HK reports."""
    config = ObcConfig(
        apid=0x101,
        essential_hk=[
            HkReportDefinition(
                report_id=0,
                parameter_names=["eps.battery.soc"],
                period_s=1.0,
            )
        ],
    )
    obc = ObcEquipment(config, sync, store, cmd_store)
    obc.initialise()
    store.write("eps.battery.soc", 0.87, t=0.0, model_id="eps")

    obc.do_step(t=0.0, dt=1.0)

    tm_3_25 = obc.get_tm_by_service(3, 25)
    assert len(tm_3_25) > 0


# ── TTC tests ─────────────────────────────────────────────────────────────────

@pytest.mark.requirement("PUS-011")
def test_ttc_forwards_tc_to_obc(
    ttc: TtcEquipment, cmd_store: CommandStore
) -> None:
    """TTC forwards TC to OBC which routes it to CommandStore."""
    tc = PusTcPacket(
        apid=0x100, sequence_count=1,
        service=20, subservice=1,
        app_data=struct.pack(">Hf", 0x2021, 0.1),
    )
    ttc.send_tc(tc)
    ttc.do_step(t=0.0, dt=0.1)

    entry = cmd_store.peek("aocs.rw1.torque_cmd")
    assert entry is not None
    assert entry.value == pytest.approx(0.1, abs=1e-5)


@pytest.mark.requirement("PUS-011")
def test_ttc_are_you_alive_roundtrip(ttc: TtcEquipment) -> None:
    """Full TC(17,1) -> TTC -> OBC -> TM(17,2) roundtrip."""
    tc = PusTcPacket(
        apid=0x100, sequence_count=1,
        service=17, subservice=1,
    )
    ttc.send_tc(tc)
    ttc.do_step(t=0.0, dt=0.1)

    responses = ttc.get_tm_responses(service=17, subservice=2)
    assert len(responses) == 1
    assert responses[0].service == 17
    assert responses[0].subservice == 2
