"""
SVF Campaign Runner

Runs a collection of Procedure instances against a spacecraft
configuration and collects results with requirement traceability.

Usage:
    from svf.campaign.campaign_runner import CampaignRunner
    from svf.config.spacecraft import SpacecraftLoader

    runner = CampaignRunner.from_yaml("campaign.yaml")
    report = runner.run()
    report.print_summary()

Campaign YAML format:
    campaign: MySat-1 AOCS Validation
    spacecraft: spacecraft.yaml
    procedures:
      - tests/procedures/test_bdot.py
      - tests/procedures/test_adcs.py

Implements: SVF-DEV-121
"""
from __future__ import annotations

import importlib.util
import inspect
import logging
import time
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Type

import yaml

from svf.stores.command_store import CommandStore
from svf.stores.parameter_store import ParameterStore
from svf.campaign.procedure import Procedure, ProcedureResult, Verdict, StepResult
from svf.config.spacecraft import SpacecraftLoader

logger = logging.getLogger(__name__)


@dataclass
class CampaignReport:
    """
    Aggregated results from a complete campaign run.

    Produced by ``CampaignRunner.run()``. Contains per-procedure verdicts,
    pass/fail/error/inconclusive counts, total duration, declared mission
    requirements, and a ``to_dict()`` method for JSON serialisation.

    Use ``print_summary()`` to print a formatted table to stdout, or pass
    to ``generate_html_report()`` to produce a self-contained HTML report.
    """
    campaign_name:  str
    spacecraft:     str
    n_procedures:   int
    n_pass:         int
    n_fail:         int
    n_error:        int
    duration_s:     float
    n_inconclusive: int = 0
    results:              list[ProcedureResult] = field(default_factory=list)
    declared_requirements: list[str]            = field(default_factory=list)

    @property
    def pass_rate(self) -> float:
        return self.n_pass / self.n_procedures if self.n_procedures > 0 else 0.0

    @property
    def uncovered_requirements(self) -> list[str]:
        """Declared requirements with no covering procedure (any verdict)."""
        attempted = {r.requirement for r in self.results if r.requirement}
        return [req for req in self.declared_requirements if req not in attempted]

    def print_summary(self) -> None:
        print(f"\n{'='*60}")
        print(f"Campaign: {self.campaign_name}")
        print(f"Spacecraft: {self.spacecraft}")
        print(f"{'='*60}")
        print(f"Procedures: {self.n_procedures}")
        print(f"PASS:          {self.n_pass}")
        print(f"FAIL:          {self.n_fail}")
        print(f"ERROR:         {self.n_error}")
        print(f"INCONCLUSIVE:  {self.n_inconclusive}")
        print(f"Pass rate: {self.pass_rate*100:.1f}%")
        print(f"Duration: {self.duration_s:.1f}s")
        if self.uncovered_requirements:
            print(f"\nUNCOVERED requirements ({len(self.uncovered_requirements)}):")
            for req in self.uncovered_requirements:
                print(f"  {req}")
        print(f"{'='*60}")
        print(f"\n{'ID':<20} {'Verdict':<14} {'Requirement':<20} Title")
        print("-"*72)
        for r in self.results:
            print(
                f"{r.procedure_id:<20} "
                f"{r.verdict.value:<14} "
                f"{r.requirement:<20} "
                f"{r.title}"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "campaign": self.campaign_name,
            "spacecraft": self.spacecraft,
            "n_procedures": self.n_procedures,
            "n_inconclusive": self.n_inconclusive,
            "pass_rate": self.pass_rate,
            "duration_s": self.duration_s,
            "declared_requirements": self.declared_requirements,
            "uncovered_requirements": self.uncovered_requirements,
            "results": [
                {
                    "id": r.procedure_id,
                    "title": r.title,
                    "requirement": r.requirement,
                    "verdict": r.verdict.value,
                    "duration_s": r.duration_s,
                    "error": r.error,
                    "steps": [
                        {
                            "name": s.step_name,
                            "verdict": s.verdict.value,
                            "detail": s.detail,
                        }
                        for s in r.steps
                    ],
                }
                for r in self.results
            ],
        }


class CampaignRunner:
    """
    Runs a collection of ``Procedure`` instances against a spacecraft.

    Each procedure gets a **fresh spacecraft simulation** — state does not
    carry over between procedures. A failure or error in one procedure does
    not stop the campaign.

    The typical entry point is ``from_yaml()``, which reads a campaign YAML
    and discovers ``Procedure`` subclasses from the referenced Python files.

    Example::

        runner = CampaignRunner.from_yaml("mission_mysat1/campaigns/aocs_campaign.yaml")
        report = runner.run()
        report.print_summary()

    Or via the CLI::

        svf campaign mission_mysat1/campaigns/aocs_campaign.yaml --report

    Implements: SVF-DEV-121
    """
    def __init__(
        self,
        campaign_name:  str,
        spacecraft_cfg: str | Path,
        procedures:     list[Type[Procedure]],
        declared_requirements: Optional[list[str]] = None,
    ) -> None:
        self._campaign_name  = campaign_name
        self._spacecraft_cfg = Path(spacecraft_cfg)
        self._procedures     = procedures
        self._declared_requirements: list[str] = declared_requirements or []

    @classmethod
    def from_yaml(cls, campaign_path: str | Path) -> "CampaignRunner":
        """
        Load a ``CampaignRunner`` from a campaign YAML file.

        The YAML must use the M20 format::

            campaign: MySat-1 AOCS Validation
            spacecraft: spacecraft.yaml   # relative to campaign file
            procedures:
              - procedures/aocs_procedures.py

        All ``Procedure`` subclasses found in the listed Python files are
        loaded and will be run in the order they are declared in the file.

        Args:
            campaign_path: Path to the campaign YAML file.

        Returns:
            Configured ``CampaignRunner`` ready to call ``run()``.

        Raises:
            FileNotFoundError: If the campaign file does not exist.
            ValueError: If the file uses the old pre-M20 pytest format.
        """
        path = Path(campaign_path)
        if not path.exists():
            raise FileNotFoundError(f"Campaign file not found: {path}")

        with open(path) as f:
            cfg = yaml.safe_load(f)

        # Detect old pre-M20 campaign format
        if "campaign_id" in cfg or "test_cases" in cfg:
            raise ValueError(
                f"{path.name} uses the old pytest-based campaign format "
                f"(campaign_id/test_cases). "
                f"Run these with: pytest tests/spacecraft/ -v\n"
                f"For svf campaign, use the M20 format with 'campaign:' "
                f"and 'procedures:' fields pointing to Python Procedure files."
            )

        campaign_name  = cfg.get("campaign", "Unnamed Campaign")
        spacecraft_cfg = cfg.get("spacecraft", "spacecraft.yaml")
        procedure_files = cfg.get("procedures", [])
        declared_requirements: list[str] = cfg.get("requirements", [])

        # Resolve spacecraft path relative to campaign file
        sc_path = path.parent / spacecraft_cfg

        # Load procedure classes from files
        procedures: list[Type[Procedure]] = []
        for proc_file in procedure_files:
            proc_path = path.parent / proc_file
            procs = cls._load_procedures_from_file(proc_path)
            procedures.extend(procs)
            logger.info(
                f"[campaign] Loaded {len(procs)} procedures "
                f"from {proc_path.name}"
            )

        return cls(campaign_name, sc_path, procedures, declared_requirements)

    @staticmethod
    def _load_procedures_from_file(
        path: Path,
    ) -> list[Type[Procedure]]:
        """
        Discover and return all ``Procedure`` subclasses in a Python file.

        Classes are returned in the order ``inspect.getmembers()`` yields them
        (alphabetical by class name). To control execution order, prefix class
        names accordingly (e.g. ``Act1_NominalOps``, ``Act2_FaultCascade``).

        Args:
            path: Path to a Python file containing ``Procedure`` subclasses.

        Returns:
            List of ``Procedure`` subclass types, deduplicated.

        Raises:
            ImportError: If the file cannot be loaded.
        """
        spec = importlib.util.spec_from_file_location(path.stem, path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot load {path}")
        module = importlib.util.module_from_spec(spec)
        import sys
        sys.modules[path.stem] = module
        spec.loader.exec_module(module)

        procedures = []
        seen: set[str] = set()
        for name, obj in inspect.getmembers(module, inspect.isclass):
            if not (issubclass(obj, Procedure) and obj is not Procedure):
                continue
            # Only include classes defined in this module
            if obj.__module__ != path.stem:
                continue
            # Avoid duplicates
            class_key = f"{obj.__module__}.{obj.__qualname__}"
            if class_key in seen:
                continue
            seen.add(class_key)
            procedures.append(obj)
        return procedures

    def run(
        self,
        output_path: Optional[Path] = None,
    ) -> CampaignReport:
        """
        Run all procedures in sequence and return the campaign report.

        Each procedure runs against a fresh spacecraft simulation instance.
        The simulation runs in a background thread; the procedure runs in the
        main thread and controls it via ``ProcedureContext``.

        A ``ProcedureError`` produces a FAIL verdict. Any other exception
        produces an ERROR verdict. Neither stops the campaign.

        Args:
            output_path: Optional path to write the report JSON. If None,
                         no JSON is written.

        Returns:
            ``CampaignReport`` with per-procedure results and summary stats.
        """
        logger.info(
            f"[campaign] Starting: {self._campaign_name} "
            f"({len(self._procedures)} procedures)"
        )

        results: list[ProcedureResult] = []
        t_start = time.monotonic()

        for proc_cls in self._procedures:
            # Reload spacecraft for each procedure — fresh simulation state
            fresh_master = SpacecraftLoader.load(self._spacecraft_cfg)
            fresh_store     = fresh_master._param_store
            fresh_cmd_store = fresh_master._command_store
            if fresh_store is None:
                fresh_store = ParameterStore()
            if fresh_cmd_store is None:
                fresh_cmd_store = CommandStore()

            proc = proc_cls()
            logger.info(
                f"[campaign] Running: {proc.id or proc_cls.__name__}"
            )

            # Run simulation in background thread
            sim_error: list[Exception] = []

            def _run_sim() -> None:
                try:
                    fresh_master.run()
                except Exception as e:
                    sim_error.append(e)

            sim_thread = threading.Thread(target=_run_sim, daemon=True)
            sim_thread.start()

            # Wait for simulation to start and stabilise
            import time as _time
            deadline = _time.monotonic() + 10.0
            last_t = -1.0
            stable_count = 0
            while _time.monotonic() < deadline:
                if sim_error:
                    break
                entry = fresh_store.read("svf.sim_time")
                cur_t = entry.value if entry is not None else -1.0
                if cur_t >= 0.0:
                    # Sim has started successfully, release the Procedure
                    break
                _time.sleep(0.01)

            if sim_error:
                results.append(ProcedureResult(
                    procedure_id=proc.id or proc_cls.__name__,
                    title=proc.title or proc_cls.__name__,
                    requirement=proc.requirement,
                    verdict=Verdict.ERROR,
                    duration_s=0.0,
                    error=f"Simulation failed to start: {sim_error[0]}",
                ))
                logger.error(
                    f"[campaign] {proc.id}: simulation error: {sim_error[0]}"
                )
                continue

            result = proc.execute(fresh_master, fresh_store, fresh_cmd_store)
            results.append(result)

            # Stop simulation after procedure completes
            fresh_master.stop()
            sim_thread.join(timeout=2.0)

            logger.info(
                f"[campaign] {proc.id}: {result.verdict.value} "
                f"({result.duration_s:.1f}s)"
            )

        duration = time.monotonic() - t_start

        report = CampaignReport(
            campaign_name=self._campaign_name,
            spacecraft=str(self._spacecraft_cfg.name),
            n_procedures=len(results),
            n_pass=sum(1 for r in results if r.verdict == Verdict.PASS),
            n_fail=sum(1 for r in results if r.verdict == Verdict.FAIL),
            n_error=sum(1 for r in results if r.verdict == Verdict.ERROR),
            n_inconclusive=sum(1 for r in results if r.verdict == Verdict.INCONCLUSIVE),
            duration_s=duration,
            results=results,
            declared_requirements=list(self._declared_requirements),
        )

        report.print_summary()

        if output_path is not None:
            import json
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                json.dumps(report.to_dict(), indent=2)
            )
            logger.info(f"[campaign] Results saved to {output_path}")

        return report
