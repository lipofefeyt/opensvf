"""
SVF Simple Nodal Thermal Equipment Model

Models spacecraft thermal environment as a network of nodes.
Each node has mass, heat capacity, radiative properties.
Heat flows: solar input, radiation to space, conduction between nodes.

The internal cavity temperature is exposed as thermal.cavity.temp_degc
so equipment models can use it as their ambient reference.

Ports:
  IN:  thermal.solar_illumination  — 0=eclipse, 1=full sun (from CSS)
       thermal.equipment_power_w   — total equipment dissipation [W]
  OUT: thermal.{node_id}.temp_degc — node temperature [degC]
       thermal.cavity.temp_degc    — internal cavity temperature [degC]
       thermal.min_temp_degc       — coldest node [degC]
       thermal.max_temp_degc       — hottest node [degC]

Implements: SVF-DEV-082
"""
from __future__ import annotations

import logging
from typing import Optional, Any

from svf.abstractions import SyncProtocol
from svf.native_equipment import NativeEquipment
from svf.equipment import PortDefinition, PortDirection
from svf.parameter_store import ParameterStore
from svf.command_store import CommandStore

logger = logging.getLogger(__name__)

STEFAN_BOLTZMANN = 5.67e-8  # W/m²/K⁴
SOLAR_FLUX       = 1361.0   # W/m²

try:
    import importlib.util as _importlib_util
except Exception:
    _HW_AVAILABLE = False

# Default 3-node configuration
_DEFAULT_NODES: list[dict[str, Any]] = [
    {
        "id": "panel_plus_x",
        "mass_kg": 0.5,
        "specific_heat_j_kg_k": 900.0,
        "area_m2": 0.01,
        "absorptivity": 0.9,
        "emissivity": 0.85,
        "initial_temp_degc": -20.0,
    },
    {
        "id": "panel_minus_x",
        "mass_kg": 0.5,
        "specific_heat_j_kg_k": 900.0,
        "area_m2": 0.01,
        "absorptivity": 0.1,
        "emissivity": 0.85,
        "initial_temp_degc": -20.0,
    },
    {
        "id": "internal",
        "mass_kg": 1.0,
        "specific_heat_j_kg_k": 900.0,
        "area_m2": 0.0,
        "absorptivity": 0.0,
        "emissivity": 0.0,
        "initial_temp_degc": 20.0,
    },
]

_DEFAULT_CONDUCTANCES: dict[str, float] = {
    "panel_plus_x_to_internal":  0.1,
    "panel_minus_x_to_internal": 0.1,
}


def _make_step_fn(
    nodes: list[dict[str, Any]],
    conductances: dict[str, float],
) -> Any:
    """Closure over node configuration."""
    node_ids = [n["id"] for n in nodes]

    def _thermal_step(eq: NativeEquipment, t: float, dt: float) -> None:
        illumination  = eq.read_port("thermal.solar_illumination")
        # Auto-aggregate: sum all *.power_w parameters from ParameterStore
        # Falls back to port value if nothing is in the store
        auto_power = 0.0
        if eq._store is not None:
            snapshot = eq._store.snapshot()
            for key, entry in snapshot.items():
                if key.endswith(".power_w") and not key.startswith("thermal."):
                    auto_power += max(0.0, entry.value)
        port_power = eq.read_port("thermal.equipment_power_w")
        equip_power_w = auto_power if auto_power > 0.0 else port_power

        # Read current node temperatures
        temps_k = {}
        for node in nodes:
            nid = node["id"]
            temp_c = eq.read_port(f"thermal.{nid}.temp_degc")
            temps_k[nid] = temp_c + 273.15

        new_temps_k = dict(temps_k)

        for node in nodes:
            nid    = node["id"]
            mass   = node["mass_kg"]
            cp     = node["specific_heat_j_kg_k"]
            area   = node["area_m2"]
            alpha  = node["absorptivity"]
            eps    = node["emissivity"]
            T      = temps_k[nid]

            # Solar input [W]
            q_solar = illumination * alpha * area * SOLAR_FLUX

            # Radiation to space [W]
            q_rad = eps * STEFAN_BOLTZMANN * area * (T ** 4)

            # Equipment dissipation (split equally across nodes)
            q_equip = equip_power_w / len(nodes)

            # Conduction from/to other nodes [W]
            q_cond = 0.0
            for key, g in conductances.items():
                parts = key.split("_to_")
                if len(parts) != 2:
                    continue
                n_from = parts[0]
                n_to   = parts[1]
                if nid == n_to and n_from in temps_k:
                    q_cond += g * (temps_k[n_from] - T)
                elif nid == n_from and n_to in temps_k:
                    q_cond -= g * (T - temps_k[n_to])

            # Integrate: dT = (Q_net / (m * cp)) * dt
            q_net  = q_solar - q_rad + q_equip + q_cond
            dT     = (q_net / (mass * cp)) * dt
            new_temps_k[nid] = T + dT

        # Write outputs
        temps_c = {nid: T - 273.15 for nid, T in new_temps_k.items()}
        for nid, tc in temps_c.items():
            eq.write_port(f"thermal.{nid}.temp_degc", tc)

        # Cavity = internal node if present, else average
        if "internal" in temps_c:
            eq.write_port("thermal.cavity.temp_degc", temps_c["internal"])
        else:
            avg = sum(temps_c.values()) / len(temps_c)
            eq.write_port("thermal.cavity.temp_degc", avg)

        eq.write_port("thermal.min_temp_degc", min(temps_c.values()))
        eq.write_port("thermal.max_temp_degc", max(temps_c.values()))

    return _thermal_step


def make_thermal(
    sync_protocol: SyncProtocol,
    store: ParameterStore,
    command_store: Optional[CommandStore] = None,
    hardware_profile: Optional[str] = None,
    hardware_dir: str = "srdb/data/hardware",
) -> NativeEquipment:
    """
    Create a Thermal NativeEquipment.

    Args:
        hardware_profile: SRDB hardware profile ID (e.g. 'thermal_default').
        hardware_dir:    Directory containing hardware YAML profiles.
    """
    nodes       = _DEFAULT_NODES
    conductances = _DEFAULT_CONDUCTANCES

    if hardware_profile is not None:
        from svf.hardware_profile import load_hardware_profile
        profile = load_hardware_profile(hardware_profile)

    node_ids = [n["id"] for n in nodes]

    # Build port list dynamically from nodes
    ports = [
        PortDefinition("thermal.solar_illumination", PortDirection.IN,
                       description="Solar illumination (0=eclipse, 1=sun)"),
        PortDefinition("thermal.equipment_power_w",  PortDirection.IN,
                       unit="W",
                       description="Total equipment heat dissipation"),
    ]
    for node in nodes:
        nid = node["id"]
        ports.append(PortDefinition(
            f"thermal.{nid}.temp_degc", PortDirection.OUT,
            unit="degC", description=f"Node {nid} temperature",
        ))
    ports += [
        PortDefinition("thermal.cavity.temp_degc", PortDirection.OUT,
                       unit="degC", description="Internal cavity temperature"),
        PortDefinition("thermal.min_temp_degc",    PortDirection.OUT,
                       unit="degC", description="Coldest node"),
        PortDefinition("thermal.max_temp_degc",    PortDirection.OUT,
                       unit="degC", description="Hottest node"),
    ]

    step_fn = _make_step_fn(nodes, conductances)

    eq = NativeEquipment(
        equipment_id="thermal",
        ports=ports,
        step_fn=step_fn,
        sync_protocol=sync_protocol,
        store=store,
        command_store=command_store,
    )

    # Set initial temperatures
    for node in nodes:
        nid = node["id"]
        eq._port_values[f"thermal.{nid}.temp_degc"] = node["initial_temp_degc"]

    eq._port_values["thermal.cavity.temp_degc"] = next(
        (n["initial_temp_degc"] for n in nodes if n["id"] == "internal"),
        nodes[0]["initial_temp_degc"],
    )
    eq._port_values["thermal.min_temp_degc"] = min(
        n["initial_temp_degc"] for n in nodes
    )
    eq._port_values["thermal.max_temp_degc"] = max(
        n["initial_temp_degc"] for n in nodes
    )
    return eq
