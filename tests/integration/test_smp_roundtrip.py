"""
L2 SMP-aligned round-trip smoke test (M50).

A MinimalSmpHost drives a NativeEquipment model through the SMP-aligned lifecycle
(publish -> configure -> connect) and verifies that the simulation output is
identical to a direct run without the SMP lifecycle interposed. SimpleCounter.fmu
runs alongside to confirm the SMP lifecycle does not interfere with FMU
co-simulation.

Implements: SVF-DEV-187
"""
from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest

from svf.core.abstractions import SyncProtocol
from svf.core.equipment import Equipment
from svf.core.fmu_equipment import FmuEquipment
from svf.models.aocs.magnetometer import make_magnetometer
from svf.smp import ISmpModel, SmpState
from svf.stores.command_store import CommandStore
from svf.stores.parameter_store import ParameterStore

COUNTER_FMU = Path(__file__).parent.parent.parent / "models" / "SimpleCounter.fmu"

_fmu_present = pytest.mark.skipif(
    not COUNTER_FMU.exists(),
    reason="SimpleCounter.fmu not found - L2 FMU tests skipped",
)


class _NoSync(SyncProtocol):
    def reset(self) -> None:
        pass

    def publish_ready(self, model_id: str, t: float) -> None:
        pass

    def wait_for_ready(self, expected: list[str], timeout: float) -> bool:
        return True


class MinimalSmpHost:
    """Minimal SMP-aligned Simulation Environment (SE) implementation.

    Implements the SMP-aligned composite model hosting contract:
    publish all fields, configure, connect, initialise, then step.
    This is the host side of the SMP-aligned IModel contract; each model
    under test is the guest side.
    """

    def __init__(self, models: list[ISmpModel]) -> None:
        """Initialise host with a list of ISmpModel guest models."""
        self._models = models

    def publish(self) -> None:
        """Call smp_publish() on all guest models."""
        for m in self._models:
            m.smp_publish()

    def configure(self) -> None:
        """Call smp_configure() on all guest models."""
        for m in self._models:
            m.smp_configure()

    def connect(self) -> None:
        """Call smp_connect() on all guest models."""
        for m in self._models:
            m.smp_connect()

    def initialise(self) -> None:
        """Run full SMP lifecycle then Equipment.initialise()."""
        self.publish()
        self.configure()
        self.connect()
        for m in self._models:
            cast(Equipment, m).initialise()

    def step(self, t: float, dt: float) -> None:
        """Advance all models by one tick."""
        for m in self._models:
            cast(Equipment, m).do_step(t=t, dt=dt)

    def run(self, steps: int, dt: float = 1.0) -> None:
        """Initialise then run for the given number of steps."""
        self.initialise()
        for i in range(steps):
            self.step(t=float(i) * dt, dt=dt)


# ── G1: SMP lifecycle round-trip ──────────────────────────────────────────────

class SmpRoundtripSuite:
    """L2 round-trip smoke tests: SMP lifecycle transparency and FMU co-simulation."""

    @pytest.mark.requirement("SVF-DEV-187")
    def test_smp_host_state_after_initialise(self) -> None:
        """After MinimalSmpHost.initialise() every model is in CONNECTED state."""
        store = ParameterStore()
        mag   = make_magnetometer(_NoSync(), store, CommandStore())
        host  = MinimalSmpHost([cast(ISmpModel, mag)])
        host.initialise()
        assert cast(ISmpModel, mag).smp_state == SmpState.CONNECTED

    @pytest.mark.requirement("SVF-DEV-187")
    def test_smp_lifecycle_transparent_to_native_output(self) -> None:
        """SMP lifecycle does not alter do_step output vs direct native path.

        Two independent magnetometer instances share no state. One is run
        directly (initialise -> do_step), the other via MinimalSmpHost.
        All OUT port store values must match within floating-point tolerance.
        """
        steps = 3
        dt    = 1.0

        # Direct (no SMP) path
        store_direct = ParameterStore()
        mag_direct   = make_magnetometer(_NoSync(), store_direct, CommandStore())
        mag_direct.initialise()
        for i in range(steps):
            mag_direct.do_step(t=float(i) * dt, dt=dt)

        # SMP host path
        store_smp = ParameterStore()
        mag_smp   = make_magnetometer(_NoSync(), store_smp, CommandStore())
        host      = MinimalSmpHost([cast(ISmpModel, mag_smp)])
        host.run(steps, dt)

        # All OUT port parameter names must produce identical store values
        smp_model = cast(ISmpModel, mag_smp)
        out_fields = [
            f.name for f in smp_model.smp_fields.values()
            if f.direction == "Output"
        ]
        assert out_fields, "no Output fields found after SMP publish"
        for name in out_fields:
            entry_direct = store_direct.read(name)
            entry_smp    = store_smp.read(name)
            assert entry_direct is not None, f"direct store missing '{name}'"
            assert entry_smp    is not None, f"SMP store missing '{name}'"
            assert entry_direct.value == pytest.approx(entry_smp.value, abs=1e-9), (
                f"SMP path diverged for '{name}': "
                f"direct={entry_direct.value} smp={entry_smp.value}"
            )

    @pytest.mark.requirement("SVF-DEV-187")
    def test_smp_fields_match_output_port_names(self) -> None:
        """Output SmpField names are a subset of ParameterStore keys after stepping."""
        store = ParameterStore()
        mag   = make_magnetometer(_NoSync(), store, CommandStore())
        host  = MinimalSmpHost([cast(ISmpModel, mag)])
        host.run(steps=1)

        smp_model  = cast(ISmpModel, mag)
        out_fields = [
            f.name for f in smp_model.smp_fields.values()
            if f.direction == "Output"
        ]
        for name in out_fields:
            entry = store.read(name)
            assert entry is not None, (
                f"SmpField '{name}' not written to store after do_step"
            )

    @pytest.mark.requirement("SVF-DEV-187")
    @_fmu_present
    def test_smp_model_runs_alongside_fmu(self) -> None:
        """MinimalSmpHost NativeEquipment and FmuEquipment co-simulate correctly.

        Magnetometer (ISmpModel, NativeEquipment) is driven through the SMP
        lifecycle. SimpleCounter.fmu (FmuEquipment, not ISmpModel) runs in
        parallel via its native interface. After N steps: FMU counter equals
        N * dt; magnetometer OUT fields are present in the store.
        """
        steps = 5
        dt    = 1.0

        store     = ParameterStore()
        cmd_store = CommandStore()
        sync      = _NoSync()

        # SMP-wrapped native model
        mag  = make_magnetometer(sync, store, cmd_store)
        host = MinimalSmpHost([cast(ISmpModel, mag)])
        host.initialise()

        # FMU co-model running natively alongside the SMP host
        fmu = FmuEquipment(
            fmu_path=COUNTER_FMU,
            equipment_id="counter",
            sync_protocol=sync,
            store=store,
            command_store=cmd_store,
        )
        fmu.initialise()

        for i in range(steps):
            host.step(t=float(i) * dt, dt=dt)
            fmu.do_step(t=float(i) * dt, dt=dt)

        # FmuEquipment writes to _port_values; read via read_port()
        counter_val = fmu.read_port("counter")
        assert counter_val == pytest.approx(steps * dt, rel=1e-6), (
            f"FMU counter after {steps} steps: expected {steps * dt}, got {counter_val}"
        )

        smp_model  = cast(ISmpModel, mag)
        out_fields = [
            f.name for f in smp_model.smp_fields.values()
            if f.direction == "Output"
        ]
        assert out_fields, "magnetometer has no Output fields"
        for name in out_fields:
            entry = store.read(name)
            assert entry is not None, (
                f"magnetometer field '{name}' not in store after co-simulation"
            )
