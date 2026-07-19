"""
Tests for OBC Equipment S15 On-Board Storage/Retrieval and S23 File Management dispatch.
Implements: SVF-DEV-188, SVF-DEV-189
"""

import pytest
from svf.core.abstractions import SyncProtocol
from svf.stores.parameter_store import ParameterStore
from svf.stores.command_store import CommandStore
from svf.models.dhs.obc import ObcEquipment, ObcConfig
from svf.pus.tc import PusTcPacket, PusTcBuilder
from svf.pus.services import PusService15, PusService23


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
def obc(sync: _NoSync, store: ParameterStore, cmd_store: CommandStore) -> ObcEquipment:
    config = ObcConfig(apid=0x101)
    eq = ObcEquipment(config, sync, store, cmd_store)
    eq.initialise()
    return eq


def _ping_tc(seq: int) -> bytes:
    """A TC(17,1) are-you-alive  -  convenient trigger for a TM round-trip."""
    tc = PusTcPacket(apid=0x100, sequence_count=seq, service=17, subservice=1)
    return PusTcBuilder().build(tc)


def _s15_tc(seq: int, subservice: int, app_data: bytes) -> bytes:
    tc = PusTcPacket(apid=0x100, sequence_count=seq, service=15, subservice=subservice, app_data=app_data)
    return PusTcBuilder().build(tc)


def _s23_tc(seq: int, subservice: int, app_data: bytes) -> bytes:
    tc = PusTcPacket(apid=0x100, sequence_count=seq, service=23, subservice=subservice, app_data=app_data)
    return PusTcBuilder().build(tc)


# ── S15 on-board storage/retrieval dispatch tests ─────────────────────────────

@pytest.mark.requirement("PUS-010", "SVF-DEV-188")
def test_obc_s15_enable_then_new_tm_gets_buffered(obc: ObcEquipment) -> None:
    """Once a store is enabled, subsequent TM generation is buffered into it."""
    obc.receive_tc(_s15_tc(1, 1, PusService15.build_enable(store_id=1)), t=0.0)
    obc.receive_tc(_ping_tc(2), t=0.0)

    responses = obc.receive_tc(
        _s15_tc(3, 3, PusService15.build_retrieve(store_id=1, start_time=0, end_time=1000)),
        t=0.0,
    )
    tm_17_2 = [r for r in responses if r.service == 17 and r.subservice == 2]
    assert len(tm_17_2) == 1


@pytest.mark.requirement("PUS-010", "SVF-DEV-188")
def test_obc_s15_disabled_store_does_not_buffer(obc: ObcEquipment) -> None:
    """TM generated while a store is disabled is not retrievable from it."""
    obc.receive_tc(_s15_tc(1, 1, PusService15.build_enable(store_id=1)), t=0.0)
    obc.receive_tc(_s15_tc(2, 2, PusService15.build_disable(store_id=1)), t=0.0)
    obc.receive_tc(_ping_tc(3), t=0.0)

    responses = obc.receive_tc(
        _s15_tc(4, 3, PusService15.build_retrieve(store_id=1, start_time=0, end_time=1000)),
        t=0.0,
    )
    tm_17_2 = [r for r in responses if r.service == 17 and r.subservice == 2]
    assert len(tm_17_2) == 0


@pytest.mark.requirement("PUS-010", "SVF-DEV-188")
def test_obc_s15_retrieve_filters_by_time_range(obc: ObcEquipment) -> None:
    """Only packets buffered within [start_time, end_time] are retrieved."""
    obc.receive_tc(_s15_tc(1, 1, PusService15.build_enable(store_id=1)), t=0.0)

    obc.do_step(t=0.0, dt=10.0)  # obt -> 10.0
    obc.receive_tc(_ping_tc(2), t=0.0)  # buffered at obt=10

    obc.do_step(t=10.0, dt=100.0)  # obt -> 110.0
    obc.receive_tc(_ping_tc(3), t=10.0)  # buffered at obt=110

    # Retrieve only the early window - should get exactly one TM(17,2).
    responses = obc.receive_tc(
        _s15_tc(4, 3, PusService15.build_retrieve(store_id=1, start_time=0, end_time=50)),
        t=10.0,
    )
    tm_17_2 = [r for r in responses if r.service == 17 and r.subservice == 2]
    assert len(tm_17_2) == 1


@pytest.mark.requirement("PUS-010", "SVF-DEV-188")
def test_obc_s15_delete_removes_packets_in_range(obc: ObcEquipment) -> None:
    """TC(15,9) delete removes buffered packets within the given time range."""
    obc.receive_tc(_s15_tc(1, 1, PusService15.build_enable(store_id=1)), t=0.0)
    obc.receive_tc(_ping_tc(2), t=0.0)

    obc.receive_tc(_s15_tc(3, 9, PusService15.build_delete(store_id=1, start_time=0, end_time=1000)), t=0.0)

    responses = obc.receive_tc(
        _s15_tc(4, 3, PusService15.build_retrieve(store_id=1, start_time=0, end_time=1000)),
        t=0.0,
    )
    tm_17_2 = [r for r in responses if r.service == 17 and r.subservice == 2]
    assert len(tm_17_2) == 0


@pytest.mark.requirement("PUS-010", "SVF-DEV-188")
def test_obc_s15_repeated_retrieve_does_not_duplicate(obc: ObcEquipment) -> None:
    """Retrieving twice must not re-buffer the retrieved packets into the store."""
    obc.receive_tc(_s15_tc(1, 1, PusService15.build_enable(store_id=1)), t=0.0)
    obc.receive_tc(_ping_tc(2), t=0.0)

    retrieve = _s15_tc(3, 3, PusService15.build_retrieve(store_id=1, start_time=0, end_time=1000))
    obc.receive_tc(retrieve, t=0.0)
    responses = obc.receive_tc(retrieve, t=0.0)

    tm_17_2 = [r for r in responses if r.service == 17 and r.subservice == 2]
    assert len(tm_17_2) == 1  # still just the one originally-buffered packet


@pytest.mark.requirement("PUS-010", "SVF-DEV-188")
def test_obc_s15_retrieve_unknown_store_returns_empty(obc: ObcEquipment) -> None:
    responses = obc.receive_tc(
        _s15_tc(1, 3, PusService15.build_retrieve(store_id=99, start_time=0, end_time=1000)),
        t=0.0,
    )
    tm_17_2 = [r for r in responses if r.service == 17]
    assert len(tm_17_2) == 0


# ── S23 file management dispatch tests ────────────────────────────────────────

@pytest.mark.requirement("PUS-010", "SVF-DEV-189")
def test_obc_s23_create_then_report_attributes(obc: ObcEquipment) -> None:
    obc.receive_tc(_s23_tc(1, 1, PusService23.build_create("boot.log", size=2048)), t=0.0)

    responses = obc.receive_tc(
        _s23_tc(2, 3, PusService23.build_report_attributes("boot.log")), t=0.0,
    )
    tm_23_4 = [r for r in responses if r.service == 23 and r.subservice == 4]
    assert len(tm_23_4) == 1
    name_len = tm_23_4[0].app_data[0]
    name = tm_23_4[0].app_data[1:1 + name_len].decode("ascii")
    assert name == "boot.log"


@pytest.mark.requirement("PUS-010", "SVF-DEV-189")
def test_obc_s23_delete_then_report_attributes_returns_nothing(obc: ObcEquipment) -> None:
    obc.receive_tc(_s23_tc(1, 1, PusService23.build_create("boot.log")), t=0.0)
    obc.receive_tc(_s23_tc(2, 2, PusService23.build_delete("boot.log")), t=0.0)

    responses = obc.receive_tc(
        _s23_tc(3, 3, PusService23.build_report_attributes("boot.log")), t=0.0,
    )
    tm_23_4 = [r for r in responses if r.service == 23 and r.subservice == 4]
    assert len(tm_23_4) == 0


@pytest.mark.requirement("PUS-010", "SVF-DEV-189")
def test_obc_s23_report_attributes_unknown_file_returns_nothing(obc: ObcEquipment) -> None:
    responses = obc.receive_tc(
        _s23_tc(1, 3, PusService23.build_report_attributes("missing.bin")), t=0.0,
    )
    tm_23_4 = [r for r in responses if r.service == 23]
    assert len(tm_23_4) == 0
