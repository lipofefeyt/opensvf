"""
Tests for SrdbLoader and Srdb.
Implements: SVF-DEV-092, SVF-DEV-093
"""

import pytest
from pathlib import Path
from svf.srdb.loader import SrdbLoader, SrdbLoadError, Srdb
from svf.srdb.definitions import Classification, Domain, Dtype


# ── Fixtures ──────────────────────────────────────────────────────────────────

MINIMAL_YAML = """
parameters:
  eps.battery.soc:
    description: Battery state of charge
    unit: ""
    dtype: float
    classification: TM
    domain: EPS
    model_id: eps
    valid_range: [0.05, 1.0]
    pus:
      apid: 0x100
      service: 3
      subservice: 25
      parameter_id: 0x0042
"""

SECOND_YAML = """
parameters:
  eps.solar_illumination:
    description: Solar illumination fraction
    unit: ""
    dtype: float
    classification: TC
    domain: EPS
    model_id: eps
    valid_range: [0.0, 1.0]
"""

MISSION_YAML = """
parameters:
  eps.battery.soc:
    description: Battery SoC (mission override)
    valid_range: [0.1, 0.95]
  eps.new_param:
    description: Mission-specific parameter
    unit: "W"
    dtype: float
    classification: TM
    domain: EPS
    model_id: eps
"""


@pytest.fixture
def baseline_file(tmp_path: Path) -> Path:
    f = tmp_path / "eps.yaml"
    f.write_text(MINIMAL_YAML)
    return f


@pytest.fixture
def second_file(tmp_path: Path) -> Path:
    f = tmp_path / "aocs.yaml"
    f.write_text(SECOND_YAML)
    return f


@pytest.fixture
def mission_file(tmp_path: Path) -> Path:
    f = tmp_path / "mission.yaml"
    f.write_text(MISSION_YAML)
    return f


# ── SrdbLoader basic loading ──────────────────────────────────────────────────

def test_load_baseline(baseline_file: Path) -> None:
    """Baseline YAML loads and produces correct ParameterDefinition."""
    loader = SrdbLoader()
    loader.load_baseline(baseline_file)
    srdb = loader.build()

    assert "eps.battery.soc" in srdb
    defn = srdb.require("eps.battery.soc")
    assert defn.classification == Classification.TM
    assert defn.domain == Domain.EPS
    assert defn.dtype == Dtype.FLOAT
    assert defn.valid_range == (0.05, 1.0)
    assert defn.pus is not None
    assert defn.pus.apid == 0x100
    assert defn.pus.service == 3
    assert defn.pus.parameter_id == 0x0042


def test_load_multiple_baselines(
    baseline_file: Path, second_file: Path
) -> None:
    """Multiple baseline files merge correctly."""
    loader = SrdbLoader()
    loader.load_baseline(baseline_file)
    loader.load_baseline(second_file)
    srdb = loader.build()

    assert len(srdb) == 2
    assert "eps.battery.soc" in srdb
    assert "eps.solar_illumination" in srdb


def test_srdb_by_domain(
    baseline_file: Path, second_file: Path
) -> None:
    """by_domain() filters correctly."""
    loader = SrdbLoader()
    loader.load_baseline(baseline_file)
    loader.load_baseline(second_file)
    srdb = loader.build()

    eps_params = srdb.by_domain(Domain.EPS)
    assert len(eps_params) == 2


def test_srdb_by_classification(
    baseline_file: Path, second_file: Path
) -> None:
    """by_classification() filters correctly."""
    loader = SrdbLoader()
    loader.load_baseline(baseline_file)
    loader.load_baseline(second_file)
    srdb = loader.build()

    tm_params = srdb.by_classification(Classification.TM)
    tc_params = srdb.by_classification(Classification.TC)
    assert len(tm_params) == 1
    assert len(tc_params) == 1


def test_srdb_by_model(baseline_file: Path) -> None:
    """by_model() filters correctly."""
    loader = SrdbLoader()
    loader.load_baseline(baseline_file)
    srdb = loader.build()

    eps_params = srdb.by_model("eps")
    assert len(eps_params) == 1


def test_srdb_get_unknown_returns_none(baseline_file: Path) -> None:
    """get() returns None for unknown parameter."""
    loader = SrdbLoader()
    loader.load_baseline(baseline_file)
    srdb = loader.build()
    assert srdb.get("nonexistent") is None


def test_srdb_require_unknown_raises(baseline_file: Path) -> None:
    """require() raises KeyError for unknown parameter."""
    loader = SrdbLoader()
    loader.load_baseline(baseline_file)
    srdb = loader.build()
    with pytest.raises(KeyError, match="nonexistent"):
        srdb.require("nonexistent")


# ── Mission override tests ────────────────────────────────────────────────────

def test_mission_override_description(
    baseline_file: Path, mission_file: Path
) -> None:
    """Mission override updates description."""
    loader = SrdbLoader()
    loader.load_baseline(baseline_file)
    loader.load_mission(mission_file)
    srdb = loader.build()

    defn = srdb.require("eps.battery.soc")
    assert defn.description == "Battery SoC (mission override)"


def test_mission_override_valid_range(
    baseline_file: Path, mission_file: Path
) -> None:
    """Mission override updates valid_range."""
    loader = SrdbLoader()
    loader.load_baseline(baseline_file)
    loader.load_mission(mission_file)
    srdb = loader.build()

    defn = srdb.require("eps.battery.soc")
    assert defn.valid_range == (0.1, 0.95)


def test_mission_adds_new_parameter(
    baseline_file: Path, mission_file: Path
) -> None:
    """Mission file can add new parameters."""
    loader = SrdbLoader()
    loader.load_baseline(baseline_file)
    loader.load_mission(mission_file)
    srdb = loader.build()

    assert "eps.new_param" in srdb
    assert len(srdb) == 2


def test_mission_cannot_change_classification(
    baseline_file: Path, tmp_path: Path
) -> None:
    """Mission file cannot change TM/TC classification."""
    mission = tmp_path / "bad_mission.yaml"
    mission.write_text("""
parameters:
  eps.battery.soc:
    classification: TC
""")
    loader = SrdbLoader()
    loader.load_baseline(baseline_file)
    with pytest.raises(SrdbLoadError, match="classification"):
        loader.load_mission(mission)


# ── Error handling tests ──────────────────────────────────────────────────────

def test_missing_file_raises(tmp_path: Path) -> None:
    """Loading a non-existent file raises SrdbLoadError."""
    loader = SrdbLoader()
    with pytest.raises(SrdbLoadError, match="not found"):
        loader.load_baseline(tmp_path / "nonexistent.yaml")


def test_duplicate_baseline_parameter_raises(
    baseline_file: Path, tmp_path: Path
) -> None:
    """Duplicate parameter across baseline files raises SrdbLoadError."""
    duplicate = tmp_path / "duplicate.yaml"
    duplicate.write_text(MINIMAL_YAML)
    loader = SrdbLoader()
    loader.load_baseline(baseline_file)
    with pytest.raises(SrdbLoadError, match="duplicate"):
        loader.load_baseline(duplicate)


def test_missing_required_field_raises(tmp_path: Path) -> None:
    """Missing required field raises SrdbLoadError."""
    f = tmp_path / "bad.yaml"
    f.write_text("""
parameters:
  eps.battery.soc:
    description: Battery SoC
    unit: ""
    dtype: float
    classification: TM
""")
    loader = SrdbLoader()
    with pytest.raises(SrdbLoadError, match="missing required field"):
        loader.load_baseline(f)


def test_invalid_classification_raises(tmp_path: Path) -> None:
    """Invalid classification value raises SrdbLoadError."""
    f = tmp_path / "bad.yaml"
    f.write_text("""
parameters:
  eps.battery.soc:
    description: Battery SoC
    unit: ""
    dtype: float
    classification: INVALID
    domain: EPS
    model_id: eps
""")
    loader = SrdbLoader()
    with pytest.raises(SrdbLoadError, match="classification"):
        loader.load_baseline(f)


def test_invalid_domain_raises(tmp_path: Path) -> None:
    """Invalid domain value raises SrdbLoadError."""
    f = tmp_path / "bad.yaml"
    f.write_text("""
parameters:
  eps.battery.soc:
    description: Battery SoC
    unit: ""
    dtype: float
    classification: TM
    domain: INVALID
    model_id: eps
""")
    loader = SrdbLoader()
    with pytest.raises(SrdbLoadError, match="domain"):
        loader.load_baseline(f)


# ── Full baseline integration test ────────────────────────────────────────────

def test_load_all_baselines() -> None:
    """All five domain baselines load cleanly and produce correct counts."""
    baseline_dir = Path(__file__).parent.parent.parent / "srdb" / "baseline"
    loader = SrdbLoader()
    for f in sorted(baseline_dir.glob("*.yaml")):
        loader.load_baseline(f)
    srdb = loader.build()

    # Confirm all five domains are present
    for domain in Domain:
        params = srdb.by_domain(domain)
        assert len(params) > 0, f"No parameters found for domain {domain.value}"

    # Confirm TM/TC split — both should exist
    assert len(srdb.by_classification(Classification.TM)) > 0
    assert len(srdb.by_classification(Classification.TC)) > 0

    # Confirm EPS FMU parameters are covered
    assert "eps.battery.soc" in srdb
    assert "eps.battery.voltage" in srdb
    assert "eps.bus.voltage" in srdb
    assert "eps.solar_array.illumination" in srdb
    assert "eps.load.power" in srdb


def test_load_baselines_with_mission_override() -> None:
    """Mission override applies correctly on top of all baselines."""
    baseline_dir = Path(__file__).parent.parent.parent / "srdb" / "baseline"
    mission_file = (
        Path(__file__).parent.parent.parent
        / "srdb" / "missions" / "example_mission.yaml"
    )
    loader = SrdbLoader()
    for f in sorted(baseline_dir.glob("*.yaml")):
        loader.load_baseline(f)
    loader.load_mission(mission_file)
    srdb = loader.build()

    # Battery SoC range overridden
    soc = srdb.require("eps.battery.soc")
    assert soc.valid_range == (0.2, 0.9)

    # Mission-specific parameter added
    assert "eps.payload.power" in srdb
