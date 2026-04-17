"""
SVF Spacecraft Configuration Loader

Loads a complete spacecraft simulation from a YAML definition file.
Zero Python required for standard configurations.

Usage:
    from svf.spacecraft import SpacecraftLoader

    master = SpacecraftLoader.load("spacecraft.yaml")
    master.run()

Or via CLI:
    svf run spacecraft.yaml

Spacecraft YAML format:
    spacecraft: MySat-1

    obsw:
      type: pipe          # pipe | socket
      binary: ./obsw_sim  # path to OBSW binary (pipe mode)
      arch: x86_64        # x86_64 | aarch64 (pipe mode)
      host: localhost      # (socket mode)
      port: 3456           # (socket mode)

    equipment:
      - id: mag1
        model: magnetometer
        hardware_profile: mag_default   # optional
        seed: 42                         # optional
      - id: rw1
        model: reaction_wheel
        hardware_profile: rw_sinclair_rw003
      - id: kde
        model: dynamics

    buses:                               # optional
      - id: aocs_bus
        type: mil1553
        rt_count: 8
        mappings:
          - rt: 5 sa: 1 parameter: aocs.rw1.torque_cmd direction: BC_to_RT
          - rt: 5 sa: 2 parameter: aocs.rw1.speed      direction: RT_to_BC

    wiring:
      auto: true           # auto-wire matching port names (default: true)
      overrides:           # explicit overrides (optional)
        - from: mag1.aocs.mag.field_x
          to:   obc.aocs.mag1.field_x

    simulation:
      dt: 0.1
      stop_time: 300.0
      seed: 42
      realtime: false      # true for RealtimeTickSource

Implements: SVF-DEV-110
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

import yaml
from cyclonedds.domain import DomainParticipant

from svf.command_store import CommandStore
from svf.dds_sync import DdsSyncProtocol
from svf.parameter_store import ParameterStore
from svf.simulation import SimulationMaster
from svf.software_tick import RealtimeTickSource, SoftwareTickSource
from svf.wiring import WiringLoader

logger = logging.getLogger(__name__)


# Registry of model factories
# Maps model name → (module, factory_function_or_class)
_MODEL_REGISTRY: dict[str, tuple[str, str]] = {
    "magnetometer":   ("svf.models.aocs.magnetometer",  "make_magnetometer"),
    "magnetorquer":   ("svf.models.aocs.magnetorquer",  "make_magnetorquer"),
    "gyroscope":      ("svf.models.aocs.gyroscope",     "make_gyroscope"),
    "reaction_wheel": ("svf.models.aocs.reaction_wheel","make_reaction_wheel"),
    "star_tracker":   ("svf.models.aocs.star_tracker",  "make_star_tracker"),
    "css":            ("svf.models.aocs.css",            "make_css"),
    "gps":            ("svf.models.aocs.gps",            "make_gps"),
    "thruster":       ("svf.models.aocs.thruster",       "make_thruster"),
    "bdot_controller":("svf.models.aocs.bdot_controller","make_bdot_controller"),
    "dynamics":       ("svf.models.dynamics.kde_equipment","make_kde_equipment"),
    "thermal":        ("svf.models.thermal.thermal",     "make_thermal"),
    "pcdu":           ("svf.models.eps.pcdu",            "make_pcdu"),
    "sbt":            ("svf.models.ttc.sbt",             "make_sbt"),
}

_BUS_REGISTRY: dict[str, tuple[str, str]] = {
    "mil1553":    ("svf.mil1553", "Mil1553Bus"),
    "spacewire":  ("svf.spw",    "SpwBus"),
    "can":        ("svf.can",    "CanBus"),
}


class SpacecraftConfigError(Exception):
    """Raised when spacecraft YAML is invalid."""


class SpacecraftLoader:
    """Loads a spacecraft simulation from a YAML configuration file."""

    @classmethod
    def load(
        cls,
        config_path: str | Path,
        participant: Optional[DomainParticipant] = None,
    ) -> SimulationMaster:
        """
        Load spacecraft configuration and return a ready SimulationMaster.

        Args:
            config_path: Path to spacecraft YAML file
            participant: Optional existing DDS participant

        Returns:
            Configured SimulationMaster ready to run
        """
        path = Path(config_path)
        if not path.exists():
            raise SpacecraftConfigError(
                f"Spacecraft config not found: {path}"
            )

        with open(path) as f:
            cfg = yaml.safe_load(f)

        spacecraft_name = cfg.get("spacecraft", "Unknown")
        logger.info(f"[spacecraft] Loading: {spacecraft_name}")

        # Shared infrastructure
        if participant is None:
            participant = DomainParticipant()
        store     = ParameterStore()
        cmd_store = CommandStore()
        sync      = DdsSyncProtocol(participant)

        # Simulation parameters
        sim_cfg    = cfg.get("simulation", {})
        dt         = float(sim_cfg.get("dt", 0.1))
        stop_time  = float(sim_cfg.get("stop_time", 60.0))
        seed       = sim_cfg.get("seed", None)
        realtime   = bool(sim_cfg.get("realtime", False))

        # Build equipment
        equipment_map: dict[str, Any] = {}
        models: list[Any] = []

        # OBSW / OBC emulator
        obc = cls._build_obc(
            cfg.get("obsw", {}), sync, store, cmd_store, path.parent
        )
        if obc is not None:
            equipment_map["obc"] = obc
            models.append(obc)

        # Equipment models
        for eq_cfg in cfg.get("equipment", []):
            eq_id   = eq_cfg["id"]
            model   = eq_cfg["model"]
            profile = eq_cfg.get("hardware_profile")
            eq_seed = eq_cfg.get("seed")

            eq = cls._build_equipment(
                eq_id, model, profile, eq_seed,
                sync, store, cmd_store
            )
            equipment_map[eq_id] = eq
            models.append(eq)
            logger.info(
                f"[spacecraft] Equipment: {eq_id} "
                f"({model}"
                f"{f' profile={profile}' if profile else ''})"
            )

        # Bus adapters
        for bus_cfg in cfg.get("buses", []):
            bus = cls._build_bus(bus_cfg, sync, store, cmd_store)
            if bus is not None:
                equipment_map[bus.bus_id] = bus
                models.append(bus)

        # Wiring
        wiring_cfg = cfg.get("wiring", {})
        auto_wire  = wiring_cfg.get("auto", True)
        overrides  = wiring_cfg.get("overrides", [])
        wiring     = cls._build_wiring(
            equipment_map, auto_wire, overrides, path.parent
        )

        # Tick source
        tick_source = (
            RealtimeTickSource() if realtime else SoftwareTickSource()
        )

        master = SimulationMaster(
            tick_source=tick_source,
            sync_protocol=sync,
            models=models,
            dt=dt,
            stop_time=stop_time,
            sync_timeout=10.0,
            command_store=cmd_store,
            param_store=store,
            wiring=wiring,
            seed=seed,
        )

        logger.info(
            f"[spacecraft] {spacecraft_name} configured: "
            f"{len(models)} models, dt={dt}s, stop={stop_time}s"
        )
        return master

    @classmethod
    def _build_obc(
        cls,
        obsw_cfg: dict[str, Any],
        sync: Any,
        store: ParameterStore,
        cmd_store: CommandStore,
        base_dir: Path,
    ) -> Optional[Any]:
        if not obsw_cfg:
            return None

        transport = obsw_cfg.get("type", "pipe")

        if transport == "socket":
            from svf.models.dhs.obc_emulator import OBCEmulatorAdapter
            host = obsw_cfg.get("host", "localhost")
            port = int(obsw_cfg.get("port", 3456))
            return OBCEmulatorAdapter(
                sim_path=None,
                sync_protocol=sync,
                store=store,
                command_store=cmd_store,
                socket_addr=(host, port),
                sync_timeout=10.0,
            )

        elif transport == "pipe":
            from svf.models.dhs.obc_emulator import OBCEmulatorAdapter
            binary = obsw_cfg.get("binary")
            if binary is None:
                raise SpacecraftConfigError(
                    "obsw.binary required for pipe transport"
                )
            binary_path = base_dir / binary
            if not binary_path.exists():
                binary_path = Path(binary)
            return OBCEmulatorAdapter(
                sim_path=binary_path,
                sync_protocol=sync,
                store=store,
                command_store=cmd_store,
                sync_timeout=10.0,
            )

        elif transport == "stub":
            from svf.models.dhs.obc_stub import ObcStub
            from svf.models.dhs.obc import ObcConfig
            return ObcStub(
                config=ObcConfig(),
                sync_protocol=sync,
                store=store,
                command_store=cmd_store,
            )

        raise SpacecraftConfigError(
            f"Unknown obsw.type: {transport}. "
            f"Expected: pipe | socket | stub"
        )

    @classmethod
    def _build_equipment(
        cls,
        eq_id:   str,
        model:   str,
        profile: Optional[str],
        seed:    Optional[int],
        sync:    Any,
        store:   ParameterStore,
        cmd_store: CommandStore,
    ) -> Any:
        if model not in _MODEL_REGISTRY:
            raise SpacecraftConfigError(
                f"Unknown model '{model}'. "
                f"Known: {sorted(_MODEL_REGISTRY.keys())}"
            )

        module_name, factory_name = _MODEL_REGISTRY[model]
        import importlib
        module  = importlib.import_module(module_name)
        factory = getattr(module, factory_name)

        # Build kwargs — only pass what the factory accepts
        import inspect
        sig    = inspect.signature(factory)
        kwargs: dict[str, Any] = {}
        if "hardware_profile" in sig.parameters and profile is not None:
            kwargs["hardware_profile"] = profile
        if "seed" in sig.parameters and seed is not None:
            kwargs["seed"] = seed

        eq = factory(sync, store, cmd_store, **kwargs)

        # Rename equipment_id to match YAML id
        if hasattr(eq, "_equipment_id"):
            eq._equipment_id = eq_id

        return eq

    @classmethod
    def _build_bus(
        cls,
        bus_cfg:   dict[str, Any],
        sync:      Any,
        store:     ParameterStore,
        cmd_store: CommandStore,
    ) -> Optional[Any]:
        bus_type = bus_cfg.get("type")
        bus_id   = bus_cfg.get("id", bus_type)

        if bus_type not in _BUS_REGISTRY:
            raise SpacecraftConfigError(
                f"Unknown bus type '{bus_type}'. "
                f"Known: {sorted(_BUS_REGISTRY.keys())}"
            )

        module_name, class_name = _BUS_REGISTRY[bus_type]
        import importlib
        module   = importlib.import_module(module_name)
        bus_cls  = getattr(module, class_name)

        if bus_type == "mil1553":
            from svf.mil1553 import SubaddressMapping
            rt_count = int(bus_cfg.get("rt_count", 8))
            mappings_1553 = []
            for m in bus_cfg.get("mappings", []):
                mappings_1553.append(SubaddressMapping(
                    rt_address=int(m["rt"]),
                    subaddress=int(m["sa"]),
                    parameter=m["parameter"],
                    direction=m["direction"],
                ))
            return bus_cls(
                bus_id=bus_id,
                rt_count=rt_count,
                mappings=mappings_1553,
                sync_protocol=sync,
                store=store,
                command_store=cmd_store,
            )

        elif bus_type == "spacewire":
            from svf.spw import SpwNode, RmapMapping
            nodes = [
                SpwNode(
                    logical_address=int(n["logical_address"], 0),
                    node_id=n["node_id"],
                    description=n.get("description", ""),
                )
                for n in bus_cfg.get("nodes", [])
            ]
            mappings = [
                RmapMapping(
                    logical_address=int(m["logical_address"], 0),
                    register_address=int(m["register"], 0),
                    parameter=m["parameter"],
                    transaction_type=m["transaction"],
                )
                for m in bus_cfg.get("mappings", [])
            ]
            return bus_cls(
                bus_id=bus_id,
                nodes=nodes,
                mappings=mappings,
                sync_protocol=sync,
                store=store,
                command_store=cmd_store,
            )

        elif bus_type == "can":
            from svf.can import CanMessage
            messages = [
                CanMessage(
                    can_id=int(m["can_id"], 0),
                    parameter=m["parameter"],
                    direction=m["direction"],
                    node_id=m["node_id"],
                    extended=bool(m.get("extended", False)),
                    dlc=int(m.get("dlc", 4)),
                )
                for m in bus_cfg.get("messages", [])
            ]
            return bus_cls(
                bus_id=bus_id,
                messages=messages,
                sync_protocol=sync,
                store=store,
                command_store=cmd_store,
            )

        return None

    @classmethod
    def _build_wiring(
        cls,
        equipment_map: dict[str, Any],
        auto_wire:     bool,
        overrides:     list[dict[str, Any]],
        base_dir:      Path,
    ) -> Optional[Any]:
        """Build wiring from auto-detection + overrides."""
        if not auto_wire and not overrides:
            return None

        connections = []

        if auto_wire:
            connections.extend(
                cls._auto_wire(equipment_map)
            )

        # Apply explicit overrides
        for override in overrides:
            from_parts = override["from"].split(".", 1)
            to_parts   = override["to"].split(".", 1)
            if len(from_parts) == 2 and len(to_parts) == 2:
                from svf.wiring import Connection
                connections.append(Connection(
                    from_equipment=from_parts[0],
                    from_port=from_parts[1],
                    to_equipment=to_parts[0],
                    to_port=to_parts[1],
                ))

        # Build a minimal wiring object
        from svf.wiring import WiringLoader
        return WiringLoader._connections_to_wiring(connections, equipment_map)

    @classmethod
    def _auto_wire(cls, equipment_map: dict[str, Any]) -> list[Any]:
        """
        Auto-wire matching OUT→IN port pairs by name.
        For each OUT port, find any IN port with the same name
        on a different equipment.
        """
        from svf.wiring import Connection

        # Collect all ports
        out_ports: dict[str, str] = {}
        in_ports:  dict[str, str] = {}

        for eq_id, eq in equipment_map.items():
            for port in eq.out_ports():
                out_ports[port.name] = eq_id
            for port in eq.in_ports():
                in_ports[port.name] = eq_id

        # Match OUT → IN by name
        connections = []
        for port_name, from_eq in out_ports.items():
            if port_name in in_ports:
                to_eq = in_ports[port_name]
                if from_eq != to_eq:
                    connections.append(Connection(
                        from_equipment=from_eq,
                        from_port=port_name,
                        to_equipment=to_eq,
                        to_port=port_name,
                    ))
                    logger.debug(
                        f"[auto-wire] {from_eq}.{port_name} "
                        f"→ {to_eq}.{port_name}"
                    )

        logger.info(
            f"[auto-wire] {len(connections)} connections inferred"
        )
        return connections
