"""
SVF Deterministic Replay Support

Manages simulation seeds for exact reproduction of any run.

Usage:
    master = SimulationMaster(..., seed=42)
    # Seeds logged to results/seed.txt after run
    # Replay: SimulationMaster(..., seed=42)

Seed derivation:
    per_model_seed = derive_seed(master_seed, model_id)
    This is deterministic — same master seed always gives
    same per-model seeds regardless of model order.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def derive_seed(master_seed: int, model_id: str) -> int:
    """
    Derive a deterministic per-model seed from a master seed.

    Uses SHA-256 of (master_seed, model_id) to ensure:
    - Same master → same per-model seeds always
    - Different model_ids → different seeds (no correlation)
    - Changing one model doesn't affect others

    Args:
        master_seed: Master simulation seed
        model_id:    Equipment model_id string

    Returns:
        32-bit integer seed for random.Random()
    """
    h = hashlib.sha256(f"{master_seed}:{model_id}".encode()).digest()
    return int.from_bytes(h[:4], "big")


def generate_seed() -> int:
    """Generate a random master seed for non-reproducible runs."""
    import random
    return random.randint(0, 2**31 - 1)


class SeedManager:
    """
    Manages master seed and per-model seed derivation.

    Attach to SimulationMaster to enable deterministic replay.
    Logs seed manifest to results/ after each run for traceability.
    """

    def __init__(self, master_seed: Optional[int] = None) -> None:
        if master_seed is None:
            self._seed = generate_seed()
            logger.info(
                f"[replay] No seed provided — generated seed={self._seed}"
            )
        else:
            self._seed = master_seed
            logger.info(f"[replay] Using master seed={self._seed}")

        self._derived: dict[str, int] = {}

    @property
    def master_seed(self) -> int:
        return self._seed

    def seed_for(self, model_id: str) -> int:
        """Get deterministic seed for a specific model."""
        if model_id not in self._derived:
            self._derived[model_id] = derive_seed(self._seed, model_id)
        return self._derived[model_id]

    def save(self, results_dir: Path = Path("results")) -> None:
        """
        Save seed manifest to results/seed.json.
        Enables exact replay of any run.
        """
        results_dir.mkdir(parents=True, exist_ok=True)
        manifest = {
            "master_seed": self._seed,
            "derived_seeds": self._derived,
            "replay_command": f"Run with seed={self._seed}",
        }
        path = results_dir / "seed.json"
        path.write_text(json.dumps(manifest, indent=2))
        logger.info(f"[replay] Seed manifest saved to {path}")
        print(f"SVF seed: {self._seed}  (replay with seed={self._seed})")

    def __repr__(self) -> str:
        return f"SeedManager(master_seed={self._seed})"
