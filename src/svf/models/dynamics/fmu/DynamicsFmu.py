from __future__ import annotations
import os
from pathlib import Path
import fmpy

class DynamicsFmu:
    """Wrapper for the SpacecraftDynamics FMI 2.0 Co-Simulation FMU."""

    def __init__(self, initial_omega: list[float] | None = None) -> None:
        # Robust path discovery: find repo root relative to this file
        current_file = Path(__file__).resolve()
        repo_root = current_file.parents[5]
        self.fmu_path = str(repo_root / "bin" / "SpacecraftDynamics.fmu")
        
        if not os.path.exists(self.fmu_path):
            # Fallback for CI environments
            self.fmu_path = str(Path(os.getcwd()) / "bin" / "SpacecraftDynamics.fmu")

        self.unzipdir = fmpy.extract(self.fmu_path)
        model_desc = fmpy.read_model_description(self.fmu_path)
        self.fmu = fmpy.instantiate_fmu(
            unzipdir=self.unzipdir,
            model_description=model_desc,
            fmi_type="CoSimulation",
        )
        self.fmu.instantiate()
        self.fmu.setupExperiment(startTime=0.0)
        
        # VRs for SpacecraftDynamics.fmu
        self.vrs = {
            "tq_mtq_x": 0, "tq_mtq_y": 1, "tq_mtq_z": 2,
            "q_w": 3, "q_x": 4, "q_y": 5, "q_z": 6,
            "omega_x": 7, "omega_y": 8, "omega_z": 9,
            "b_field_x": 10, "b_field_y": 11, "b_field_z": 12,
        }
        
        self.fmu.enterInitializationMode()
        if initial_omega is not None:
            self.fmu.setReal(
                [self.vrs["omega_x"], self.vrs["omega_y"], self.vrs["omega_z"]],
                initial_omega,
            )
        self.fmu.exitInitializationMode()

    def step_at(self, t: float, dt: float, mechanical_torque: list[float]) -> dict[str, list[float]]:
        self.fmu.setReal(
            [self.vrs["tq_mtq_x"], self.vrs["tq_mtq_y"], self.vrs["tq_mtq_z"]],
            mechanical_torque,
        )
        self.fmu.doStep(currentCommunicationPoint=t, communicationStepSize=dt)
        q = self.fmu.getReal([self.vrs["q_w"], self.vrs["q_x"], self.vrs["q_y"], self.vrs["q_z"]])
        w = self.fmu.getReal([self.vrs["omega_x"], self.vrs["omega_y"], self.vrs["omega_z"]])
        b = self.fmu.getReal([self.vrs["b_field_x"], self.vrs["b_field_y"], self.vrs["b_field_z"]])
        return {"attitude": list(q), "omega": list(w), "b_field": list(b)}

    def step(self, dt: float, mechanical_torque: list[float], _t: float = 0.0) -> dict[str, list[float]]:
        return self.step_at(t=_t, dt=dt, mechanical_torque=mechanical_torque)
