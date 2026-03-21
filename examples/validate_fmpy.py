"""
SVF - fmpy validation script
Builds a minimal pythonfmu FMU and steps it using fmpy.
Closes: #2
Implements: SVF-DEV-001, SVF-DEV-040
"""

import fmpy
from fmpy import simulate_fmu, read_model_description
from pathlib import Path


def main():
    print(f"fmpy version: {fmpy.__version__}")

    fmu_path = Path(__file__).parent / "SimpleCounter.fmu"
    if not fmu_path.exists():
        raise FileNotFoundError(
            f"FMU not found at {fmu_path}. "
            "Run: python3 -m pythonfmu build -f examples/SimpleCounter.py --dest examples/"
        )

    # Print model description
    model_desc = read_model_description(str(fmu_path))
    print(f"Model name:  {model_desc.modelName}")
    print(f"FMI version: {model_desc.fmiVersion}")

    # Simulate for 10 steps
    print("\nStepping FMU (dt=0.1s, 10 steps):")
    print(f"{'Step':>5}  {'Time':>8}  {'counter':>10}")
    print("-" * 30)

    result = simulate_fmu(
        str(fmu_path),
        stop_time=1.0,
        step_size=0.1,
        output_interval=0.1,
    )

    for i, row in enumerate(result):
        print(f"{i:>5}  {row[0]:>8.3f}  {row[1]:>10.3f}")

    print("\nValidation complete - fmpy and pythonfmu are working correctly.")


if __name__ == "__main__":
    main()