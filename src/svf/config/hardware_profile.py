"""
SVF Hardware Profile Loader

Loads equipment hardware profiles from YAML files.
Search order:
  1. srdb/hardware/ in the opensvf repo (bundled profiles)
  2. obsw-srdb package (if installed)
  3. Explicit hardware_dir argument

This means opensvf works out-of-the-box without obsw-srdb installed.

Implements: SVF-DEV-130
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

import yaml

logger = logging.getLogger(__name__)

# Path to bundled hardware profiles (relative to this file)
_BUNDLED_PROFILES_DIR = (
    Path(__file__).parent.parent.parent.parent / "srdb" / "hardware"
)


def load_hardware_profile(
    profile_name: str,
    hardware_dir: Optional[str | Path] = None,
) -> dict[str, Any]:
    """
    Load a hardware profile by name.

    Search order:
    1. Explicit hardware_dir (if provided)
    2. srdb/hardware/ in opensvf repo (bundled)
    3. obsw-srdb package (if installed)

    Args:
        profile_name: Profile ID without .yaml extension
                      e.g. "mag_default", "rw_sinclair_rw003"
        hardware_dir: Optional explicit directory to search first

    Returns:
        Dict of profile parameters

    Raises:
        FileNotFoundError if profile not found anywhere
    """
    filename = f"{profile_name}.yaml"

    # 1. Explicit hardware_dir
    if hardware_dir is not None:
        path = Path(hardware_dir) / filename
        if path.exists():
            return _load_yaml(path, profile_name, source="explicit")

    # 2. Bundled srdb/hardware/ in opensvf
    bundled_path = _BUNDLED_PROFILES_DIR / filename
    if bundled_path.exists():
        return _load_yaml(bundled_path, profile_name, source="bundled")

    # 3. obsw-srdb package
    try:
        import importlib.util
        if importlib.util.find_spec("obsw_srdb") is not None:
            from obsw_srdb.hardware import load_profile as _load_hw
            result: dict[str, Any] = _load_hw(profile_name)
            logger.info(
                f"[hw-profile] Loaded '{profile_name}' "
                f"from obsw-srdb package"
            )
            return result
    except Exception:
        pass

    raise FileNotFoundError(
        f"Hardware profile '{profile_name}' not found. "
        f"Searched: explicit dir, srdb/hardware/, obsw-srdb package. "
        f"Available bundled profiles: "
        f"{sorted(p.stem for p in _BUNDLED_PROFILES_DIR.glob('*.yaml'))}"
    )


def _load_yaml(
    path: Path,
    profile_name: str,
    source: str,
) -> dict[str, Any]:
    with open(path) as f:
        data = yaml.safe_load(f)
    params: dict[str, Any] = data.get("params", data)
    logger.info(
        f"[hw-profile] Loaded '{profile_name}' "
        f"from {source} ({path.name})"
    )
    return params
