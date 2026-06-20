"""
SMP 2.0 portability layer for opensvf equipment models.

Exports the ISmpModel interface and SmpEquipmentMixin so that any Equipment
subclass can declare SMP 2.0 compliance by mixing in SmpEquipmentMixin.

Implements: SVF-DEV-182, SVF-DEV-183
"""

from svf.smp.interfaces import ISmpModel, SmpField, SmpState
from svf.smp.mixin import SmpEquipmentMixin

__all__ = [
    "ISmpModel",
    "SmpEquipmentMixin",
    "SmpField",
    "SmpState",
]
