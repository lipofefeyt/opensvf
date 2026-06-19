"""
Unit tests for SpacecraftValidator  -  pre-flight configuration check.
Implements: SVF-DEV-152, SVF-DEV-153
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from svf.config.validator import SpacecraftValidator, ValidationFailed, ValidationIssue


# ── helpers ───────────────────────────────────────────────────────────────────

def _errors(issues: list[ValidationIssue]) -> list[ValidationIssue]:
    return [i for i in issues if i.severity == "error"]


def _codes(issues: list[ValidationIssue]) -> list[str]:
    return [i.code for i in issues]


def _validate(cfg: dict) -> list[ValidationIssue]:
    return SpacecraftValidator()._run(cfg, Path("."))


_MINIMAL_CFG: dict = {
    "spacecraft": "TestSat",
    "equipment": [{"id": "mag1", "model": "magnetometer"}],
    "simulation": {"dt": 0.1, "stop_time": 10.0},
}


# ── clean config ──────────────────────────────────────────────────────────────

@pytest.mark.requirement("SVF-DEV-152")
def test_clean_config_no_issues() -> None:
    issues = _validate(_MINIMAL_CFG)
    assert issues == []


# ── duplicate equipment IDs ───────────────────────────────────────────────────

@pytest.mark.requirement("SVF-DEV-152")
def test_duplicate_equipment_id_raises_error() -> None:
    cfg = {
        "spacecraft": "TestSat",
        "equipment": [
            {"id": "rw1", "model": "reaction_wheel"},
            {"id": "rw1", "model": "reaction_wheel"},
        ],
    }
    issues = _validate(cfg)
    assert any(i.code == "DUPLICATE_EQUIPMENT_ID" for i in _errors(issues))


@pytest.mark.requirement("SVF-DEV-152")
def test_duplicate_equipment_id_message_contains_id() -> None:
    cfg = {
        "spacecraft": "TestSat",
        "equipment": [
            {"id": "gyro1", "model": "gyroscope"},
            {"id": "gyro1", "model": "gyroscope"},
        ],
    }
    issues = _validate(cfg)
    dup = next(i for i in issues if i.code == "DUPLICATE_EQUIPMENT_ID")
    assert "gyro1" in dup.message


@pytest.mark.requirement("SVF-DEV-152")
def test_unique_equipment_ids_no_error() -> None:
    cfg = {
        "spacecraft": "TestSat",
        "equipment": [
            {"id": "rw1", "model": "reaction_wheel"},
            {"id": "rw2", "model": "reaction_wheel"},
            {"id": "mag1", "model": "magnetometer"},
        ],
    }
    issues = _validate(cfg)
    assert not any(i.code == "DUPLICATE_EQUIPMENT_ID" for i in issues)


# ── CAN bus address conflicts ─────────────────────────────────────────────────

@pytest.mark.requirement("SVF-DEV-153")
def test_can_duplicate_id_raises_error() -> None:
    cfg = {
        "spacecraft": "TestSat",
        "equipment": [{"id": "mag1", "model": "magnetometer"}],
        "buses": [{
            "id": "aocs_can",
            "type": "can",
            "messages": [
                {"can_id": 0x100, "parameter": "aocs.mag1.field_x",
                 "direction": "TM", "node_id": "mag1", "dlc": 4},
                {"can_id": 0x100, "parameter": "aocs.mag1.field_y",
                 "direction": "TM", "node_id": "mag1", "dlc": 4},
            ],
        }],
    }
    issues = _validate(cfg)
    errors = _errors(issues)
    assert any(i.code == "BUS_ADDRESS_CONFLICT" for i in errors)


@pytest.mark.requirement("SVF-DEV-153")
def test_can_duplicate_message_contains_bus_and_id() -> None:
    cfg = {
        "spacecraft": "TestSat",
        "equipment": [{"id": "mag1", "model": "magnetometer"}],
        "buses": [{
            "id": "eps_can",
            "type": "can",
            "messages": [
                {"can_id": 0x201, "parameter": "eps.battery.soc",
                 "direction": "TM", "node_id": "bat1", "dlc": 4},
                {"can_id": 0x201, "parameter": "eps.battery.voltage",
                 "direction": "TM", "node_id": "bat1", "dlc": 4},
            ],
        }],
    }
    issues = _validate(cfg)
    conflict = next(i for i in issues if i.code == "BUS_ADDRESS_CONFLICT")
    assert "eps_can" in conflict.message
    assert "0x201" in conflict.message


@pytest.mark.requirement("SVF-DEV-153")
def test_can_unique_ids_no_error() -> None:
    cfg = {
        "spacecraft": "TestSat",
        "equipment": [{"id": "mag1", "model": "magnetometer"}],
        "buses": [{
            "id": "aocs_can",
            "type": "can",
            "messages": [
                {"can_id": 0x100, "parameter": "aocs.mag1.field_x",
                 "direction": "TM", "node_id": "mag1", "dlc": 4},
                {"can_id": 0x101, "parameter": "aocs.mag1.field_y",
                 "direction": "TM", "node_id": "mag1", "dlc": 4},
            ],
        }],
    }
    issues = _validate(cfg)
    assert not any(i.code == "BUS_ADDRESS_CONFLICT" for i in issues)


# ── SpaceWire logical address conflicts ───────────────────────────────────────

@pytest.mark.requirement("SVF-DEV-153")
def test_spw_duplicate_logical_address_raises_error() -> None:
    cfg = {
        "spacecraft": "TestSat",
        "equipment": [{"id": "mag1", "model": "magnetometer"}],
        "buses": [{
            "id": "obdh_spw",
            "type": "spacewire",
            "nodes": [
                {"logical_address": 0x20, "node_id": "obc"},
                {"logical_address": 0x20, "node_id": "dpu"},
            ],
            "mappings": [],
        }],
    }
    issues = _validate(cfg)
    assert any(i.code == "BUS_ADDRESS_CONFLICT" for i in _errors(issues))


@pytest.mark.requirement("SVF-DEV-153")
def test_spw_duplicate_message_mentions_address_and_bus() -> None:
    cfg = {
        "spacecraft": "TestSat",
        "equipment": [{"id": "mag1", "model": "magnetometer"}],
        "buses": [{
            "id": "payload_spw",
            "type": "spacewire",
            "nodes": [
                {"logical_address": 0x40, "node_id": "sensor_a"},
                {"logical_address": 0x40, "node_id": "sensor_b"},
            ],
            "mappings": [],
        }],
    }
    issues = _validate(cfg)
    conflict = next(i for i in issues if i.code == "BUS_ADDRESS_CONFLICT")
    assert "payload_spw" in conflict.message
    assert "0x40" in conflict.message


@pytest.mark.requirement("SVF-DEV-153")
def test_spw_unique_addresses_no_error() -> None:
    cfg = {
        "spacecraft": "TestSat",
        "equipment": [{"id": "mag1", "model": "magnetometer"}],
        "buses": [{
            "id": "obdh_spw",
            "type": "spacewire",
            "nodes": [
                {"logical_address": 0x20, "node_id": "obc"},
                {"logical_address": 0x30, "node_id": "dpu"},
            ],
            "mappings": [],
        }],
    }
    issues = _validate(cfg)
    assert not any(i.code == "BUS_ADDRESS_CONFLICT" for i in issues)


# ── MIL-STD-1553 RT/SA conflicts ─────────────────────────────────────────────

@pytest.mark.requirement("SVF-DEV-153")
def test_1553_duplicate_rt_sa_raises_error() -> None:
    cfg = {
        "spacecraft": "TestSat",
        "equipment": [{"id": "rw1", "model": "reaction_wheel"}],
        "buses": [{
            "id": "aocs_bus",
            "type": "mil1553",
            "rt_count": 8,
            "mappings": [
                {"rt": 5, "sa": 1, "parameter": "aocs.rw1.torque_cmd",
                 "direction": "BC_to_RT"},
                {"rt": 5, "sa": 1, "parameter": "aocs.rw1.speed_cmd",
                 "direction": "BC_to_RT"},
            ],
        }],
    }
    issues = _validate(cfg)
    assert any(i.code == "BUS_ADDRESS_CONFLICT" for i in _errors(issues))


@pytest.mark.requirement("SVF-DEV-153")
def test_1553_duplicate_message_mentions_rt_sa() -> None:
    cfg = {
        "spacecraft": "TestSat",
        "equipment": [{"id": "rw1", "model": "reaction_wheel"}],
        "buses": [{
            "id": "aocs_bus",
            "type": "mil1553",
            "rt_count": 8,
            "mappings": [
                {"rt": 3, "sa": 2, "parameter": "aocs.rw1.speed",
                 "direction": "RT_to_BC"},
                {"rt": 3, "sa": 2, "parameter": "aocs.rw1.torque",
                 "direction": "RT_to_BC"},
            ],
        }],
    }
    issues = _validate(cfg)
    conflict = next(i for i in issues if i.code == "BUS_ADDRESS_CONFLICT")
    assert "RT=3" in conflict.message
    assert "SA=2" in conflict.message


@pytest.mark.requirement("SVF-DEV-153")
def test_1553_unique_rt_sa_no_error() -> None:
    cfg = {
        "spacecraft": "TestSat",
        "equipment": [{"id": "rw1", "model": "reaction_wheel"}],
        "buses": [{
            "id": "aocs_bus",
            "type": "mil1553",
            "rt_count": 8,
            "mappings": [
                {"rt": 5, "sa": 1, "parameter": "aocs.rw1.torque_cmd",
                 "direction": "BC_to_RT"},
                {"rt": 5, "sa": 2, "parameter": "aocs.rw1.speed",
                 "direction": "RT_to_BC"},
            ],
        }],
    }
    issues = _validate(cfg)
    assert not any(i.code == "BUS_ADDRESS_CONFLICT" for i in issues)


# ── wiring override references ────────────────────────────────────────────────

@pytest.mark.requirement("SVF-DEV-152")
def test_wiring_override_unknown_from_equipment() -> None:
    cfg = {
        "spacecraft": "TestSat",
        "equipment": [{"id": "mag1", "model": "magnetometer"}],
        "wiring": {
            "auto": False,
            "overrides": [
                {"from": "ghost_sensor.field_x", "to": "mag1.field_x"}
            ],
        },
    }
    issues = _validate(cfg)
    assert any(i.code == "UNKNOWN_EQUIPMENT_REF" for i in _errors(issues))


@pytest.mark.requirement("SVF-DEV-152")
def test_wiring_override_unknown_to_equipment() -> None:
    cfg = {
        "spacecraft": "TestSat",
        "equipment": [{"id": "mag1", "model": "magnetometer"}],
        "wiring": {
            "auto": False,
            "overrides": [
                {"from": "mag1.field_x", "to": "ghost_obc.mag1.field_x"}
            ],
        },
    }
    issues = _validate(cfg)
    assert any(i.code == "UNKNOWN_EQUIPMENT_REF" for i in _errors(issues))


@pytest.mark.requirement("SVF-DEV-152")
def test_wiring_override_valid_references_no_error() -> None:
    cfg = {
        "spacecraft": "TestSat",
        "equipment": [
            {"id": "mag1", "model": "magnetometer"},
            {"id": "obc", "model": "magnetometer"},  # id matters, not model
        ],
        "wiring": {
            "auto": False,
            "overrides": [
                {"from": "mag1.field_x", "to": "obc.mag1.field_x"}
            ],
        },
    }
    issues = _validate(cfg)
    assert not any(i.code == "UNKNOWN_EQUIPMENT_REF" for i in issues)


@pytest.mark.requirement("SVF-DEV-152")
def test_wiring_override_bus_id_is_valid_reference() -> None:
    cfg = {
        "spacecraft": "TestSat",
        "equipment": [{"id": "rw1", "model": "reaction_wheel"}],
        "buses": [{"id": "aocs_bus", "type": "mil1553", "rt_count": 4,
                   "mappings": []}],
        "wiring": {
            "auto": False,
            "overrides": [
                {"from": "aocs_bus.aocs.rw1.speed", "to": "rw1.speed"}
            ],
        },
    }
    issues = _validate(cfg)
    assert not any(i.code == "UNKNOWN_EQUIPMENT_REF" for i in issues)


# ── OBT parameter file ────────────────────────────────────────────────────────

@pytest.mark.requirement("SVF-DEV-152")
def test_obt_param_file_missing_raises_error(tmp_path: Path) -> None:
    cfg = {
        "spacecraft": "TestSat",
        "equipment": [{"id": "mag1", "model": "magnetometer"}],
        "simulation": {"dt": 0.1, "stop_time": 10.0,
                       "obt_init_file": "nonexistent.tsv"},
    }
    issues = SpacecraftValidator()._run(cfg, tmp_path)
    assert any(i.code == "FILE_NOT_FOUND" for i in _errors(issues))


@pytest.mark.requirement("SVF-DEV-152")
def test_obt_param_file_malformed_raises_error(tmp_path: Path) -> None:
    bad_file = tmp_path / "init.tsv"
    bad_file.write_text("0.0\teps.battery.soc\tnot_a_number\n")
    cfg = {
        "spacecraft": "TestSat",
        "equipment": [{"id": "mag1", "model": "magnetometer"}],
        "simulation": {"dt": 0.1, "stop_time": 10.0,
                       "obt_init_file": "init.tsv"},
    }
    issues = SpacecraftValidator()._run(cfg, tmp_path)
    assert any(i.code == "OBT_PARAM_FILE_INVALID" for i in _errors(issues))


@pytest.mark.requirement("SVF-DEV-152")
def test_obt_param_file_valid_no_error(tmp_path: Path) -> None:
    good_file = tmp_path / "init.tsv"
    good_file.write_text(
        "# initial state\n"
        "0.0\teps.battery.soc\t0.85\n"
        "0.0\taocs.rw1.speed_rpm\t3200.0\n"
    )
    cfg = {
        "spacecraft": "TestSat",
        "equipment": [{"id": "mag1", "model": "magnetometer"}],
        "simulation": {"dt": 0.1, "stop_time": 10.0,
                       "obt_init_file": "init.tsv"},
    }
    issues = SpacecraftValidator()._run(cfg, tmp_path)
    assert not any(i.code in ("FILE_NOT_FOUND", "OBT_PARAM_FILE_INVALID")
                   for i in issues)


# ── ValidationFailed exception ────────────────────────────────────────────────

@pytest.mark.requirement("SVF-DEV-152")
def test_validate_or_raise_raises_on_errors(tmp_path: Path) -> None:
    bad_yaml = tmp_path / "spacecraft.yaml"
    bad_yaml.write_text(
        "spacecraft: TestSat\n"
        "equipment:\n"
        "  - id: mag1\n"
        "    model: magnetometer\n"
        "  - id: mag1\n"
        "    model: magnetometer\n"
    )
    with pytest.raises(ValidationFailed) as exc_info:
        SpacecraftValidator.validate_or_raise(bad_yaml)
    assert exc_info.value.issues
    assert any(i.code == "DUPLICATE_EQUIPMENT_ID" for i in exc_info.value.issues)


@pytest.mark.requirement("SVF-DEV-152")
def test_validate_or_raise_passes_on_clean_config(tmp_path: Path) -> None:
    good_yaml = tmp_path / "spacecraft.yaml"
    good_yaml.write_text(
        "spacecraft: TestSat\n"
        "equipment:\n"
        "  - id: mag1\n"
        "    model: magnetometer\n"
        "simulation:\n"
        "  dt: 0.1\n"
        "  stop_time: 10.0\n"
    )
    SpacecraftValidator.validate_or_raise(good_yaml)  # must not raise


# ── multiple errors reported together ────────────────────────────────────────

@pytest.mark.requirement("SVF-DEV-152")
def test_multiple_errors_all_reported() -> None:
    cfg = {
        "spacecraft": "TestSat",
        "equipment": [
            {"id": "rw1", "model": "reaction_wheel"},
            {"id": "rw1", "model": "reaction_wheel"},  # duplicate
        ],
        "buses": [{
            "id": "aocs_can",
            "type": "can",
            "messages": [
                {"can_id": 0x100, "parameter": "aocs.rw1.speed",
                 "direction": "TM", "node_id": "rw1", "dlc": 4},
                {"can_id": 0x100, "parameter": "aocs.rw1.torque",
                 "direction": "TM", "node_id": "rw1", "dlc": 4},
            ],
        }],
    }
    issues = _validate(cfg)
    codes = _codes(_errors(issues))
    assert "DUPLICATE_EQUIPMENT_ID" in codes
    assert "BUS_ADDRESS_CONFLICT" in codes
