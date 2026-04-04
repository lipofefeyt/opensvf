"""
SVF Reference Model — Integrated EPS FMU
Models a spacecraft Electrical Power System comprising:
  - Solar Array: illumination-dependent power generation
  - Battery: Li-Ion with non-linear SoC/voltage curve
  - PCDU: power conditioning and distribution

This is an integrated model — all three subsystems are internally
decomposed as Python classes but exposed as a single FMU interface.
Decomposition into separate FMUs connected via model wiring is
deferred to M4.5 (SVF-DEV-066).

Inputs:
  solar_illumination  float  0.0 (eclipse) to 1.0 (full sun)
  load_power          float  Spacecraft load demand in Watts

Outputs:
  bus_voltage         float  Regulated bus voltage in Volts
  battery_soc         float  Battery state of charge (0.0 to 1.0)
  battery_voltage     float  Battery terminal voltage in Volts
  generated_power     float  Solar array generated power in Watts
  charge_current      float  Battery charge/discharge current in Amps
                             Positive = charging, Negative = discharging

Simplifications documented:
  - Solar array modelled as ideal current source (no I-V curve)
  - No temperature dependence on capacity or panel efficiency
  - Bus voltage equals battery voltage (no active regulation)
  - No penumbra modelling beyond fractional illumination input
  - Constant internal resistance not modelled
  - No battery thermal model

Implements: SVF-DEV-063, SVF-DEV-065
"""

from pythonfmu import Fmi2Slave, Real   # type: ignore[import-untyped]


# ── Solar Array ───────────────────────────────────────────────────────────────

class SolarArray:
    """
    Models a spacecraft solar array.

    Generates power proportional to illumination level.
    Panel efficiency accounts for solar cell and harness losses.
    """

    MAX_POWER_W: float = 100.0    # Peak power in full sun (W)
    PANEL_EFFICIENCY: float = 0.90  # Combined panel and harness efficiency

    def step(self, solar_illumination: float) -> float:
        """
        Compute generated power.

        Args:
            solar_illumination: 0.0 (eclipse) to 1.0 (full sun).
                                Fractional values model penumbra.
        Returns:
            Generated power in Watts.
        """
        illumination = max(0.0, min(1.0, solar_illumination))
        return illumination * self.MAX_POWER_W * self.PANEL_EFFICIENCY


# ── Battery ───────────────────────────────────────────────────────────────────

class Battery:
    """
    Models a Li-Ion spacecraft battery.

    Uses a piecewise non-linear SoC/voltage curve approximating
    real Li-Ion cell behaviour:
      SoC 0.0 → 0.1 : steep rise (3.0V → 3.5V)
      SoC 0.1 → 0.9 : flat plateau (3.5V → 4.0V)
      SoC 0.9 → 1.0 : steep rise (4.0V → 4.2V)

    Reference: typical 18650 Li-Ion cell discharge curve.
    """

    CAPACITY_WH: float = 20.0      # Battery capacity in Watt-hours
    SOC_MIN: float = 0.05           # Minimum allowable SoC (protection cutoff)
    SOC_MAX: float = 1.0            # Maximum allowable SoC

    def __init__(self, initial_soc: float = 0.8) -> None:
        self.soc = max(self.SOC_MIN, min(self.SOC_MAX, initial_soc))

    @property
    def voltage(self) -> float:
        """
        Battery open-circuit voltage as a function of SoC.
        Piecewise linear approximation of Li-Ion discharge curve.
        """
        soc = self.soc
        if soc <= 0.1:
            return 3.0 + 5.0 * soc                    # 3.0V → 3.5V
        elif soc <= 0.9:
            return 3.5 + 0.625 * (soc - 0.1)         # 3.5V → 4.0V
        else:
            return 4.0 + 2.0 * (soc - 0.9)           # 4.0V → 4.2V

    def update(self, charge_current: float, dt: float) -> None:
        """
        Update SoC based on charge/discharge current.

        Args:
            charge_current: Current in Amps. Positive = charging.
            dt:             Timestep in seconds.
        """
        # Energy transferred in this timestep (Wh)
        delta_wh = charge_current * self.voltage * dt / 3600.0
        delta_soc = delta_wh / self.CAPACITY_WH
        self.soc = max(self.SOC_MIN, min(self.SOC_MAX, self.soc + delta_soc))


# ── PCDU ──────────────────────────────────────────────────────────────────────

class Pcdu:
    """
    Models a spacecraft Power Conditioning and Distribution Unit.

    Manages power flow between solar array, battery, and loads.
    Computes charge/discharge current based on power balance.

    Separate charge and discharge efficiencies account for
    real converter losses in both directions.
    """

    CHARGE_EFFICIENCY: float = 0.95     # Battery charging efficiency
    DISCHARGE_EFFICIENCY: float = 0.92  # Battery discharge efficiency

    def compute(
        self,
        generated_power: float,
        load_power: float,
        battery_voltage: float,
    ) -> float:
        """
        Compute battery charge/discharge current.

        Args:
            generated_power:  Solar array output in Watts.
            load_power:       Spacecraft load demand in Watts.
            battery_voltage:  Current battery terminal voltage.

        Returns:
            charge_current in Amps.
            Positive = battery charging.
            Negative = battery discharging.
        """
        power_balance = generated_power - load_power

        if battery_voltage <= 0.0:
            return 0.0

        if power_balance >= 0.0:
            # Surplus power — charge the battery
            return (power_balance * self.CHARGE_EFFICIENCY) / battery_voltage
        else:
            # Power deficit — discharge the battery
            return power_balance / (self.DISCHARGE_EFFICIENCY * battery_voltage)


# ── Integrated EPS FMU ────────────────────────────────────────────────────────

class EpsFmu(Fmi2Slave):    # type: ignore[misc]
    """
    Integrated EPS FMU combining SolarArray, Battery, and PCDU.

    Exposes a clean external interface while internally decomposing
    the three subsystems. Decomposition into separate FMUs is deferred
    to M4.5 (SVF-DEV-066).
    """

    author = "SVF"
    description = (
        "Integrated spacecraft EPS model: Solar Array + Li-Ion Battery + PCDU. "
        "Non-linear SoC/voltage curve. Separate charge/discharge efficiency. "
        "M4 reference model — see SVF-DEV-063, SVF-DEV-065."
    )

    def __init__(self, **kwargs):  # type: ignore[no-untyped-def]
        super().__init__(**kwargs)

        # Inputs
        self.solar_illumination: float = 1.0
        self.load_power: float = 30.0   # Default 30W load

        # Outputs
        self.bus_voltage: float = 0.0
        self.battery_soc: float = 0.0
        self.battery_voltage: float = 0.0
        self.generated_power: float = 0.0
        self.charge_current: float = 0.0

        # Internal subsystems
        self._solar_array = SolarArray()
        self._battery = Battery(initial_soc=0.8)
        self._pcdu = Pcdu()

        # Register FMI variables
        self.register_variable(Real(
            "solar_illumination",
            causality="input",
            variability="continuous",
            start=1.0,
            description="Solar illumination fraction (0.0=eclipse, 1.0=full sun)",
        ))
        self.register_variable(Real(
            "load_power",
            causality="input",
            variability="continuous",
            start=30.0,
            description="Spacecraft load power demand in Watts",
        ))
        self.register_variable(Real(
            "bus_voltage",
            causality="output",
            variability="continuous",
            description="Regulated bus voltage in Volts",
        ))
        self.register_variable(Real(
            "battery_soc",
            causality="output",
            variability="continuous",
            description="Battery state of charge (0.0 to 1.0)",
        ))
        self.register_variable(Real(
            "battery_voltage",
            causality="output",
            variability="continuous",
            description="Battery terminal voltage in Volts",
        ))
        self.register_variable(Real(
            "generated_power",
            causality="output",
            variability="continuous",
            description="Solar array generated power in Watts",
        ))
        self.register_variable(Real(
            "charge_current",
            causality="output",
            variability="continuous",
            description="Battery charge current in Amps (positive=charging)",
        ))

    def do_step(self, t: float, dt: float) -> bool:
        """
        Advance the EPS model by one timestep.

        Step order:
          1. Solar array computes generated power
          2. PCDU computes charge/discharge current from power balance
          3. Battery updates SoC from charge current
          4. Outputs written from updated state
        """
        # 1. Solar array
        self.generated_power = self._solar_array.step(self.solar_illumination)

        # 2. PCDU — compute current based on power balance
        self.charge_current = self._pcdu.compute(
            generated_power=self.generated_power,
            load_power=self.load_power,
            battery_voltage=self._battery.voltage,
        )

        # 3. Battery — update SoC
        self._battery.update(charge_current=self.charge_current, dt=dt)

        # 4. Write outputs
        self.battery_soc = self._battery.soc
        self.battery_voltage = self._battery.voltage
        self.bus_voltage = self._battery.voltage   # Simplified: no active regulation

        return True
