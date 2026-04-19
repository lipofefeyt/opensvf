"""
SVF Universal Equipment Fault Engine

Intercepts Equipment.read_port() and write_port() to inject
standardised faults without modifying model physics code.

Fault types:
  stuck  — output fixed value regardless of physics
  noise  — add Gaussian noise to value
  bias   — add constant offset to value
  scale  — multiply value by factor (efficiency degradation)
  fail   — output 0.0 (complete failure)

Usage (via ProcedureContext):
  ctx.inject_equipment_fault(
      equipment_id="str1",
      port="aocs.str1.quaternion_w",
      fault_type="stuck",
      value=0.0,
      duration_s=10.0,
  )
  ctx.clear_equipment_faults("str1")

Usage (direct):
  engine = EquipmentFaultEngine()
  engine.inject(EquipmentFault(
      port="aocs.mag.field_x",
      fault_type=FaultMode.BIAS,
      value=1e-5,
      duration_s=30.0,
      injected_at=0.0,
  ))
  value = engine.apply_read("aocs.mag.field_x", raw_value=0.0, t=1.0)

Implements: SVF-DEV-132
"""
from __future__ import annotations

import logging
import math
import random
from dataclasses import dataclass
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class FaultMode(str, Enum):
    STUCK  = "stuck"   # output fixed value
    NOISE  = "noise"   # add Gaussian noise (value = std_dev)
    BIAS   = "bias"    # add constant offset
    SCALE  = "scale"   # multiply by factor (0.5 = 50% degradation)
    FAIL   = "fail"    # output 0.0 (complete failure)


@dataclass
class EquipmentFault:
    """A fault to inject on a specific port."""
    port:        str
    fault_type:  FaultMode
    value:       float        # meaning depends on fault_type
    duration_s:  float        # 0.0 = permanent
    injected_at: float        # simulation time of injection
    seed:        Optional[int] = None  # for reproducible noise

    def is_expired(self, t: float) -> bool:
        if self.duration_s <= 0.0:
            return False
        return t >= self.injected_at + self.duration_s


class EquipmentFaultEngine:
    """
    Per-equipment fault engine.

    Attached to a NativeEquipment instance. Intercepts read_port()
    and write_port() to apply active faults.
    """

    def __init__(self, equipment_id: str, seed: Optional[int] = None) -> None:
        self._equipment_id = equipment_id
        self._faults:  list[EquipmentFault] = []
        self._rng      = random.Random(seed)

    def inject(self, fault: EquipmentFault) -> None:
        """Inject a fault, replacing any existing fault on the same port."""
        self._faults = [
            f for f in self._faults if f.port != fault.port
        ]
        self._faults.append(fault)
        logger.warning(
            f"[fault-engine:{self._equipment_id}] "
            f"Injected {fault.fault_type.value} on '{fault.port}' "
            f"value={fault.value} duration={fault.duration_s}s"
        )

    def clear(self, port: Optional[str] = None) -> None:
        """Clear faults on a specific port, or all faults."""
        if port is None:
            count = len(self._faults)
            self._faults.clear()
            logger.info(
                f"[fault-engine:{self._equipment_id}] "
                f"Cleared {count} faults"
            )
        else:
            self._faults = [f for f in self._faults if f.port != port]
            logger.info(
                f"[fault-engine:{self._equipment_id}] "
                f"Cleared faults on '{port}'"
            )

    def active_faults(self, t: float) -> list[EquipmentFault]:
        """Return non-expired faults at time t."""
        return [f for f in self._faults if not f.is_expired(t)]

    def expire(self, t: float) -> None:
        """Remove expired faults."""
        before = len(self._faults)
        self._faults = [f for f in self._faults if not f.is_expired(t)]
        expired = before - len(self._faults)
        if expired > 0:
            logger.info(
                f"[fault-engine:{self._equipment_id}] "
                f"{expired} fault(s) expired at t={t:.2f}s"
            )

    def apply_read(self, port: str, raw_value: float, t: float) -> float:
        """
        Apply any active fault to a read_port() value.
        Returns the (possibly modified) value.
        """
        for fault in self.active_faults(t):
            if fault.port != port:
                continue
            return self._apply(fault, raw_value)
        return raw_value

    def apply_write(self, port: str, value: float, t: float) -> float:
        """
        Apply any active fault to a write_port() value.
        Used for actuator output faults (stuck valve, degraded thruster).
        """
        for fault in self.active_faults(t):
            if fault.port != port:
                continue
            return self._apply(fault, value)
        return value

    def _apply(self, fault: EquipmentFault, value: float) -> float:
        if fault.fault_type == FaultMode.STUCK:
            return fault.value
        elif fault.fault_type == FaultMode.NOISE:
            return value + self._rng.gauss(0.0, fault.value)
        elif fault.fault_type == FaultMode.BIAS:
            return value + fault.value
        elif fault.fault_type == FaultMode.SCALE:
            return value * fault.value
        elif fault.fault_type == FaultMode.FAIL:
            return 0.0
        return value
