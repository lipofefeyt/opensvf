"""
SVF Wiring Loader
Parses equipment wiring YAML files into Connection objects.
Implements: SVF-DEV-004
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

from svf.equipment import Equipment

logger = logging.getLogger(__name__)


class WiringLoadError(Exception):
    """Raised when wiring YAML parsing or validation fails."""
    pass


@dataclass(frozen=True)
class Connection:
    """
    A single point-to-point connection between two equipment ports.

    Attributes:
        from_equipment: Source equipment ID
        from_port:      Source OUT port name
        to_equipment:   Destination equipment ID
        to_port:        Destination IN port name
        description:    Human-readable description of the connection
    """
    from_equipment: str
    from_port: str
    to_equipment: str
    to_port: str
    description: str = ""

    def __str__(self) -> str:
        return (
            f"{self.from_equipment}.{self.from_port} -> "
            f"{self.to_equipment}.{self.to_port}"
        )


class WiringMap:
    """
    A validated set of equipment connections.
    Built by WiringLoader after validating against registered equipment.
    """

    def __init__(self, connections: list[Connection]) -> None:
        self._connections = list(connections)

    @property
    def connections(self) -> list[Connection]:
        return list(self._connections)

    def connections_from(self, equipment_id: str) -> list[Connection]:
        """All connections sourced from the given equipment."""
        return [
            c for c in self._connections
            if c.from_equipment == equipment_id
        ]

    def connections_to(self, equipment_id: str) -> list[Connection]:
        """All connections targeting the given equipment."""
        return [
            c for c in self._connections
            if c.to_equipment == equipment_id
        ]

    def __len__(self) -> int:
        return len(self._connections)

    def __repr__(self) -> str:
        return f"WiringMap({len(self._connections)} connections)"


class WiringLoader:
    """
    Parses a wiring YAML file into a validated WiringMap.

    YAML format:
        connections:
          - from: equipment_id.port_name
            to:   equipment_id.port_name
            description: Optional human-readable description

    Usage:
        equipment = {"eps": FmuEquipment(...), "pcdu": FmuEquipment(...)}
        loader = WiringLoader(equipment)
        wiring = loader.load(Path("srdb/wiring/eps_wiring.yaml"))
    """

    def __init__(self, equipment: Mapping[str, Equipment]) -> None:
        self._equipment = equipment

    def load(self, path: Path) -> WiringMap:
        """
        Load and validate a wiring YAML file.

        Raises WiringLoadError on any schema or validation error.
        """
        logger.info(f"Loading wiring: {path}")

        if not path.exists():
            raise WiringLoadError(f"Wiring file not found: {path}")

        try:
            with open(path, encoding="utf-8") as f:
                raw = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise WiringLoadError(f"{path}: YAML parse error: {e}") from e

        if not isinstance(raw, dict):
            raise WiringLoadError(
                f"{path}: YAML root must be a mapping"
            )

        raw_connections = raw.get("connections", [])
        if not isinstance(raw_connections, list):
            raise WiringLoadError(
                f"{path}: 'connections' must be a list"
            )

        connections: list[Connection] = []
        seen: set[tuple[str, str, str, str]] = set()

        for i, entry in enumerate(raw_connections):
            conn = self._parse_connection(entry, i, path)

            # Check for duplicate connections
            key = (conn.from_equipment, conn.from_port,
                   conn.to_equipment, conn.to_port)
            if key in seen:
                raise WiringLoadError(
                    f"{path}: duplicate connection at index {i}: {conn}"
                )
            seen.add(key)
            connections.append(conn)

        logger.info(f"Loaded {len(connections)} connections from {path.name}")
        return WiringMap(connections)

    def _parse_connection(
        self,
        entry: Any,
        index: int,
        source: Path,
    ) -> Connection:
        """Parse and validate a single connection entry."""
        if not isinstance(entry, dict):
            raise WiringLoadError(
                f"{source}: connection at index {index} must be a mapping"
            )

        for field in ["from", "to"]:
            if field not in entry:
                raise WiringLoadError(
                    f"{source}: connection at index {index} "
                    f"is missing required field '{field}'"
                )

        from_eq, from_port = self._parse_endpoint(
            entry["from"], "from", index, source
        )
        to_eq, to_port = self._parse_endpoint(
            entry["to"], "to", index, source
        )

        # Validate source equipment and port exist
        if from_eq not in self._equipment:
            raise WiringLoadError(
                f"{source}: connection {index}: "
                f"unknown source equipment '{from_eq}'"
            )
        eq = self._equipment[from_eq]
        if from_port not in eq.ports:
            raise WiringLoadError(
                f"{source}: connection {index}: "
                f"unknown port '{from_port}' on equipment '{from_eq}'"
            )
        from svf.equipment import PortDirection
        if eq.ports[from_port].direction != PortDirection.OUT:
            raise WiringLoadError(
                f"{source}: connection {index}: "
                f"'{from_eq}.{from_port}' is an IN port — "
                f"connections must start from OUT ports"
            )

        # Validate destination equipment and port exist
        if to_eq not in self._equipment:
            raise WiringLoadError(
                f"{source}: connection {index}: "
                f"unknown destination equipment '{to_eq}'"
            )
        eq = self._equipment[to_eq]
        if to_port not in eq.ports:
            raise WiringLoadError(
                f"{source}: connection {index}: "
                f"unknown port '{to_port}' on equipment '{to_eq}'"
            )
        if eq.ports[to_port].direction != PortDirection.IN:
            raise WiringLoadError(
                f"{source}: connection {index}: "
                f"'{to_eq}.{to_port}' is an OUT port — "
                f"connections must end at IN ports"
            )

        return Connection(
            from_equipment=from_eq,
            from_port=from_port,
            to_equipment=to_eq,
            to_port=to_port,
            description=str(entry.get("description", "")),
        )

    def _parse_endpoint(
        self,
        value: Any,
        field: str,
        index: int,
        source: Path,
    ) -> tuple[str, str]:
        """
        Parse 'equipment_id.port_name' endpoint string.
        Returns (equipment_id, port_name).
        """
        if not isinstance(value, str):
            raise WiringLoadError(
                f"{source}: connection {index}: "
                f"'{field}' must be a string"
            )
        parts = value.split(".", 1)
        if len(parts) != 2 or not parts[0] or not parts[1]:
            raise WiringLoadError(
                f"{source}: connection {index}: "
                f"'{field}' must be 'equipment_id.port_name', got '{value}'"
            )
        return parts[0], parts[1]
