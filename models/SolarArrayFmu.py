"""
SVF Reference Model — Solar Array FMU
Models spacecraft solar array power generation.

Inputs:
  solar_illumination  float  0.0 (eclipse) to 1.0 (full sun)

Outputs:
  generated_power     float  Solar array output power in Watts
  array_voltage       float  Solar array open-circuit voltage in Volts

Implements: SVF-DEV-066
"""

from pythonfmu import Fmi2Slave, Real  # type: ignore[import-untyped]


class SolarArrayFmu(Fmi2Slave):  # type: ignore[misc]

    author = "lipofefeyt"
    description = (
        "Spacecraft solar array model. "
        "Power proportional to illumination fraction. "
        "Part of decomposed EPS — see SVF-DEV-066."
    )

    MAX_POWER_W: float = 100.0
    PANEL_EFFICIENCY: float = 0.90
    OPEN_CIRCUIT_VOLTAGE: float = 5.0  # V, simplified

    def __init__(self, **kwargs):  # type: ignore[no-untyped-def]
        super().__init__(**kwargs)

        self.solar_illumination: float = 1.0
        self.generated_power: float = 0.0
        self.array_voltage: float = 0.0

        self.register_variable(Real(
            "solar_illumination",
            causality="input",
            variability="continuous",
            start=1.0,
            description="Solar illumination fraction (0.0=eclipse, 1.0=full sun)",
        ))
        self.register_variable(Real(
            "generated_power",
            causality="output",
            variability="continuous",
            description="Solar array generated power in Watts",
        ))
        self.register_variable(Real(
            "array_voltage",
            causality="output",
            variability="continuous",
            description="Solar array open-circuit voltage in Volts",
        ))

    def do_step(self, t: float, dt: float) -> bool:
        illumination = max(0.0, min(1.0, self.solar_illumination))
        self.generated_power = illumination * self.MAX_POWER_W * self.PANEL_EFFICIENCY
        self.array_voltage = illumination * self.OPEN_CIRCUIT_VOLTAGE
        return True
