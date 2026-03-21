"""
Tests for SimulationMaster and CsvLogger.
Implements: SVF-DEV-001, SVF-DEV-002, SVF-DEV-005, SVF-DEV-006, SVF-DEV-007
"""

import pytest
from pathlib import Path
from svf.simulation import SimulationMaster, SimulationError
from svf.logging import CsvLogger

FMU_PATH = Path(__file__).parent.parent / "examples" / "SimpleCounter.fmu"


# ── SimulationMaster tests ────────────────────────────────────────────────────

def test_simulation_master_initialises():
    """FMU loads and initialises without error."""
    master = SimulationMaster(FMU_PATH, dt=0.1)
    master.initialise()
    assert master.time == 0.0
    assert "counter" in master.output_names
    master.teardown()


def test_simulation_master_steps():
    """Single step advances time by dt and returns output dict."""
    with SimulationMaster(FMU_PATH, dt=0.1) as master:
        master.initialise()
        outputs = master.step()
        assert master.time == pytest.approx(0.1)
        assert "counter" in outputs
        assert outputs["counter"] == pytest.approx(0.1)


def test_simulation_master_multiple_steps():
    """10 steps advance time to 1.0s correctly."""
    with SimulationMaster(FMU_PATH, dt=0.1) as master:
        master.initialise()
        for _ in range(10):
            master.step()
        assert master.time == pytest.approx(1.0)


def test_simulation_master_context_manager_teardown():
    """Context manager calls teardown automatically."""
    with SimulationMaster(FMU_PATH, dt=0.1) as master:
        master.initialise()
        master.step()
    assert master._instance is None


def test_simulation_master_missing_fmu():
    """Missing FMU path raises SimulationError on construction."""
    with pytest.raises(SimulationError, match="FMU not found"):
        SimulationMaster("nonexistent.fmu", dt=0.1)


def test_simulation_master_step_before_initialise():
    """Stepping before initialise raises SimulationError."""
    master = SimulationMaster(FMU_PATH, dt=0.1)
    with pytest.raises(SimulationError, match="not been initialised"):
        master.step()


# ── CsvLogger tests ───────────────────────────────────────────────────────────

def test_csv_logger_creates_file(tmp_path: Path):
    """CsvLogger creates a CSV file with correct headers."""
    csv_logger = CsvLogger(output_dir=tmp_path, run_id="test")
    csv_logger.open(["counter"])
    csv_logger.record(time=0.1, outputs={"counter": 0.1})
    csv_logger.close()

    files = list(tmp_path.glob("test_*.csv"))
    assert len(files) == 1

    content = files[0].read_text()
    assert "time,counter" in content
    assert "0.1,0.1" in content


def test_csv_logger_record_before_open():
    """Recording before open raises RuntimeError."""
    csv_logger = CsvLogger()
    with pytest.raises(RuntimeError, match="not open"):
        csv_logger.record(time=0.1, outputs={"counter": 0.1})


def test_csv_logger_wired_to_simulation_master(tmp_path: Path):
    """CsvLogger receives all steps when wired to SimulationMaster."""
    csv_logger = CsvLogger(output_dir=tmp_path, run_id="wired")
    with SimulationMaster(FMU_PATH, dt=0.1, csv_logger=csv_logger) as master:
        master.initialise()
        for _ in range(5):
            master.step()

    files = list(tmp_path.glob("wired_*.csv"))
    assert len(files) == 1
    lines = files[0].read_text().strip().splitlines()
    assert len(lines) == 6  # header + 5 data rows