"""
L1 tests for the wire protocol v4 sensor frame OBCEmulatorAdapter sends,
its refusal of an obsw_sim on another protocol, and the OBC thermal input
model that feeds the frame.

Implements: SVF-DEV-219
"""
from __future__ import annotations

import logging
import math
import struct
from unittest.mock import MagicMock

import pytest

from svf.core.equipment_fault import EquipmentFault, EquipmentFaultEngine, FaultMode
from svf.models.dhs.obc_emulator import (
    FRAME_SENSOR, WIRE_PROTOCOL_VERSION, OBCEmulatorAdapter,
)
from svf.models.dhs.obc_thermal import (
    NOMINAL_RAW, STATUS_PORT, TEMPERATURE_RAW_PORT,
    degc_to_raw, make_obc_thermal, raw_to_degc,
)
from svf.stores.parameter_store import ParameterStore

_THERMAL_OFFSET = 47          # after sim_time, where a v3 frame ended
_V4_BANNER = [
    "[OBSW] Entered SAFE mode",
    "[OBSW] Host sim started (wire protocol v4).",
    "[OBSW] openobsw v0.19.0",
    "[OBSW] SRDB version: 0.1.0",
]


def _adapter() -> tuple[OBCEmulatorAdapter, ParameterStore]:
    store = ParameterStore()
    return OBCEmulatorAdapter(sim_path=None, sync_protocol=MagicMock(), store=store), store


def _sent_frame(adapter: OBCEmulatorAdapter) -> bytes:
    written: list[tuple[int, bytes]] = []
    adapter._write_typed_frame = (  # type: ignore[method-assign]
        lambda frame_type, frame: written.append((frame_type, frame)))
    adapter._send_sensor_frame(1.5)
    assert len(written) == 1 and written[0][0] == FRAME_SENSOR
    return written[0][1]


def _thermal(frame: bytes) -> tuple[int, int]:
    raw, valid = struct.unpack_from("<hB", frame, _THERMAL_OFFSET)
    return raw, valid


@pytest.mark.requirement("SVF-DEV-219")
def test_sensor_frame_is_50_bytes_with_sim_time_before_the_thermal_fields() -> None:
    adapter, _ = _adapter()
    frame = _sent_frame(adapter)
    assert len(frame) == 50
    assert struct.unpack_from("<f", frame, 43)[0] == 1.5


@pytest.mark.requirement("SVF-DEV-219")
def test_sensor_frame_carries_thermal_input() -> None:
    adapter, store = _adapter()
    store.write(TEMPERATURE_RAW_PORT, 1300.0, t=1.0, model_id="obc_thermal")
    store.write(STATUS_PORT, 1.0, t=1.0, model_id="obc_thermal")
    assert _thermal(_sent_frame(adapter)) == (1300, 1)


@pytest.mark.requirement("SVF-DEV-219")
def test_negative_raw_value_is_sent_signed() -> None:
    """-50 degC is raw -100; openobsw types obc_temperature int16 since v0.19."""
    adapter, store = _adapter()
    store.write(TEMPERATURE_RAW_PORT, -100.0, t=1.0, model_id="obc_thermal")
    store.write(STATUS_PORT, 1.0, t=1.0, model_id="obc_thermal")
    assert _thermal(_sent_frame(adapter)) == (-100, 1)


@pytest.mark.requirement("SVF-DEV-219")
@pytest.mark.parametrize("value, sent", [
    (1299.6, 1300),
    (1e6, 32767),
    (-1e6, -32768),
])
def test_thermal_value_is_rounded_and_clamped_to_int16(value: float, sent: int) -> None:
    adapter, store = _adapter()
    store.write(TEMPERATURE_RAW_PORT, value, t=1.0, model_id="obc_thermal")
    store.write(STATUS_PORT, 1.0, t=1.0, model_id="obc_thermal")
    assert _thermal(_sent_frame(adapter)) == (sent, 1)


@pytest.mark.requirement("SVF-DEV-219")
def test_without_thermal_input_the_obsw_keeps_its_own_value() -> None:
    """thermal_valid 0: openobsw leaves obc_temperature to TC(20,1)."""
    adapter, _ = _adapter()
    assert _thermal(_sent_frame(adapter)) == (0, 0)


@pytest.mark.requirement("SVF-DEV-219")
@pytest.mark.parametrize("status", [None, 0.0])
def test_thermal_input_without_valid_status_is_invalid(status: float | None) -> None:
    adapter, store = _adapter()
    store.write(TEMPERATURE_RAW_PORT, 1300.0, t=1.0, model_id="obc_thermal")
    if status is not None:
        store.write(STATUS_PORT, status, t=1.0, model_id="obc_thermal")
    assert _thermal(_sent_frame(adapter)) == (1300, 0)


@pytest.mark.requirement("SVF-DEV-219")
def test_non_finite_thermal_value_is_invalid() -> None:
    adapter, store = _adapter()
    store.write(TEMPERATURE_RAW_PORT, math.nan, t=1.0, model_id="obc_thermal")
    store.write(STATUS_PORT, 1.0, t=1.0, model_id="obc_thermal")
    assert _thermal(_sent_frame(adapter)) == (0, 0)


@pytest.mark.requirement("SVF-DEV-219")
def test_v4_banner_is_accepted() -> None:
    adapter, _ = _adapter()
    assert WIRE_PROTOCOL_VERSION == 4
    adapter._check_wire_protocol(_V4_BANNER)


@pytest.mark.requirement("SVF-DEV-219")
@pytest.mark.parametrize("banner, named", [
    ("[OBSW] Host sim started (type-frame protocol v2).", "an older wire protocol"),
    ("[OBSW] Host sim started.", "an older wire protocol"),
    ("[OBSW] Host sim started (wire protocol v3).", "wire protocol v3"),
    ("[OBSW] Host sim started (wire protocol v5).", "wire protocol v5"),
])
def test_obsw_sim_on_another_protocol_is_refused(banner: str, named: str) -> None:
    """openobsw v0.18 prints 'type-frame protocol v2' and expects 47-byte frames."""
    adapter, _ = _adapter()
    with pytest.raises(RuntimeError, match=named):
        adapter._check_wire_protocol(["[OBSW] Entered SAFE mode", banner])


@pytest.mark.requirement("SVF-DEV-219")
def test_missing_banner_is_a_warning(caplog: pytest.LogCaptureFixture) -> None:
    adapter, _ = _adapter()
    with caplog.at_level(logging.WARNING):
        adapter._check_wire_protocol([])
    assert "wire protocol version not checked" in caplog.text


@pytest.mark.requirement("SVF-DEV-219")
def test_raw_conversion_is_the_openobsw_srdb_one() -> None:
    """parameters.yaml obc_temperature: degC = 0.1 * raw - 40; 85 degC = 1250."""
    assert raw_to_degc(1250.0) == pytest.approx(85.0)
    assert degc_to_raw(25.0) == pytest.approx(NOMINAL_RAW)
    assert raw_to_degc(degc_to_raw(-50.0)) == pytest.approx(-50.0)


@pytest.mark.requirement("SVF-DEV-219")
def test_obc_thermal_writes_a_valid_nominal_value() -> None:
    store = ParameterStore()
    eq = make_obc_thermal(MagicMock(), store)
    eq.on_tick(0.0, 0.1)
    raw, status = store.read(TEMPERATURE_RAW_PORT), store.read(STATUS_PORT)
    assert raw is not None and raw.value == NOMINAL_RAW
    assert status is not None and status.value == 1.0


@pytest.mark.requirement("SVF-DEV-219")
def test_obc_thermal_fault_is_applied_and_cleared() -> None:
    """The procedure path: a stuck fault raises the value, clearing restores it."""
    store = ParameterStore()
    eq = make_obc_thermal(MagicMock(), store)
    engine = EquipmentFaultEngine("obc_thermal")
    eq.attach_fault_engine(engine)

    engine.inject(EquipmentFault(TEMPERATURE_RAW_PORT, FaultMode.STUCK, 1300.0, 0.0, 0.0))
    eq.on_tick(0.0, 0.1)
    entry = store.read(TEMPERATURE_RAW_PORT)
    assert entry is not None and entry.value == 1300.0

    engine.clear()
    eq.on_tick(0.1, 0.1)
    entry = store.read(TEMPERATURE_RAW_PORT)
    assert entry is not None and entry.value == NOMINAL_RAW


@pytest.mark.requirement("SVF-DEV-219")
def test_obc_thermal_fail_fault_invalidates_the_reading() -> None:
    store = ParameterStore()
    eq = make_obc_thermal(MagicMock(), store)
    engine = EquipmentFaultEngine("obc_thermal")
    eq.attach_fault_engine(engine)
    engine.inject(EquipmentFault(STATUS_PORT, FaultMode.FAIL, 0.0, 0.0, 0.0))
    eq.on_tick(0.0, 0.1)
    entry = store.read(STATUS_PORT)
    assert entry is not None and entry.value == 0.0


@pytest.mark.requirement("SVF-DEV-219")
def test_spacecraft_yaml_model_obc_thermal_builds_the_model() -> None:
    """`model: obc_thermal` in spacecraft.yaml resolves to make_obc_thermal."""
    from svf.config.spacecraft import SpacecraftLoader
    from svf.stores.command_store import CommandStore
    eq = SpacecraftLoader._build_equipment(
        "obc_thermal", "obc_thermal", None, None,
        MagicMock(), ParameterStore(), CommandStore())
    assert eq.equipment_id == "obc_thermal"
    assert {p.name for p in eq.out_ports()} == {TEMPERATURE_RAW_PORT, STATUS_PORT}
