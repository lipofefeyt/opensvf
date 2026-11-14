"""
L1 tests for TM(3,25) housekeeping set layouts in the SRDB: the definitions,
SrdbLoader.load_hk_sets() and the layouts shipped with opensvf.

Implements: SVF-DEV-217
"""
from __future__ import annotations

import struct
from pathlib import Path

import pytest

from svf.srdb.definitions import HkParameter, HkSetDefinition, HkWireType
from svf.srdb.loader import (
    BUNDLED_HK_SETS,
    SrdbLoader,
    SrdbLoadError,
    load_bundled_hk_sets,
)

_YAML = """\
hk_sets:
  - id: 1
    name: nominal_hk
    description: "thermal, power, uptime"
    parameters:
      - {key: dhs.obc.obc_temperature, obsw: obc_temperature, type: int16, unit: raw}
      - {key: dhs.obc.obc_voltage_3v3, obsw: obc_voltage_3v3, type: uint16, unit: mV}
      - {key: dhs.obc.obc_uptime, obsw: obc_uptime, type: uint32, unit: s}
  - id: 4
    name: aocs_hk
    parameters:
      - {key: dhs.obc.bdot_gain, obsw: bdot_gain, type: float32}
"""


def _write(tmp_path: Path, text: str, name: str = "hk_sets.yaml") -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def _load_error(tmp_path: Path, text: str) -> str:
    with pytest.raises(SrdbLoadError) as exc:
        SrdbLoader().load_hk_sets(_write(tmp_path, text))
    return str(exc.value)


# ── Definitions ──────────────────────────────────────────────────────────────

@pytest.mark.requirement("SVF-DEV-217")
@pytest.mark.parametrize("wire_type, size", [
    (HkWireType.UINT8, 1), (HkWireType.INT8, 1),
    (HkWireType.UINT16, 2), (HkWireType.INT16, 2),
    (HkWireType.UINT32, 4), (HkWireType.INT32, 4),
    (HkWireType.FLOAT32, 4), (HkWireType.FLOAT64, 8),
])
def test_wire_type_sizes(wire_type: HkWireType, size: int) -> None:
    assert wire_type.size == size


@pytest.mark.requirement("SVF-DEV-217")
def test_set_decodes_big_endian_signed_and_float() -> None:
    hk_set = HkSetDefinition(set_id=9, name="mixed", parameters=(
        HkParameter("dhs.obc.t", "t", HkWireType.INT16),
        HkParameter("dhs.obc.v", "v", HkWireType.UINT16),
        HkParameter("dhs.obc.n", "n", HkWireType.UINT32),
        HkParameter("dhs.obc.g", "g", HkWireType.FLOAT32),
        HkParameter("dhs.obc.f", "f", HkWireType.UINT8),
    ))
    assert hk_set.sizes == (2, 2, 4, 4, 1)
    assert hk_set.data_len == 13
    data = bytes([0xAA]) + struct.pack(">hHIfB", -100, 3300, 1000, 1.5, 7)
    assert hk_set.decode(data, offset=1) == (-100, 3300, 1000, 1.5, 7)
    # Read little-endian by mistake, 1000 would come out as 3892510720.
    assert hk_set.decode(data, 1)[2] != struct.unpack_from("<I", data, 5)[0]


@pytest.mark.requirement("SVF-DEV-217")
def test_decode_of_a_short_report_raises() -> None:
    hk_set = HkSetDefinition(1, "s", (HkParameter("dhs.obc.n", "n", HkWireType.UINT32),))
    with pytest.raises(struct.error):
        hk_set.decode(b"\x00\x01\x02")


@pytest.mark.requirement("SVF-DEV-217")
def test_invalid_definitions_are_rejected() -> None:
    p = HkParameter("dhs.obc.n", "n", HkWireType.UINT8)
    with pytest.raises(ValueError, match="domain.subsystem.parameter"):
        HkParameter("obc_temperature", "obc_temperature", HkWireType.INT16)
    with pytest.raises(ValueError, match="no parameters"):
        HkSetDefinition(1, "empty", ())
    with pytest.raises(ValueError, match="0-255"):
        HkSetDefinition(256, "big", (p,))
    with pytest.raises(ValueError, match="more than once"):
        HkSetDefinition(1, "dup", (p, p))


# ── Loader ───────────────────────────────────────────────────────────────────

@pytest.mark.requirement("SVF-DEV-217")
def test_loader_reads_sets_in_report_order(tmp_path: Path) -> None:
    loader = SrdbLoader()
    sets = loader.load_hk_sets(_write(tmp_path, _YAML))
    assert sorted(sets) == [1, 4]
    nominal = sets[1]
    assert (nominal.name, nominal.description) == ("nominal_hk", "thermal, power, uptime")
    assert [p.name for p in nominal.parameters] == [
        "dhs.obc.obc_temperature", "dhs.obc.obc_voltage_3v3", "dhs.obc.obc_uptime"]
    assert [p.obsw_name for p in nominal.parameters] == [
        "obc_temperature", "obc_voltage_3v3", "obc_uptime"]
    assert nominal.parameters[0].wire_type is HkWireType.INT16
    assert nominal.parameters[0].unit == "raw"
    assert nominal.sizes == (2, 2, 4)
    assert sets[4].sizes == (4,)


@pytest.mark.requirement("SVF-DEV-217")
def test_loaded_sets_are_part_of_the_built_srdb(tmp_path: Path) -> None:
    loader = SrdbLoader()
    loader.load_hk_sets(_write(tmp_path, _YAML))
    srdb = loader.build()
    assert sorted(srdb.hk_sets) == [1, 4]
    hk_set = srdb.hk_set(4)
    assert hk_set is not None and hk_set.name == "aocs_hk"
    assert srdb.hk_set(3) is None
    assert SrdbLoader().build().hk_sets == {}


@pytest.mark.requirement("SVF-DEV-217")
def test_same_set_id_in_two_files_is_rejected(tmp_path: Path) -> None:
    loader = SrdbLoader()
    loader.load_hk_sets(_write(tmp_path, _YAML))
    with pytest.raises(SrdbLoadError, match="duplicate housekeeping set ID 1"):
        loader.load_hk_sets(_write(tmp_path, _YAML, "mission_hk.yaml"))


@pytest.mark.requirement("SVF-DEV-217")
@pytest.mark.parametrize("text, message", [
    ("parameters: {}\n", "'hk_sets' key must be a list"),
    ("hk_sets:\n  - {name: a, parameters: []}\n", "missing required field 'id'"),
    ("hk_sets:\n  - {id: one, name: a, parameters: []}\n", "id must be an integer"),
    ("hk_sets:\n  - {id: 1, name: a, parameters: {}}\n", "'parameters' must be a list"),
    ("hk_sets:\n  - {id: 1, name: a, parameters: []}\n", "has no parameters"),
    ("hk_sets:\n  - {id: 1, name: a, parameters: [{key: dhs.obc.x, type: uint8}]}\n",
     "needs 'key', 'obsw' and 'type'"),
    ("hk_sets:\n  - {id: 1, name: a, parameters: [{key: dhs.obc.x, obsw: x, type: uint24}]}\n",
     "invalid type 'uint24'"),
    ("hk_sets:\n  - {id: 1, name: a, parameters: [{key: x, obsw: x, type: uint8}]}\n",
     "domain.subsystem.parameter"),
    ("hk_sets:\n  - {id: 1, name: a, parameters: [{key: dhs.obc.x, obsw: x, type: uint8}]}\n"
     "  - {id: 1, name: b, parameters: [{key: dhs.obc.y, obsw: y, type: uint8}]}\n",
     "duplicate housekeeping set ID 1"),
])
def test_loader_rejects_malformed_files(tmp_path: Path, text: str, message: str) -> None:
    assert message in _load_error(tmp_path, text)


# ── Layouts shipped with opensvf ─────────────────────────────────────────────

@pytest.mark.requirement("SVF-DEV-217")
def test_bundled_layouts_are_the_openobsw_sets() -> None:
    """Sizes as openobsw v0.18 generates them in SRDB_HK_<SET>_SIZES."""
    assert BUNDLED_HK_SETS.exists()
    sets = load_bundled_hk_sets()
    assert {i: (s.name, s.sizes) for i, s in sets.items()} == {
        1: ("nominal_hk",    (2, 2, 2, 4)),
        2: ("fdir_hk",       (2, 4, 4)),
        3: ("dhs_obc_hk",    (1, 4, 1, 1, 1, 2, 1)),
        4: ("aocs_hk",       (4, 4, 4)),
        5: ("aocs_orbit_hk", (4, 4, 4, 4, 4, 4)),
        6: ("aocs_state_hk", (4, 4, 1)),
        7: ("aocs_bdot_hk",  (4, 4, 4, 4, 4, 4, 1)),
    }
    assert [p.name for p in sets[1].parameters] == [
        "dhs.obc.obc_temperature", "dhs.obc.obc_voltage_3v3",
        "dhs.obc.obc_voltage_5v", "dhs.obc.obc_uptime"]
    assert sets[1].parameters[0].wire_type is HkWireType.INT16


@pytest.mark.requirement("SVF-DEV-217")
def test_bundled_keys_are_dhs_obc_plus_the_openobsw_name() -> None:
    for hk_set in load_bundled_hk_sets().values():
        for p in hk_set.parameters:
            assert p.name == f"dhs.obc.{p.obsw_name}"


@pytest.mark.requirement("SVF-DEV-217")
def test_bundled_layouts_are_read_only_and_cached() -> None:
    sets = load_bundled_hk_sets()
    assert load_bundled_hk_sets() is sets
    with pytest.raises(TypeError):
        sets[99] = sets[1]  # type: ignore[index]
