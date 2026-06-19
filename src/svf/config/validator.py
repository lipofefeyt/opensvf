"""
SVF Spacecraft Pre-Flight Validator

Validates a spacecraft YAML configuration before any simulation infrastructure
(DDS, models, tick source) is instantiated. Surfaces all configuration errors
as a structured list rather than crashing at tick 0.

Checks performed:
  - Duplicate equipment IDs (SVF-DEV-152)
  - Bus address conflicts: CAN IDs, SpW logical addresses, 1553 RT/SA (SVF-DEV-153)
  - Wiring overrides that reference undefined equipment
  - OBT parameter init file: existence and parse validity

Usage:
    issues = SpacecraftValidator.from_file("spacecraft.yaml")
    if any(i.severity == "error" for i in issues):
        ...

    # Or raise on any error:
    SpacecraftValidator.validate_or_raise("spacecraft.yaml")

Implements: SVF-DEV-152, SVF-DEV-153
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ValidationIssue:
    """A single validation finding."""
    severity: str   # "error" | "warning"
    code: str       # machine-readable tag, e.g. "DUPLICATE_EQUIPMENT_ID"
    message: str    # human-readable description

    def __str__(self) -> str:
        return f"[{self.severity.upper()}] {self.code}: {self.message}"


class ValidationFailed(Exception):
    """Raised by validate_or_raise() when one or more errors are found."""

    def __init__(self, issues: list[ValidationIssue]) -> None:
        self.issues = issues
        errors = [i for i in issues if i.severity == "error"]
        lines = "\n".join(f"  {i}" for i in issues)
        super().__init__(
            f"{len(errors)} validation error(s):\n{lines}"
        )


class SpacecraftValidator:
    """
    Pre-flight validator that works on the raw spacecraft YAML dict.
    No DDS participant, no model imports, no tick source required.
    """

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    @classmethod
    def from_file(cls, path: str | Path) -> list[ValidationIssue]:
        """Parse YAML and validate. Returns all issues found."""
        import yaml
        path = Path(path)
        with open(path) as f:
            cfg = yaml.safe_load(f) or {}
        return cls()._run(cfg, path.parent)

    @classmethod
    def validate_or_raise(cls, path: str | Path) -> None:
        """Like from_file() but raises ValidationFailed if any errors exist."""
        issues = cls.from_file(path)
        errors = [i for i in issues if i.severity == "error"]
        if errors:
            raise ValidationFailed(issues)

    # ------------------------------------------------------------------ #
    # Internal orchestration                                               #
    # ------------------------------------------------------------------ #

    def _run(
        self, cfg: dict[str, Any], base_dir: Path
    ) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        self._check_duplicate_equipment_ids(cfg, issues)
        self._check_bus_address_conflicts(cfg, issues)
        self._check_wiring_overrides(cfg, issues)
        self._check_obt_param_file(cfg, base_dir, issues)
        return issues

    # ------------------------------------------------------------------ #
    # Individual checks                                                    #
    # ------------------------------------------------------------------ #

    def _check_duplicate_equipment_ids(
        self, cfg: dict[str, Any], issues: list[ValidationIssue]
    ) -> None:
        seen: set[str] = set()
        for eq in cfg.get("equipment", []):
            eq_id = eq.get("id")
            if not eq_id:
                continue
            if eq_id in seen:
                issues.append(ValidationIssue(
                    severity="error",
                    code="DUPLICATE_EQUIPMENT_ID",
                    message=f"Equipment id '{eq_id}' appears more than once.",
                ))
            seen.add(eq_id)

    def _check_bus_address_conflicts(
        self, cfg: dict[str, Any], issues: list[ValidationIssue]
    ) -> None:
        for bus in cfg.get("buses", []):
            bus_id   = bus.get("id", "<unnamed>")
            bus_type = bus.get("type", "")

            if bus_type == "can":
                self._check_can_conflicts(bus_id, bus, issues)
            elif bus_type == "spacewire":
                self._check_spw_conflicts(bus_id, bus, issues)
            elif bus_type == "mil1553":
                self._check_1553_conflicts(bus_id, bus, issues)

    def _check_can_conflicts(
        self,
        bus_id: str,
        bus: dict[str, Any],
        issues: list[ValidationIssue],
    ) -> None:
        seen: dict[Any, str] = {}
        for msg in bus.get("messages", []):
            can_id = msg.get("can_id")
            param  = msg.get("parameter", "?")
            if can_id is None:
                continue
            key = can_id
            if key in seen:
                issues.append(ValidationIssue(
                    severity="error",
                    code="BUS_ADDRESS_CONFLICT",
                    message=(
                        f"Bus '{bus_id}' (CAN): duplicate CAN ID "
                        f"{hex(can_id) if isinstance(can_id, int) else can_id!r} "
                        f" -  '{param}' conflicts with '{seen[key]}'."
                    ),
                ))
            else:
                seen[key] = param

    def _check_spw_conflicts(
        self,
        bus_id: str,
        bus: dict[str, Any],
        issues: list[ValidationIssue],
    ) -> None:
        seen: dict[Any, str] = {}
        for node in bus.get("nodes", []):
            raw_addr = node.get("logical_address")
            node_id  = node.get("node_id", "?")
            if raw_addr is None:
                continue
            addr = int(raw_addr, 0) if isinstance(raw_addr, str) else raw_addr
            if addr in seen:
                issues.append(ValidationIssue(
                    severity="error",
                    code="BUS_ADDRESS_CONFLICT",
                    message=(
                        f"Bus '{bus_id}' (SpaceWire): duplicate logical address "
                        f"{hex(addr)}  -  '{node_id}' conflicts with '{seen[addr]}'."
                    ),
                ))
            else:
                seen[addr] = node_id

    def _check_1553_conflicts(
        self,
        bus_id: str,
        bus: dict[str, Any],
        issues: list[ValidationIssue],
    ) -> None:
        seen: dict[tuple[int, int], str] = {}
        for mapping in bus.get("mappings", []):
            rt    = mapping.get("rt")
            sa    = mapping.get("sa")
            param = mapping.get("parameter", "?")
            if rt is None or sa is None:
                continue
            key = (int(rt), int(sa))
            if key in seen:
                issues.append(ValidationIssue(
                    severity="error",
                    code="BUS_ADDRESS_CONFLICT",
                    message=(
                        f"Bus '{bus_id}' (MIL-STD-1553): duplicate RT={key[0]} SA={key[1]} "
                        f" -  '{param}' conflicts with '{seen[key]}'."
                    ),
                ))
            else:
                seen[key] = param

    def _check_wiring_overrides(
        self, cfg: dict[str, Any], issues: list[ValidationIssue]
    ) -> None:
        valid_ids: set[str] = {
            eq["id"] for eq in cfg.get("equipment", []) if "id" in eq
        }
        for bus in cfg.get("buses", []):
            if "id" in bus:
                valid_ids.add(bus["id"])
        if cfg.get("obsw"):
            valid_ids.add("obc")

        for override in cfg.get("wiring", {}).get("overrides", []):
            for direction in ("from", "to"):
                ref = override.get(direction, "")
                eq_id = ref.split(".", 1)[0] if ref else ""
                if eq_id and eq_id not in valid_ids:
                    issues.append(ValidationIssue(
                        severity="error",
                        code="UNKNOWN_EQUIPMENT_REF",
                        message=(
                            f"Wiring override {direction}='{ref}': "
                            f"equipment '{eq_id}' is not defined."
                        ),
                    ))

    def _check_obt_param_file(
        self,
        cfg: dict[str, Any],
        base_dir: Path,
        issues: list[ValidationIssue],
    ) -> None:
        obt_path = cfg.get("simulation", {}).get("obt_init_file")
        if obt_path is None:
            return

        resolved = base_dir / obt_path
        if not resolved.exists():
            issues.append(ValidationIssue(
                severity="error",
                code="FILE_NOT_FOUND",
                message=(
                    f"simulation.obt_init_file: file not found: {resolved}"
                ),
            ))
            return

        try:
            from svf.sim.obt_param_file import ObtParamFile
            ObtParamFile.load(resolved)
        except ValueError as e:
            issues.append(ValidationIssue(
                severity="error",
                code="OBT_PARAM_FILE_INVALID",
                message=str(e),
            ))
