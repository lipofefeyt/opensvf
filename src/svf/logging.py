"""
SVF CSV Logger
Records FMU output variables to a timestamped CSV file for each simulation run.
Implements: SVF-DEV-005
"""

from __future__ import annotations

import csv
import logging
from datetime import datetime
from io import TextIOWrapper
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class CsvLogger:
    """
    Records simulation outputs to a timestamped CSV file.

    Usage:
        csv_logger = CsvLogger(output_dir="results", run_id="my_run")
        csv_logger.open(variable_names=["counter", "voltage"])
        csv_logger.record(time=0.1, outputs={"counter": 0.1, "voltage": 3.3})
        csv_logger.close()

    Or as a context manager:
        with CsvLogger(output_dir="results", run_id="my_run") as csv_logger:
            csv_logger.open(variable_names=["counter"])
            csv_logger.record(time=0.1, outputs={"counter": 0.1})
    """

    def __init__(
        self,
        output_dir: str | Path = "results",
        run_id: str = "run",
    ) -> None:
        self.output_dir = Path(output_dir)
        self.run_id = run_id
        self._file: Optional[TextIOWrapper] = None
        self._writer: Optional[csv.DictWriter[str]] = None
        self._path: Optional[Path] = None

    def open(self, variable_names: list[str]) -> None:
        """
        Open the CSV file and write the header row.
        File is named: {run_id}_{timestamp}.csv
        """
        self.output_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._path = self.output_dir / f"{self.run_id}_{timestamp}.csv"

        self._file = open(self._path, "w", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(
            self._file,
            fieldnames=["time"] + variable_names,
        )
        self._writer.writeheader()
        logger.info(f"CSV logger opened: {self._path}")

    def record(self, time: float, outputs: dict[str, float]) -> None:
        """
        Write one row to the CSV: simulation time + all output values.
        Raises RuntimeError if called before open().
        """
        if self._writer is None:
            raise RuntimeError("CsvLogger is not open. Call open() first.")
        row: dict[str, float] = {"time": round(time, 9)} | outputs
        self._writer.writerow(row)

    def close(self) -> None:
        """
        Flush and close the CSV file.
        Safe to call even if open() was never called.
        """
        if self._file is not None:
            self._file.flush()
            self._file.close()
            self._file = None
            self._writer = None
            logger.info(f"CSV logger closed: {self._path}")

    @property
    def path(self) -> Optional[Path]:
        """Path to the current CSV file, or None if not open."""
        return self._path

    def __enter__(self) -> "CsvLogger":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()