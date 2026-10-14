"""
SMP-aligned model layer for opensvf equipment models (M50, corrected in M63).

SMP (Simulation Modelling Platform, ECSS-E-ST-40-07C) is the European space
industry standard for exchangeable simulation models. opensvf aligns with
its component lifecycle and describes model interfaces in SMP-style XML,
which keeps a later port to a real SMP runtime mechanical.

What this is not: SMP compliance. The standard is a C++ ABI plus SMDL
schemas; opensvf models are Python and cannot be loaded by an SMP runtime
(BASILES, EuroSim, SIMSAT), and the generated catalogue is not validated
against XML/Smdl/Catalogue.xsd. A real bridge is roadmap item M68.

The contract is expressed through ISmpModel, which every NativeEquipment,
OrbitalEnvironment, TtcEquipment, and Bus model satisfies via
SmpEquipmentMixin. The lifecycle mirrors IComponent (§5.2.3.1):

    model.smp_publish()     - Created -> Publishing (fields from Equipment.ports)
    model.smp_configure()   - Publishing -> Configured
    model.smp_connect()     - Configured -> Connected
    model.initialise()      - ModelAdapter initial state, before first tick
    model.smp_disconnect()  - Connected -> Disconnected (final)

Implements: SVF-DEV-182, SVF-DEV-183, SVF-DEV-202
"""

from svf.smp.interfaces import (
    SMP_ALIGNED_NS,
    ISmpModel,
    SmpField,
    SmpState,
    SmpStateError,
)
from svf.smp.mixin import SmpEquipmentMixin

__all__ = [
    "SMP_ALIGNED_NS",
    "ISmpModel",
    "SmpEquipmentMixin",
    "SmpField",
    "SmpState",
    "SmpStateError",
]
