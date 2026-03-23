"""
Tests for SimulationMaster, FmuModelAdapter, NativeModelAdapter and CsvLogger.
Implements: SVF-DEV-001, SVF-DEV-002, SVF-DEV-005, SVF-DEV-006, SVF-DEV-007,
            SVF-DEV-010, SVF-DEV-013, SVF-DEV-014, SVF-DEV-015, SVF-DEV-016
"""

import pytest
from pathlib import Path

from cyclonedds.domain import DomainParticipant

from svf.simulation import SimulationMaster, SimulationError
from svf.abstractions import SyncProtocol
from svf.software_tick import SoftwareTickSource
from svf.fmu_adapter import FmuModelAdapter
from svf.native_adapter import NativeModelAdapter
from svf.logging import CsvLogger

FMU_PATH = Path(__file__).parent.parent / "examples" / "SimpleCounter.fmu"


# ── Helpers ───────────────────────────────────────────────────────────────────

class _PassthroughSync(SyncProtocol):
    """Minimal SyncProtocol — always returns True immediately."""
    def reset(self) -> None: pass
    def publish_ready(self, model_id: str, t: float) -> None: pass
    def wait_for_ready(self, expected: list[str], timeout: float) -> bool: return True


@pytest.fixture
def participant() -> DomainParticipant:
    return DomainParticipant()


@pytest.fixture
def sync() -> _PassthroughSync:
    return _PassthroughSync()


# ── NativeModelAdapter tests ──────────────────────────────────────────────────

def test_native_adapter_step(
    participant: DomainParticipant, sync: _PassthroughSync
) -> None:
    """NativeModelAdapter correctly delegates to the underlying model."""
    results: list[float] = []

    class _RecordingModel:
        def step(self, t: float, dt: float) -> dict[str, float]:
            results.append(round(t + dt, 9))
            return {"value": round(t + dt, 9)}

    adapter = NativeModelAdapter(
        model=_RecordingModel(),
        model_id="rec",
        output_names=["value"],
        participant=participant,
        sync_protocol=sync,
    )
    adapter.initialise()
    adapter.on_tick(t=0.0, dt=0.1)
    assert results == [pytest.approx(0.1)]
    adapter.teardown()


def test_native_adapter_invalid_model(
    participant: DomainParticipant, sync: _PassthroughSync
) -> None:
    """NativeModelAdapter rejects a model missing the step() method."""
    with pytest.raises(TypeError, match="does not implement"):
        NativeModelAdapter(
            model=object(),  # type: ignore
            model_id="bad",
            output_names=[],
            participant=participant,
            sync_protocol=sync,
        )


# ── FmuModelAdapter tests ─────────────────────────────────────────────────────

def test_fmu_adapter_initialises(
    participant: DomainParticipant, sync: _PassthroughSync
) -> None:
    """FmuModelAdapter loads and initialises without error."""
    adapter = FmuModelAdapter(
        fmu_path=FMU_PATH,
        model_id="counter",
        participant=participant,
        sync_protocol=sync,
    )
    adapter.initialise()
    assert "counter" in adapter.output_names
    adapter.teardown()


def test_fmu_adapter_on_tick(
    participant: DomainParticipant, sync: _PassthroughSync
) -> None:
    """FmuModelAdapter steps the FMU without error."""
    adapter = FmuModelAdapter(
        fmu_path=FMU_PATH,
        model_id="counter",
        participant=participant,
        sync_protocol=sync,
    )
    adapter.initialise()
    adapter.on_tick(t=0.0, dt=0.1)
    adapter.teardown()


def test_fmu_adapter_missing_fmu(
    participant: DomainParticipant, sync: _PassthroughSync
) -> None:
    """FmuModelAdapter raises FileNotFoundError for missing FMU."""
    with pytest.raises(FileNotFoundError, match="FMU not found"):
        FmuModelAdapter(
            fmu_path="nonexistent.fmu",
            model_id="bad",
            participant=participant,
            sync_protocol=sync,
        )


def test_fmu_adapter_tick_before_initialise(
    participant: DomainParticipant, sync: _PassthroughSync
) -> None:
    """FmuModelAdapter raises RuntimeError if ticked before initialise."""
    adapter = FmuModelAdapter(
        fmu_path=FMU_PATH,
        model_id="counter",
        participant=participant,
        sync_protocol=sync,
    )
    with pytest.raises(RuntimeError, match="not initialised"):
        adapter.on_tick(t=0.0, dt=0.1)


# ── SimulationMaster tests ────────────────────────────────────────────────────

def test_simulation_master_runs(
    participant: DomainParticipant, sync: _PassthroughSync
) -> None:
    """SimulationMaster completes a 10-step run."""
    results: list[float] = []

    class _RecordingModel:
        def step(self, t: float, dt: float) -> dict[str, float]:
            results.append(round(t + dt, 9))
            return {"value": round(t + dt, 9)}

    master = SimulationMaster(
        tick_source=SoftwareTickSource(),
        sync_protocol=sync,
        models=[NativeModelAdapter(_RecordingModel(), "rec", ["value"], participant, sync)],
        dt=0.1,
        stop_time=1.0,
    )
    master.run()
    assert len(results) == 10
    assert results[-1] == pytest.approx(1.0)


def test_simulation_master_with_fmu(
    participant: DomainParticipant, sync: _PassthroughSync
) -> None:
    """SimulationMaster runs correctly with FmuModelAdapter."""
    master = SimulationMaster(
        tick_source=SoftwareTickSource(),
        sync_protocol=sync,
        models=[FmuModelAdapter(FMU_PATH, "counter", participant, sync)],
        dt=0.1,
        stop_time=1.0,
    )
    master.run()
    assert master.time == pytest.approx(0.9)


def test_simulation_master_no_models(sync: _PassthroughSync) -> None:
    """SimulationMaster raises SimulationError if no models provided."""
    with pytest.raises(SimulationError, match="at least one"):
        SimulationMaster(
            tick_source=SoftwareTickSource(),
            sync_protocol=sync,
            models=[],
            dt=0.1,
            stop_time=1.0,
        )


def test_simulation_master_context_manager(
    participant: DomainParticipant, sync: _PassthroughSync
) -> None:
    """SimulationMaster tears down cleanly via context manager."""
    class _SimpleModel:
        def step(self, t: float, dt: float) -> dict[str, float]:
            return {"value": round(t + dt, 9)}

    with SimulationMaster(
        tick_source=SoftwareTickSource(),
        sync_protocol=sync,
        models=[NativeModelAdapter(_SimpleModel(), "simple", ["value"], participant, sync)],
        dt=0.1,
        stop_time=0.5,
    ) as master:
        master.run()
    assert master.time == pytest.approx(0.4)


# ── CsvLogger tests ───────────────────────────────────────────────────────────

def test_csv_logger_creates_file(tmp_path: Path) -> None:
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


def test_csv_logger_record_before_open() -> None:
    """CsvLogger raises RuntimeError if record called before open."""
    csv_logger = CsvLogger()
    with pytest.raises(RuntimeError, match="not open"):
        csv_logger.record(time=0.1, outputs={"counter": 0.1})


def test_csv_logger_wired_to_fmu_adapter(
    participant: DomainParticipant, sync: _PassthroughSync, tmp_path: Path
) -> None:
    """CsvLogger receives all steps when wired to FmuModelAdapter."""
    csv_logger = CsvLogger(output_dir=tmp_path, run_id="wired")
    master = SimulationMaster(
        tick_source=SoftwareTickSource(),
        sync_protocol=sync,
        models=[FmuModelAdapter(
            FMU_PATH, "counter", participant, sync, csv_logger=csv_logger
        )],
        dt=0.1,
        stop_time=0.5,
    )
    master.run()

    files = list(tmp_path.glob("wired_*.csv"))
    assert len(files) == 1
    lines = files[0].read_text().strip().splitlines()
    assert len(lines) == 6  # header + 5 data rows
