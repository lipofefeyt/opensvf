"""
Quick smoke test for SimulationMaster against SimpleCounter.fmu.
Not a pytest test - just a manual validation script.
"""

from pathlib import Path
from svf.simulation import SimulationMaster

fmu_path = Path(__file__).parent / "SimpleCounter.fmu"

print("Testing SimulationMaster with SimpleCounter.fmu")
print("-" * 45)

with SimulationMaster(fmu_path, dt=0.1) as master:
    master.initialise(start_time=0.0)
    print(f"Outputs: {master.output_names}")
    print(f"\n{'Step':>5}  {'Time':>8}  {'counter':>10}")
    print("-" * 30)
    for i in range(10):
        outputs = master.step()
        print(f"{i:>5}  {master.time:>8.3f}  {outputs['counter']:>10.3f}")

print("\nSimulationMaster smoke test passed.")