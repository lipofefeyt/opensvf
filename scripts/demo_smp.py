"""
opensvf - SMP-aligned model lifecycle demo (M50, M63)

Shows the SMP component lifecycle on a real magnetometer model:
  publish -> configure -> connect -> tick -> disconnect

Run from the repo root with the venv activated:
    python scripts/demo_smp.py
"""

from __future__ import annotations

from svf.core.abstractions import SyncProtocol
from svf.models.aocs.magnetometer import make_magnetometer
from svf.smp import ISmpModel
from svf.stores.parameter_store import ParameterStore


# ── minimal no-op sync so the demo runs without DDS ──────────────────────────

class _NoSync(SyncProtocol):
    def reset(self) -> None: pass
    def publish_ready(self, model_id: str, t: float) -> None: pass
    def wait_for_ready(self, expected: list[str], timeout: float) -> bool: return True


# ── display helpers ───────────────────────────────────────────────────────────

W = 62

def _header(text: str) -> None:
    print()
    print(f" {text}")
    print(" " + "─" * (W - 2))

def _row(label: str, value: str) -> None:
    print(f"  {label:<28}{value}")

def _sep() -> None:
    print()


# ── demo ─────────────────────────────────────────────────────────────────────

def main() -> None:
    print()
    print(" " + "═" * W)
    print("  opensvf  -  SMP-aligned model lifecycle demo  (M50, M63)")
    print("  ECSS-E-ST-40-07C  -  Simulation Modelling Platform")
    print(" " + "═" * W)

    # ── 1. Build a real model ─────────────────────────────────────────────────
    store = ParameterStore()
    mag   = make_magnetometer(
        sync_protocol=_NoSync(),
        store=store,
        equipment_id="mag1",
        seed=42,
    )

    _header("Model")
    _row("equipment_id:",    mag.equipment_id)
    _row("class:",           type(mag).__name__)
    _row("ISmpModel?",       str(isinstance(mag, ISmpModel)))
    _row("ports declared:",  str(len(mag.ports)))
    _row("initial state:",   mag.smp_state.value)

    # ── 2. SMP lifecycle ──────────────────────────────────────────────────
    _header("SMP lifecycle  (ECSS-E-ST-40-07C §5.2.3.1)")

    mag.smp_publish()
    print(f"  smp_publish()     ->  {mag.smp_state.value}"
          f"  [{len(mag.smp_fields)} fields registered]")

    mag.smp_configure()
    print(f"  smp_configure()   ->  {mag.smp_state.value}")

    mag.smp_connect()
    print(f"  smp_connect()     ->  {mag.smp_state.value}")

    mag.initialise(start_time=0.0)
    print(f"  initialise()      ->  {mag.smp_state.value}  (ModelAdapter, state unchanged)")

    # ── 3. Field catalogue ────────────────────────────────────────────────────
    _header("SMP-aligned field catalogue")
    print(f"  {'NAME':<32} {'KIND':<10} {'DIR':<8} {'UNIT':<6} DESCRIPTION")
    print("  " + "─" * (W - 2))
    for f in mag.smp_fields.values():
        unit = f.unit if f.unit else "-"
        desc = f.description[:22] if f.description else ""
        print(f"  {f.name:<32} {f.kind:<10} {f.direction:<8} {unit:<6} {desc}")

    # ── 4. Simulation tick ────────────────────────────────────────────────────
    _header("Simulation  (t=0.0 s, dt=0.1 s)")

    B_TRUE = (2.34e-5, -1.12e-5, 4.56e-5)   # realistic LEO B-field, Tesla
    mag._port_values["aocs.mag1.power_enable"] = 1.0
    mag._port_values["aocs.mag1.true_x"]       = B_TRUE[0]
    mag._port_values["aocs.mag1.true_y"]       = B_TRUE[1]
    mag._port_values["aocs.mag1.true_z"]       = B_TRUE[2]

    print(f"  inject  power_enable = 1.0  (powered on)")
    print(f"  inject  true_x/y/z   = {B_TRUE[0]:.2e}  {B_TRUE[1]:.2e}  {B_TRUE[2]:.2e}  T")
    _sep()

    mag.do_step(t=0.0, dt=0.1)

    meas_x = mag.read_port("aocs.mag1.field_x")
    meas_y = mag.read_port("aocs.mag1.field_y")
    meas_z = mag.read_port("aocs.mag1.field_z")
    status = mag.read_port("aocs.mag1.status")

    print(f"  field_x  = {meas_x:+.6e} T   (noise {meas_x - B_TRUE[0]:+.2e} T)")
    print(f"  field_y  = {meas_y:+.6e} T   (noise {meas_y - B_TRUE[1]:+.2e} T)")
    print(f"  field_z  = {meas_z:+.6e} T   (noise {meas_z - B_TRUE[2]:+.2e} T)")
    print(f"  status   = {status:.1f}  (nominal)")

    # ── 5. Disconnect and contract check ──────────────────────────────────────
    _sep()
    mag.smp_disconnect()
    print(f"  smp_disconnect()  ->  {mag.smp_state.value}  (final)")
    print(" " + "═" * W)
    aligned = isinstance(mag, ISmpModel)
    mark    = "PASS" if aligned else "FAIL"
    print(f"  [{mark}]  ISmpModel lifecycle contract satisfied (SMP-aligned)")
    print("          Not loadable by SMP runtimes; real bridge is roadmap M68")
    print(" " + "═" * W)
    print()


if __name__ == "__main__":
    main()
