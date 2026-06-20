"""
SMP 2.0 portability layer for opensvf equipment models (Milestone M50).

SMP 2.0 (Simulation Modelling Portability, ECSS-E-ST-40-07C) is the European
space industry standard for exchangeable simulation models. Compliance means
opensvf models can be loaded into any SMP 2.0 runtime (BASILES, EuroSim,
SIMSAT) without code changes, and third-party SMP 2.0 models can be dropped
into opensvf simulations in their place.

The portability contract is expressed through ISmpModel, which every
NativeEquipment, OrbitalEnvironment, TtcEquipment, and Bus model satisfies
via SmpEquipmentMixin. The four lifecycle methods mirror the SMP 2.0 standard:

    model.smp_publish()    - register fields (derived from Equipment.ports)
    model.smp_configure()  - apply configuration parameters
    model.smp_connect()    - link to peer model fields
    model.initialise()     - set initial state before first tick

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
