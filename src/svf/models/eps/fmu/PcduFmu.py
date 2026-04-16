"""
SVF Reference Model — PCDU FMU
Models spacecraft Power Conditioning and Distribution Unit.

Inputs:
  generated_power   float  Solar array output power in Watts
  battery_voltage   float  Battery terminal voltage in Volts
  load_power        float  Spacecraft load demand in Watts

Outputs:
  bus_voltage       float  Regulated bus voltage in Volts
  charge_current    float  Battery charge/discharge current in Amps

Implements: SVF-DEV-066
"""

from pythonfmu import Fmi2Slave, Real  # type: ignore[import-untyped]


class PcduFmu(Fmi2Slave):  # type: ignore[misc]

    author = "lipofefeyt"
    description = (
        "Spacecraft PCDU model. "
        "Manages power flow between solar array, battery, and loads. "
        "Part of decomposed EPS — see SVF-DEV-066."
    )

    CHARGE_EFFICIENCY: float = 0.95
    DISCHARGE_EFFICIENCY: float = 0.92

    def __init__(self, **kwargs):  # type: ignore[no-untyped-def]
        super().__init__(**kwargs)

        self.generated_power: float = 0.0
        self.battery_voltage: float = 3.7
        self.load_power: float = 30.0
        self.bus_voltage: float = 0.0
        self.charge_current: float = 0.0

        self.register_variable(Real(
            "generated_power",
            causality="input",
            variability="continuous",
            start=0.0,
            description="Solar array generated power in Watts",
        ))
        self.register_variable(Real(
            "battery_voltage",
            causality="input",
            variability="continuous",
            start=3.7,
            description="Battery terminal voltage in Volts",
        ))
        self.register_variable(Real(
            "load_power",
            causality="input",
            variability="continuous",
            start=30.0,
            description="Spacecraft load demand in Watts",
        ))
        self.register_variable(Real(
            "bus_voltage",
            causality="output",
            variability="continuous",
            description="Regulated bus voltage in Volts",
        ))
        self.register_variable(Real(
            "charge_current",
            causality="output",
            variability="continuous",
            description="Battery charge current in Amps (positive=charging)",
        ))

    def do_step(self, t: float, dt: float) -> bool:
        power_balance = self.generated_power - self.load_power

        if self.battery_voltage <= 0.0:
            self.charge_current = 0.0
        elif power_balance >= 0.0:
            self.charge_current = (
                power_balance * self.CHARGE_EFFICIENCY
            ) / self.battery_voltage
        else:
            self.charge_current = power_balance / (
                self.DISCHARGE_EFFICIENCY * self.battery_voltage
            )

        self.bus_voltage = self.battery_voltage
        return True
