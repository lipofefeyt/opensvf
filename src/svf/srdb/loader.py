"""
SVF SRDB Loader
Parses YAML parameter definition files into typed ParameterDefinition objects.
Supports baseline domain files and mission-level overrides.
Implements: SVF-DEV-092, SVF-DEV-093
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

import yaml

from svf.srdb.definitions import (
    Classification,
    Domain,
    Dtype,
    ParameterDefinition,
    PusMapping,
)

logger = logging.getLogger(__name__)


class SrdbLoadError(Exception):
    """Raised when SRDB YAML parsing or validation fails."""
    pass


class Srdb:
    """
    Loaded and validated spacecraft reference database.

    Holds the complete set of ParameterDefinition objects parsed
    from one or more YAML files. Immutable after construction —
    use SrdbLoader to build instances.

    Usage:
        loader = SrdbLoader()
        loader.load_baseline(Path("srdb/baseline/eps.yaml"))
        loader.load_mission(Path("srdb/missions/my_mission.yaml"))
        srdb = loader.build()

        defn = srdb.get("eps.battery.soc")
        all_tm = srdb.by_classification(Classification.TM)
        eps_params = srdb.by_domain(Domain.EPS)
    """

    def __init__(self, parameters: dict[str, ParameterDefinition]) -> None:
        self._parameters = dict(parameters)

    def get(self, name: str) -> Optional[ParameterDefinition]:
        """Return the definition for a parameter, or None if not found."""
        return self._parameters.get(name)

    def require(self, name: str) -> ParameterDefinition:
        """
        Return the definition for a parameter.
        Raises KeyError if not found.
        """
        defn = self._parameters.get(name)
        if defn is None:
            raise KeyError(f"Parameter '{name}' not found in SRDB")
        return defn

    def by_domain(self, domain: Domain) -> list[ParameterDefinition]:
        """All parameters belonging to the given domain."""
        return [p for p in self._parameters.values() if p.domain == domain]

    def by_classification(
        self, classification: Classification
    ) -> list[ParameterDefinition]:
        """All parameters with the given TM/TC classification."""
        return [
            p for p in self._parameters.values()
            if p.classification == classification
        ]

    def by_model(self, model_id: str) -> list[ParameterDefinition]:
        """All parameters owned by the given model."""
        return [
            p for p in self._parameters.values()
            if p.model_id == model_id
        ]

    @property
    def parameter_names(self) -> list[str]:
        """All parameter names in the database."""
        return list(self._parameters.keys())

    def __len__(self) -> int:
        return len(self._parameters)

    def __contains__(self, name: str) -> bool:
        return name in self._parameters


class SrdbLoader:
    """
    Builds an Srdb from one or more YAML files.

    Load order:
      1. load_baseline() — one or more domain baseline files
      2. load_mission()  — optional mission override (last-writer wins
                           for all fields except classification)

    Usage:
        loader = SrdbLoader()
        for f in Path("srdb/baseline").glob("*.yaml"):
            loader.load_baseline(f)
        loader.load_mission(Path("srdb/missions/my_mission.yaml"))
        srdb = loader.build()
    """

    def __init__(self) -> None:
        self._baseline: dict[str, ParameterDefinition] = {}
        self._mission_overrides: dict[str, dict[str, Any]] = {}

    def load_baseline(self, path: Path) -> None:
        """
        Load a domain baseline YAML file.
        Raises SrdbLoadError on any schema or validation error.
        """
        logger.info(f"Loading SRDB baseline: {path}")
        raw = self._read_yaml(path)
        parameters = raw.get("parameters", {})
        if not isinstance(parameters, dict):
            raise SrdbLoadError(
                f"{path}: 'parameters' key must be a mapping, got "
                f"{type(parameters).__name__}"
            )

        for name, fields in parameters.items():
            if name in self._baseline:
                raise SrdbLoadError(
                    f"{path}: duplicate parameter name '{name}' — "
                    f"already defined in a previously loaded baseline"
                )
            defn = self._parse_definition(name, fields, path)
            self._baseline[name] = defn

        logger.info(
            f"Loaded {len(parameters)} parameters from {path.name}"
        )

    def load_mission(self, path: Path) -> None:
        """
        Load a mission-level YAML override file.

        Mission overrides are applied on top of baselines at build() time.
        New parameters not in any baseline are added.
        Existing parameters may have any field overridden except
        classification — attempting to change classification raises
        SrdbLoadError.
        """
        logger.info(f"Loading SRDB mission overrides: {path}")
        raw = self._read_yaml(path)
        parameters = raw.get("parameters", {})
        if not isinstance(parameters, dict):
            raise SrdbLoadError(
                f"{path}: 'parameters' key must be a mapping"
            )

        for name, fields in parameters.items():
            if name in self._mission_overrides:
                raise SrdbLoadError(
                    f"{path}: duplicate parameter name '{name}' in mission file"
                )
            # Validate classification change attempt
            if name in self._baseline and "classification" in fields:
                baseline_cls = self._baseline[name].classification.value
                mission_cls = fields["classification"]
                if baseline_cls != mission_cls:
                    raise SrdbLoadError(
                        f"{path}: cannot change classification of '{name}' "
                        f"from {baseline_cls} to {mission_cls} — "
                        f"TM/TC classification is immutable after baselining"
                    )
            self._mission_overrides[name] = fields

        logger.info(
            f"Loaded {len(parameters)} mission overrides from {path.name}"
        )

    def build(self) -> Srdb:
        """
        Build the final Srdb by merging baselines and mission overrides.
        """
        merged: dict[str, ParameterDefinition] = dict(self._baseline)

        for name, fields in self._mission_overrides.items():
            if name in merged:
                # Merge override fields into existing baseline definition
                existing = merged[name]
                merged_fields = self._definition_to_dict(existing)
                merged_fields.update(fields)
                merged[name] = self._parse_definition(
                    name, merged_fields, Path("mission")
                )
            else:
                # New parameter — parse from scratch
                merged[name] = self._parse_definition(
                    name, fields, Path("mission")
                )

        logger.info(f"SRDB built: {len(merged)} parameters total")
        return Srdb(merged)

    # ── Private helpers ───────────────────────────────────────────────────────

    def _read_yaml(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            raise SrdbLoadError(f"SRDB file not found: {path}")
        try:
            with open(path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
            if not isinstance(data, dict):
                raise SrdbLoadError(
                    f"{path}: YAML root must be a mapping, got "
                    f"{type(data).__name__}"
                )
            return data
        except yaml.YAMLError as e:
            raise SrdbLoadError(f"{path}: YAML parse error: {e}") from e

    def _parse_definition(
        self,
        name: str,
        fields: Any,
        source: Path,
    ) -> ParameterDefinition:
        if not isinstance(fields, dict):
            raise SrdbLoadError(
                f"{source}: parameter '{name}' must be a mapping"
            )

        required = ["description", "unit", "dtype", "classification",
                    "domain", "model_id"]
        for field in required:
            if field not in fields:
                raise SrdbLoadError(
                    f"{source}: parameter '{name}' is missing "
                    f"required field '{field}'"
                )

        try:
            dtype = Dtype(fields["dtype"])
        except ValueError:
            raise SrdbLoadError(
                f"{source}: parameter '{name}' has invalid dtype "
                f"'{fields['dtype']}'. Must be one of: "
                f"{[d.value for d in Dtype]}"
            )

        try:
            classification = Classification(fields["classification"])
        except ValueError:
            raise SrdbLoadError(
                f"{source}: parameter '{name}' has invalid classification "
                f"'{fields['classification']}'. Must be TM or TC."
            )

        try:
            domain = Domain(fields["domain"])
        except ValueError:
            raise SrdbLoadError(
                f"{source}: parameter '{name}' has invalid domain "
                f"'{fields['domain']}'. Must be one of: "
                f"{[d.value for d in Domain]}"
            )

        valid_range: Optional[tuple[float, float]] = None
        if "valid_range" in fields and fields["valid_range"] is not None:
            r = fields["valid_range"]
            if not (isinstance(r, list) and len(r) == 2):
                raise SrdbLoadError(
                    f"{source}: parameter '{name}' valid_range must be "
                    f"a list of [min, max]"
                )
            valid_range = (float(r[0]), float(r[1]))

        pus: Optional[PusMapping] = None
        if "pus" in fields and fields["pus"] is not None:
            p = fields["pus"]
            try:
                pus = PusMapping(
                    apid=int(p["apid"], 0) if isinstance(p["apid"], str)
                         else int(p["apid"]),
                    service=int(p["service"]),
                    subservice=int(p["subservice"]),
                    parameter_id=int(p["parameter_id"], 0)
                    if isinstance(p["parameter_id"], str)
                    else int(p["parameter_id"]),
                )
            except (KeyError, TypeError, ValueError) as e:
                raise SrdbLoadError(
                    f"{source}: parameter '{name}' has invalid PUS "
                    f"mapping: {e}"
                ) from e

        try:
            return ParameterDefinition(
                name=name,
                description=str(fields["description"]),
                unit=str(fields["unit"]),
                dtype=dtype,
                classification=classification,
                domain=domain,
                model_id=str(fields["model_id"]),
                valid_range=valid_range,
                pus=pus,
            )
        except ValueError as e:
            raise SrdbLoadError(
                f"{source}: parameter '{name}': {e}"
            ) from e

    def _definition_to_dict(
        self, defn: ParameterDefinition
    ) -> dict[str, Any]:
        """Convert a ParameterDefinition back to a raw dict for merging."""
        d: dict[str, Any] = {
            "description": defn.description,
            "unit": defn.unit,
            "dtype": defn.dtype.value,
            "classification": defn.classification.value,
            "domain": defn.domain.value,
            "model_id": defn.model_id,
            "valid_range": list(defn.valid_range) if defn.valid_range else None,
        }
        if defn.pus is not None:
            d["pus"] = {
                "apid": defn.pus.apid,
                "service": defn.pus.service,
                "subservice": defn.pus.subservice,
                "parameter_id": defn.pus.parameter_id,
            }
        return d
