"""
Spacecraft Dynamics FMU Model.

This module provides the FMU wrapper for the 6-DOF Kinematics and Dynamics Engine (KDE).
It interfaces with the compiled C++ SpacecraftDynamics.fmu binary to provide high-fidelity
physics simulation for the OpenSVF platform.
"""

import fmpy
import os
from typing import Dict, List

class DynamicsFmu:
    """
    Wrapper class for the Spacecraft Dynamics FMU.
    
    Handles the extraction, instantiation, and stepping of the FMI 2.0 Co-Simulation binary.
    
    Attributes:
        fmu_path (str): Absolute path to the compiled .fmu artifact.
        unzipdir (str): Temporary directory where the FMU is extracted.
        vrs (Dict[str, int]): Dictionary mapping variable names to their FMI value references.
    """

    def __init__(self) -> None:
        """Initializes the FMI environment and loads the XML model description."""
        current_dir = os.path.dirname(os.path.abspath(__file__))
        self.fmu_path = os.path.join(current_dir, '..', '..', '..', '..', 'models', 'fmu', 'SpacecraftDynamics.fmu')
        
        self.unzipdir = fmpy.extract(self.fmu_path)
        model_desc = fmpy.read_model_description(self.fmu_path)
        
        self.fmu = fmpy.instantiate_fmu(
            unzipdir=self.unzipdir,
            model_description=model_desc,
            fmi_type='CoSimulation'
        )
        self._setup_fmu()
        self._map_value_references()

    def _setup_fmu(self) -> None:
        """Configures the initial experiment state and enters Co-Simulation mode."""
        self.fmu.instantiate()
        self.fmu.setupExperiment(startTime=0.0)
        self.fmu.enterInitializationMode()
        self.fmu.exitInitializationMode()

    def _map_value_references(self) -> None:
        """Hardcodes the FMI value references to match the modelDescription.xml."""
        self.vrs = {
            'tq_mtq_x': 0, 'tq_mtq_y': 1, 'tq_mtq_z': 2,
            'q_w': 3, 'q_x': 4, 'q_y': 5, 'q_z': 6,
            'omega_x': 7, 'omega_y': 8, 'omega_z': 9,
            'b_field_x': 10, 'b_field_y': 11, 'b_field_z': 12
        }

    def step(self, dt: float, mechanical_torque: List[float]) -> Dict[str, List[float]]:
        """
        Advances the 6-DOF physics engine by a given timestep.

        Args:
            dt (float): The simulation step size in seconds.
            mechanical_torque (List[float]): A 3-element list [x, y, z] representing 
                                             the applied mechanical torque in Nm.

        Returns:
            Dict[str, List[float]]: A dictionary containing the updated state vectors:
                                    - 'attitude': Quaternion [w, x, y, z]
                                    - 'omega': Angular velocity [x, y, z] in rad/s
                                    - 'b_field': Environmental magnetic field [x, y, z] in Tesla
        """
        self.fmu.setReal([self.vrs['tq_mtq_x'], self.vrs['tq_mtq_y'], self.vrs['tq_mtq_z']], mechanical_torque)
        self.fmu.doStep(currentCommunicationPoint=0.0, communicationStepSize=dt)
        
        q = self.fmu.getReal([self.vrs['q_w'], self.vrs['q_x'], self.vrs['q_y'], self.vrs['q_z']])
        w = self.fmu.getReal([self.vrs['omega_x'], self.vrs['omega_y'], self.vrs['omega_z']])
        b = self.fmu.getReal([self.vrs['b_field_x'], self.vrs['b_field_y'], self.vrs['b_field_z']])
        
        return {'attitude': q, 'omega': w, 'b_field': b}