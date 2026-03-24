"""
SVF SRDB — Parameter Definition Schema
Core dataclasses for spacecraft parameter definitions.
Inspired by ECSS-E-TM-10-23 and the Astrium SRDB Next Generation.

One data one source: every parameter has exactly one authoritative
definition shared across all engineering disciplines.

Implements: SVF-DEV-090
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Optional


class Classification(enum.Enum):
    """
    TM/TC classification of a parameter.

    TM: Telemetry — written by models, read by test procedures and reporters.
    TC: Telecommand — written by test procedures, consumed by model adapters.

    Mirrors the fundamental TM/TC separation in real spacecraft architecture.
    """
    TM = "TM"
    TC = "TC"


class Domain(enum.Enum):
    """
    Spacecraft engineering domain owning the parameter.

    Matches the five standard spacecraft subsystem domains used in
    ECSS and ESA mission databases.
    """
    EPS     = "EPS"      # Electrical Power System
    AOCS    = "AOCS"     # Attitude and Orbit Control System
    TTC     = "TTC"      # Telemetry, Tracking and Command
    OBDH    = "OBDH"     # On-Board Data Handling
    THERMAL = "THERMAL"  # Thermal Control


class Dtype(enum.Enum):
    """
    Data type of the parameter value.
    """
    FLOAT  = "float"
    INT    = "int"
    BOOL   = "bool"
    STRING = "string"


@dataclass(frozen=True)
class PusMapping:
    """
    CCSDS Packet Utilisation Standard (PUS) mapping for a parameter.

    Maps the parameter to its PUS service/subservice and parameter ID,
    enabling future integration with CCSDS/PUS commanding and telemetry
    reporting (SVF-DEV-037).

    Attributes:
        apid:          CCSDS Application Process Identifier (11-bit)
        service:       PUS service type (e.g. 3 = Housekeeping)
        subservice:    PUS subservice type (e.g. 25 = HK parameter report)
        parameter_id:  Parameter ID within the service (mission-specific)
    """
    apid: int
    service: int
    subservice: int
    parameter_id: int

    def __post_init__(self) -> None:
        if not (0 <= self.apid <= 0x7FF):
            raise ValueError(f"APID must be 0-2047, got {self.apid}")
        if not (0 <= self.service <= 255):
            raise ValueError(f"PUS service must be 0-255, got {self.service}")
        if not (0 <= self.subservice <= 255):
            raise ValueError(f"PUS subservice must be 0-255, got {self.subservice}")
        if not (0 <= self.parameter_id <= 0xFFFF):
            raise ValueError(f"Parameter ID must be 0-65535, got {self.parameter_id}")


@dataclass(frozen=True)
class ParameterDefinition:
    """
    Authoritative definition of a spacecraft parameter.

    Separates parameter definition (what this parameter is) from
    runtime value (what its current value is). The ParameterStore
    holds runtime values; the SRDB holds definitions.

    Attributes:
        name:            Canonical parameter name. Convention: domain.subsystem.parameter
                         e.g. "eps.battery.soc", "aocs.attitude.quaternion_w"
        description:     Human-readable description of the parameter
        unit:            Engineering unit (SI preferred). Empty string for dimensionless.
        dtype:           Data type of the parameter value
        classification:  TM (telemetry output) or TC (telecommand input)
        domain:          Spacecraft engineering domain
        model_id:        ID of the model that owns this parameter
        valid_range:     Optional (min, max) tuple for range checking.
                         None means no range constraint defined.
        pus:             Optional PUS service mapping. None if not PUS-mapped.
    """
    name: str
    description: str
    unit: str
    dtype: Dtype
    classification: Classification
    domain: Domain
    model_id: str
    valid_range: Optional[tuple[float, float]] = None
    pus: Optional[PusMapping] = None

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("Parameter name cannot be empty")
        if not self.model_id:
            raise ValueError("model_id cannot be empty")
        if self.valid_range is not None:
            lo, hi = self.valid_range
            if lo >= hi:
                raise ValueError(
                    f"valid_range min ({lo}) must be less than max ({hi}) "
                    f"for parameter '{self.name}'"
                )

    def is_in_range(self, value: float) -> bool:
        """
        Check whether a value falls within the defined valid range.
        Always returns True if no valid_range is defined.
        """
        if self.valid_range is None:
            return True
        lo, hi = self.valid_range
        return lo <= value <= hi

    def __str__(self) -> str:
        unit_str = f" [{self.unit}]" if self.unit else ""
        range_str = f" {self.valid_range}" if self.valid_range else ""
        return (
            f"{self.name}{unit_str} "
            f"({self.classification.value}, {self.domain.value})"
            f"{range_str}"
        )