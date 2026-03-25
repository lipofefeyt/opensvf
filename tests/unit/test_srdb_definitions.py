"""
Tests for SRDB ParameterDefinition schema.
Implements: SVF-DEV-090
"""

import pytest
from svf.srdb.definitions import (
    Classification, Domain, Dtype,
    PusMapping, ParameterDefinition,
)


# ── PusMapping tests ──────────────────────────────────────────────────────────

@pytest.mark.requirement("SVF-DEV-090")
def test_pus_mapping_valid() -> None:
    """PusMapping constructs correctly with valid values."""
    pus = PusMapping(apid=0x100, service=3, subservice=25, parameter_id=0x0042)
    assert pus.apid == 0x100
    assert pus.service == 3
    assert pus.subservice == 25
    assert pus.parameter_id == 0x0042


@pytest.mark.requirement("SVF-DEV-090")
def test_pus_mapping_invalid_apid() -> None:
    """APID must be within 11-bit range."""
    with pytest.raises(ValueError, match="APID"):
        PusMapping(apid=0x800, service=3, subservice=25, parameter_id=1)


@pytest.mark.requirement("SVF-DEV-090")
def test_pus_mapping_invalid_service() -> None:
    """PUS service must be 0-255."""
    with pytest.raises(ValueError, match="service"):
        PusMapping(apid=0x100, service=256, subservice=25, parameter_id=1)


@pytest.mark.requirement("SVF-DEV-090")
def test_pus_mapping_frozen() -> None:
    """PusMapping is immutable."""
    pus = PusMapping(apid=0x100, service=3, subservice=25, parameter_id=1)
    with pytest.raises(Exception):
        pus.apid = 0x200  # type: ignore[misc]


# ── ParameterDefinition tests ─────────────────────────────────────────────────

@pytest.mark.requirement("SVF-DEV-090")
def test_parameter_definition_tm() -> None:
    """TM parameter constructs correctly."""
    param = ParameterDefinition(
        name="eps.battery.soc",
        description="Battery state of charge",
        unit="",
        dtype=Dtype.FLOAT,
        classification=Classification.TM,
        domain=Domain.EPS,
        model_id="eps",
        valid_range=(0.05, 1.0),
        pus=PusMapping(apid=0x100, service=3, subservice=25, parameter_id=0x0042),
    )
    assert param.name == "eps.battery.soc"
    assert param.classification == Classification.TM
    assert param.domain == Domain.EPS
    assert param.valid_range == (0.05, 1.0)


@pytest.mark.requirement("SVF-DEV-090")
def test_parameter_definition_tc() -> None:
    """TC parameter constructs correctly."""
    param = ParameterDefinition(
        name="eps.solar_illumination",
        description="Solar illumination fraction",
        unit="",
        dtype=Dtype.FLOAT,
        classification=Classification.TC,
        domain=Domain.EPS,
        model_id="eps",
        valid_range=(0.0, 1.0),
    )
    assert param.classification == Classification.TC
    assert param.pus is None


@pytest.mark.requirement("SVF-DEV-090")
def test_parameter_definition_no_range() -> None:
    """Parameter without valid_range is always in range."""
    param = ParameterDefinition(
        name="obdh.mode",
        description="OBC operating mode",
        unit="",
        dtype=Dtype.INT,
        classification=Classification.TM,
        domain=Domain.OBDH,
        model_id="obdh",
    )
    assert param.valid_range is None
    assert param.is_in_range(999.0) is True


@pytest.mark.requirement("SVF-DEV-090")
def test_parameter_is_in_range() -> None:
    """is_in_range() returns correct results."""
    param = ParameterDefinition(
        name="eps.battery.soc",
        description="Battery SoC",
        unit="",
        dtype=Dtype.FLOAT,
        classification=Classification.TM,
        domain=Domain.EPS,
        model_id="eps",
        valid_range=(0.05, 1.0),
    )
    assert param.is_in_range(0.5) is True
    assert param.is_in_range(0.05) is True
    assert param.is_in_range(1.0) is True
    assert param.is_in_range(0.04) is False
    assert param.is_in_range(1.01) is False


@pytest.mark.requirement("SVF-DEV-090")
def test_parameter_empty_name_raises() -> None:
    """Empty name raises ValueError."""
    with pytest.raises(ValueError, match="name cannot be empty"):
        ParameterDefinition(
            name="",
            description="test",
            unit="",
            dtype=Dtype.FLOAT,
            classification=Classification.TM,
            domain=Domain.EPS,
            model_id="eps",
        )


@pytest.mark.requirement("SVF-DEV-090")
def test_parameter_invalid_range_raises() -> None:
    """valid_range with min >= max raises ValueError."""
    with pytest.raises(ValueError, match="valid_range"):
        ParameterDefinition(
            name="eps.battery.soc",
            description="test",
            unit="",
            dtype=Dtype.FLOAT,
            classification=Classification.TM,
            domain=Domain.EPS,
            model_id="eps",
            valid_range=(1.0, 0.0),
        )


@pytest.mark.requirement("SVF-DEV-090")
def test_parameter_frozen() -> None:
    """ParameterDefinition is immutable."""
    param = ParameterDefinition(
        name="eps.battery.soc",
        description="test",
        unit="",
        dtype=Dtype.FLOAT,
        classification=Classification.TM,
        domain=Domain.EPS,
        model_id="eps",
    )
    with pytest.raises(Exception):
        param.name = "changed"  # type: ignore[misc]


@pytest.mark.requirement("SVF-DEV-090")
def test_parameter_str() -> None:
    """__str__ produces readable output."""
    param = ParameterDefinition(
        name="eps.battery.soc",
        description="Battery SoC",
        unit="",
        dtype=Dtype.FLOAT,
        classification=Classification.TM,
        domain=Domain.EPS,
        model_id="eps",
        valid_range=(0.05, 1.0),
    )
    s = str(param)
    assert "eps.battery.soc" in s
    assert "TM" in s
    assert "EPS" in s
