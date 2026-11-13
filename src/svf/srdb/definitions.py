"""
SVF SRDB  -  Parameter Definition Schema
Core dataclasses for spacecraft parameter definitions.
Inspired by ECSS-E-TM-10-23 and the Astrium SRDB Next Generation.

One data one source: every parameter has exactly one authoritative
definition shared across all engineering disciplines.

Implements: SVF-DEV-090, SVF-DEV-096, SVF-DEV-217
"""

from __future__ import annotations

import enum
import struct
from dataclasses import dataclass, field
from typing import Optional, Union


class Classification(enum.Enum):
    """
    TM/TC classification of a parameter.

    TM: Telemetry  -  written by models, read by test procedures and reporters.
    TC: Telecommand  -  written by test procedures, consumed by model adapters.

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
class CalibrationCurve:
    """
    Raw-to-engineering calibration for a telemetry parameter.

    Two curve types are supported:

    polynomial:
        eng = coefficients[0] + coefficients[1]*raw + coefficients[2]*raw² + ...
        The coefficient tuple length determines the polynomial degree.
        At least one coefficient must be provided.

    table:
        Piecewise-linear interpolation over a list of (raw, eng) breakpoints.
        Points are sorted ascending by raw value at construction time.
        Values outside the table range are clamped to the nearest endpoint.
        At least two breakpoints are required.

    Attributes:
        type:         "polynomial" or "table"
        coefficients: Polynomial coefficients a0, a1, ..., aN (polynomial only)
        table:        Breakpoints as ((raw0, eng0), (raw1, eng1), ...) (table only)
    """
    type: str
    coefficients: tuple[float, ...] = ()
    table: tuple[tuple[float, float], ...] = ()

    def __post_init__(self) -> None:
        if self.type not in ("polynomial", "table"):
            raise ValueError(
                f"CalibrationCurve type must be 'polynomial' or 'table', "
                f"got '{self.type}'"
            )
        if self.type == "polynomial":
            if not self.coefficients:
                raise ValueError(
                    "CalibrationCurve polynomial requires at least one coefficient"
                )
        elif self.type == "table":
            if len(self.table) < 2:
                raise ValueError(
                    "CalibrationCurve table requires at least two breakpoints"
                )
            # Normalise to ascending raw order; frozen dataclass requires this idiom
            object.__setattr__(
                self, "table",
                tuple(sorted(self.table, key=lambda p: p[0]))
            )

    def apply(self, raw: float) -> float:
        """Convert a raw sensor value to its engineering unit equivalent."""
        if self.type == "polynomial":
            result = 0.0
            for i, coeff in enumerate(self.coefficients):
                result += coeff * (raw ** i)
            return result
        # table  -  piecewise linear, clamped at extremes
        pts = self.table
        if raw <= pts[0][0]:
            return pts[0][1]
        if raw >= pts[-1][0]:
            return pts[-1][1]
        for i in range(len(pts) - 1):
            r0, e0 = pts[i]
            r1, e1 = pts[i + 1]
            if r0 <= raw <= r1:
                t = (raw - r0) / (r1 - r0)
                return e0 + t * (e1 - e0)
        return pts[-1][1]  # unreachable


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
    calibration: Optional[CalibrationCurve] = None

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


# ── Housekeeping set layouts (TM(3,25)) ──────────────────────────────────────

class HkWireType(enum.Enum):
    """
    Raw encoding of a housekeeping parameter in a TM(3,25) report.

    The names are openobsw's SRDB parameter types. A report carries its
    parameters big-endian with no padding, so the byte size of each type is
    the width the flight software binds for it (``SRDB_HK_<SET>_SIZES``).
    """
    UINT8   = "uint8"
    INT8    = "int8"
    UINT16  = "uint16"
    INT16   = "int16"
    UINT32  = "uint32"
    INT32   = "int32"
    FLOAT32 = "float32"
    FLOAT64 = "float64"

    @property
    def struct_code(self) -> str:
        """``struct`` format character for this type."""
        return _HK_STRUCT_CODES[self]

    @property
    def size(self) -> int:
        """Encoded size in bytes."""
        return struct.calcsize(">" + _HK_STRUCT_CODES[self])


_HK_STRUCT_CODES: dict[HkWireType, str] = {
    HkWireType.UINT8: "B",   HkWireType.INT8: "b",
    HkWireType.UINT16: "H",  HkWireType.INT16: "h",
    HkWireType.UINT32: "I",  HkWireType.INT32: "i",
    HkWireType.FLOAT32: "f", HkWireType.FLOAT64: "d",
}


@dataclass(frozen=True)
class HkParameter:
    """
    One parameter of a housekeeping set.

    Attributes:
        name:         Canonical ParameterStore key the decoded raw value is
                      written to, e.g. "dhs.obc.obc_temperature"
        obsw_name:    Parameter name in the flight software's SRDB
        wire_type:    Raw encoding in the report
        unit:         Unit of the raw value. Empty string for dimensionless.
        description:  Human-readable description
    """
    name: str
    obsw_name: str
    wire_type: HkWireType
    unit: str = ""
    description: str = ""

    def __post_init__(self) -> None:
        if len(self.name.split(".")) < 3 or not all(self.name.split(".")):
            raise ValueError(
                f"HK parameter key '{self.name}' is not of the form "
                f"domain.subsystem.parameter"
            )
        if not self.obsw_name:
            raise ValueError(f"HK parameter '{self.name}' has no obsw name")


@dataclass(frozen=True)
class HkSetDefinition:
    """
    Layout of one housekeeping set as reported in TM(3,25).

    The application data of a report is the set ID (uint8) followed by the
    parameters in order, big-endian, each as wide as its wire type.

    Attributes:
        set_id:       Housekeeping set ID (the first application data byte)
        name:         Set name in the flight software's SRDB
        parameters:   Parameters in report order
        description:  Human-readable description
    """
    set_id: int
    name: str
    parameters: tuple[HkParameter, ...]
    description: str = ""
    _struct: struct.Struct = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not (0 <= self.set_id <= 255):
            raise ValueError(f"HK set ID must be 0-255, got {self.set_id}")
        if not self.parameters:
            raise ValueError(f"HK set {self.set_id} ({self.name}) has no parameters")
        for attr in ("name", "obsw_name"):
            seen = [getattr(p, attr) for p in self.parameters]
            dup = sorted({n for n in seen if seen.count(n) > 1})
            if dup:
                raise ValueError(
                    f"HK set {self.set_id} ({self.name}) lists {dup} more than once"
                )
        object.__setattr__(self, "_struct", struct.Struct(
            ">" + "".join(p.wire_type.struct_code for p in self.parameters)))

    @property
    def sizes(self) -> tuple[int, ...]:
        """Byte size of each parameter, in report order."""
        return tuple(p.wire_type.size for p in self.parameters)

    @property
    def data_len(self) -> int:
        """Bytes of parameter data in a report, without the set ID."""
        return self._struct.size

    def decode(self, data: bytes, offset: int = 0) -> tuple[Union[int, float], ...]:
        """
        Decode the raw parameter values of a report, in report order.

        ``data[offset:]`` starts at the first parameter, after the set ID.
        Raises ``struct.error`` when fewer than ``data_len`` bytes follow.
        """
        return self._struct.unpack_from(data, offset)
