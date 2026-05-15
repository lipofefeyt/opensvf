"""
Unit tests for SRDB raw-to-engineering calibration.
Implements: SVF-DEV-096
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from svf.srdb.definitions import CalibrationCurve, Classification, Domain, Dtype, ParameterDefinition
from svf.srdb.loader import SrdbLoadError, SrdbLoader


# ── CalibrationCurve construction ─────────────────────────────────────────────

@pytest.mark.requirement("SVF-DEV-096")
def test_polynomial_apply_constant() -> None:
    """Single-coefficient polynomial returns that constant for any raw value."""
    cal = CalibrationCurve(type="polynomial", coefficients=(5.0,))
    assert cal.apply(0.0) == pytest.approx(5.0)
    assert cal.apply(100.0) == pytest.approx(5.0)


@pytest.mark.requirement("SVF-DEV-096")
def test_polynomial_apply_linear() -> None:
    """Linear polynomial: eng = offset + scale * raw."""
    cal = CalibrationCurve(type="polynomial", coefficients=(0.0, 0.00488))
    assert cal.apply(0.0) == pytest.approx(0.0)
    assert cal.apply(2048.0) == pytest.approx(9.99424)
    assert cal.apply(4095.0) == pytest.approx(19.9836)


@pytest.mark.requirement("SVF-DEV-096")
def test_polynomial_apply_quadratic() -> None:
    """Quadratic polynomial: eng = a0 + a1*x + a2*x^2."""
    cal = CalibrationCurve(type="polynomial", coefficients=(1.0, 2.0, 0.5))
    # 1.0 + 2.0*3 + 0.5*9 = 1 + 6 + 4.5 = 11.5
    assert cal.apply(3.0) == pytest.approx(11.5)


@pytest.mark.requirement("SVF-DEV-096")
def test_table_apply_exact_breakpoint() -> None:
    """Table calibration returns exact value at a breakpoint."""
    cal = CalibrationCurve(
        type="table",
        table=((0.0, 22.0), (2048.0, 25.2), (4095.0, 28.8)),
    )
    assert cal.apply(0.0) == pytest.approx(22.0)
    assert cal.apply(2048.0) == pytest.approx(25.2)
    assert cal.apply(4095.0) == pytest.approx(28.8)


@pytest.mark.requirement("SVF-DEV-096")
def test_table_apply_interpolates_midpoint() -> None:
    """Table calibration linearly interpolates between breakpoints."""
    cal = CalibrationCurve(
        type="table",
        table=((0.0, 0.0), (100.0, 10.0)),
    )
    assert cal.apply(50.0) == pytest.approx(5.0)
    assert cal.apply(25.0) == pytest.approx(2.5)


@pytest.mark.requirement("SVF-DEV-096")
def test_table_apply_clamps_below_minimum() -> None:
    """Values below the table minimum clamp to the first engineering value."""
    cal = CalibrationCurve(
        type="table",
        table=((100.0, 10.0), (200.0, 20.0)),
    )
    assert cal.apply(0.0) == pytest.approx(10.0)
    assert cal.apply(99.99) == pytest.approx(10.0)


@pytest.mark.requirement("SVF-DEV-096")
def test_table_apply_clamps_above_maximum() -> None:
    """Values above the table maximum clamp to the last engineering value."""
    cal = CalibrationCurve(
        type="table",
        table=((0.0, 0.0), (100.0, 10.0)),
    )
    assert cal.apply(200.0) == pytest.approx(10.0)


@pytest.mark.requirement("SVF-DEV-096")
def test_table_breakpoints_sorted_on_construction() -> None:
    """Table breakpoints provided out of order are sorted by raw value."""
    cal = CalibrationCurve(
        type="table",
        table=((100.0, 10.0), (0.0, 0.0), (50.0, 5.0)),
    )
    # After sort: (0,0), (50,5), (100,10)
    assert cal.apply(25.0) == pytest.approx(2.5)
    assert cal.apply(75.0) == pytest.approx(7.5)


# ── Validation ────────────────────────────────────────────────────────────────

@pytest.mark.requirement("SVF-DEV-096")
def test_invalid_calibration_type_raises() -> None:
    """CalibrationCurve raises ValueError for unknown type."""
    with pytest.raises(ValueError, match="'polynomial' or 'table'"):
        CalibrationCurve(type="spline", coefficients=(1.0,))


@pytest.mark.requirement("SVF-DEV-096")
def test_polynomial_empty_coefficients_raises() -> None:
    """Polynomial with no coefficients raises ValueError."""
    with pytest.raises(ValueError, match="at least one coefficient"):
        CalibrationCurve(type="polynomial", coefficients=())


@pytest.mark.requirement("SVF-DEV-096")
def test_table_single_point_raises() -> None:
    """Table with only one breakpoint raises ValueError."""
    with pytest.raises(ValueError, match="at least two breakpoints"):
        CalibrationCurve(type="table", table=((0.0, 0.0),))


# ── ParameterDefinition integration ──────────────────────────────────────────

@pytest.mark.requirement("SVF-DEV-096")
def test_parameter_definition_with_calibration() -> None:
    """ParameterDefinition stores and exposes calibration correctly."""
    cal = CalibrationCurve(type="polynomial", coefficients=(0.0, 0.00488))
    defn = ParameterDefinition(
        name="eps.battery.voltage",
        description="Battery terminal voltage (ADC raw)",
        unit="V",
        dtype=Dtype.FLOAT,
        classification=Classification.TM,
        domain=Domain.EPS,
        model_id="battery",
        calibration=cal,
    )
    assert defn.calibration is not None
    assert defn.calibration.apply(2048.0) == pytest.approx(9.99424)


@pytest.mark.requirement("SVF-DEV-096")
def test_parameter_definition_without_calibration() -> None:
    """ParameterDefinition without calibration has calibration=None."""
    defn = ParameterDefinition(
        name="aocs.rw1.speed",
        description="Reaction wheel speed",
        unit="rpm",
        dtype=Dtype.FLOAT,
        classification=Classification.TM,
        domain=Domain.AOCS,
        model_id="rw1",
    )
    assert defn.calibration is None


# ── YAML loader ───────────────────────────────────────────────────────────────

def _loader_from_yaml(tmp_path: Path, content: str) -> SrdbLoader:
    p = tmp_path / "params.yaml"
    p.write_text(textwrap.dedent(content))
    loader = SrdbLoader()
    loader.load_baseline(p)
    return loader


@pytest.mark.requirement("SVF-DEV-096")
def test_loader_parses_polynomial_calibration(tmp_path: Path) -> None:
    """SrdbLoader parses a polynomial calibration block from YAML."""
    loader = _loader_from_yaml(tmp_path, """\
        parameters:
          eps.battery.voltage:
            description: Battery voltage
            unit: V
            dtype: float
            classification: TM
            domain: EPS
            model_id: battery
            calibration:
              type: polynomial
              coefficients: [0.0, 0.00488]
    """)
    srdb = loader.build()
    defn = srdb.require("eps.battery.voltage")
    assert defn.calibration is not None
    assert defn.calibration.type == "polynomial"
    assert defn.calibration.apply(0.0) == pytest.approx(0.0)
    assert defn.calibration.apply(4095.0) == pytest.approx(4095.0 * 0.00488)


@pytest.mark.requirement("SVF-DEV-096")
def test_loader_parses_table_calibration(tmp_path: Path) -> None:
    """SrdbLoader parses a table calibration block from YAML."""
    loader = _loader_from_yaml(tmp_path, """\
        parameters:
          eps.battery.soc:
            description: Battery state of charge
            unit: ""
            dtype: float
            classification: TM
            domain: EPS
            model_id: battery
            calibration:
              type: table
              table:
                - [0, 0.05]
                - [2048, 0.52]
                - [4095, 1.0]
    """)
    srdb = loader.build()
    defn = srdb.require("eps.battery.soc")
    assert defn.calibration is not None
    assert defn.calibration.type == "table"
    assert defn.calibration.apply(0.0) == pytest.approx(0.05)
    assert defn.calibration.apply(4095.0) == pytest.approx(1.0)


@pytest.mark.requirement("SVF-DEV-096")
def test_loader_no_calibration_is_none(tmp_path: Path) -> None:
    """Parameters without calibration block have calibration=None after load."""
    loader = _loader_from_yaml(tmp_path, """\
        parameters:
          aocs.rw1.speed:
            description: RW speed
            unit: rpm
            dtype: float
            classification: TM
            domain: AOCS
            model_id: rw1
    """)
    srdb = loader.build()
    defn = srdb.require("aocs.rw1.speed")
    assert defn.calibration is None


@pytest.mark.requirement("SVF-DEV-096")
def test_loader_invalid_calibration_type_raises(tmp_path: Path) -> None:
    """Unknown calibration type in YAML raises SrdbLoadError."""
    with pytest.raises(SrdbLoadError, match="calibration type must be"):
        _loader_from_yaml(tmp_path, """\
            parameters:
              eps.x:
                description: x
                unit: V
                dtype: float
                classification: TM
                domain: EPS
                model_id: m
                calibration:
                  type: spline
                  coefficients: [1.0]
        """)


@pytest.mark.requirement("SVF-DEV-096")
def test_loader_polynomial_missing_coefficients_raises(tmp_path: Path) -> None:
    """Polynomial calibration with empty coefficients raises SrdbLoadError."""
    with pytest.raises(SrdbLoadError, match="non-empty 'coefficients'"):
        _loader_from_yaml(tmp_path, """\
            parameters:
              eps.x:
                description: x
                unit: V
                dtype: float
                classification: TM
                domain: EPS
                model_id: m
                calibration:
                  type: polynomial
                  coefficients: []
        """)


@pytest.mark.requirement("SVF-DEV-096")
def test_loader_table_too_few_points_raises(tmp_path: Path) -> None:
    """Table calibration with fewer than two breakpoints raises SrdbLoadError."""
    with pytest.raises(SrdbLoadError, match="at least two breakpoints"):
        _loader_from_yaml(tmp_path, """\
            parameters:
              eps.x:
                description: x
                unit: V
                dtype: float
                classification: TM
                domain: EPS
                model_id: m
                calibration:
                  type: table
                  table:
                    - [0, 0.0]
        """)


@pytest.mark.requirement("SVF-DEV-096")
def test_loader_calibration_survives_mission_override(tmp_path: Path) -> None:
    """Mission override of description preserves the baseline calibration."""
    baseline = tmp_path / "baseline.yaml"
    baseline.write_text(textwrap.dedent("""\
        parameters:
          eps.battery.voltage:
            description: Battery voltage (raw ADC)
            unit: V
            dtype: float
            classification: TM
            domain: EPS
            model_id: battery
            calibration:
              type: polynomial
              coefficients: [0.0, 0.00488]
    """))
    mission = tmp_path / "mission.yaml"
    mission.write_text(textwrap.dedent("""\
        parameters:
          eps.battery.voltage:
            description: Battery terminal voltage (engineering)
    """))
    loader = SrdbLoader()
    loader.load_baseline(baseline)
    loader.load_mission(mission)
    srdb = loader.build()
    defn = srdb.require("eps.battery.voltage")
    assert defn.description == "Battery terminal voltage (engineering)"
    assert defn.calibration is not None
    assert defn.calibration.apply(1000.0) == pytest.approx(4.88)
