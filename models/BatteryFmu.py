"""
SVF Reference Model — Battery FMU
Models a Li-Ion spacecraft battery.

Inputs:
  charge_current  float  Charge/discharge current in Amps
                         Positive = charging, negative = discharging

Outputs:
  battery_voltage float  Battery terminal voltage in Volts
  battery_soc     float  State of charge (0.0 to 1.0)

Implements: SVF-DEV-066
"""

from pythonfmu import Fmi2Slave, Real  # type: ignore[import-untyped]


class BatteryFmu(Fmi2Slave):  # type: ignore[misc]

    author = "lipofefeyt"
    description = (
        "Li-Ion spacecraft battery model. "
        "Non-linear SoC/voltage curve. "
        "Part of decomposed EPS — see SVF-DEV-066."
    )

    CAPACITY_WH: float = 20.0
    SOC_MIN: float = 0.05
    SOC_MAX: float = 1.0
    INITIAL_SOC: float = 0.8

    def __init__(self, **kwargs):  # type: ignore[no-untyped-def]
        super().__init__(**kwargs)

        self.charge_current: float = 0.0
        self.battery_voltage: float = 0.0
        self.battery_soc: float = self.INITIAL_SOC

        self._soc: float = self.INITIAL_SOC

        self.register_variable(Real(
            "charge_current",
            causality="input",
            variability="continuous",
            start=0.0,
            description="Battery charge current in Amps (positive=charging)",
        ))
        self.register_variable(Real(
            "battery_voltage",
            causality="output",
            variability="continuous",
            description="Battery terminal voltage in Volts",
        ))
        self.register_variable(Real(
            "battery_soc",
            causality="output",
            variability="continuous",
            description="Battery state of charge (0.0 to 1.0)",
        ))

    def _voltage_from_soc(self, soc: float) -> float:
        """Non-linear SoC/voltage curve — piecewise Li-Ion approximation."""
        if soc <= 0.1:
            return 3.0 + 5.0 * soc
        elif soc <= 0.9:
            return 3.5 + 0.625 * (soc - 0.1)
        else:
            return 4.0 + 2.0 * (soc - 0.9)

    def do_step(self, t: float, dt: float) -> bool:
        v = self._voltage_from_soc(self._soc)
        delta_wh = self.charge_current * v * dt / 3600.0
        delta_soc = delta_wh / self.CAPACITY_WH
        self._soc = max(self.SOC_MIN, min(self.SOC_MAX, self._soc + delta_soc))

        self.battery_soc = self._soc
        self.battery_voltage = self._voltage_from_soc(self._soc)
        return True
