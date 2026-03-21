"""
Smoke test for SimulationMaster + CsvLogger against SimpleCounter.fmu.
"""

from pathlib import Path
from svf.simulation import SimulationMaster
from svf.logging import CsvLogger

fmu_path = Path(__file__).parent / "SimpleCounter.fmu"

print("Testing SimulationMaster + CsvLogger with SimpleCounter.fmu")
print("-" * 55)

csv_logger = CsvLogger(output_dir="results", run_id="simple_counter")

with SimulationMaster(fmu_path, dt=0.1, csv_logger=csv_logger) as master:
    master.initialise(start_time=0.0)
    print(f"Outputs: {master.output_names}")
    print(f"\n{'Step':>5}  {'Time':>8}  {'counter':>10}")
    print("-" * 30)
    for i in range(10):
        outputs = master.step()
        print(f"{i:>5}  {master.time:>8.3f}  {outputs['counter']:>10.3f}")

print(f"\nCSV written to: {csv_logger.path}")
print("\nSimulationMaster + CsvLogger smoke test passed.")