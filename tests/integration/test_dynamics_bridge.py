"""
SVF Integration Test — Spacecraft Dynamics FMU Bridge
Exercises the FMPy bridge to the compiled C++ kinematics and dynamics engine.
Implements: KDE-001, KDE-002, KDE-003, SVF-DEV-061
"""

import pytest
from svf.models.fmu.DynamicsFmu import DynamicsFmu

@pytest.mark.requirement("KDE-001", "KDE-002", "KDE-003", "KDE-004", "SVF-DEV-061")
def test_physics_bridge() -> None:
    """
    Verifies that the Python ctypes bridge successfully passes float arrays to the 
    C++ FMI interface and retrieves the numerically integrated results.
    """
    dynamics = DynamicsFmu()
    
    # Verify B-Field is present (KDE-004)
    state = dynamics.step(dt=0.0, mechanical_torque=[0.0, 0.0, 0.0])
    assert "b_field" in state
    assert len(state["b_field"]) == 3

    # 1. Verify Initial State
    state = dynamics.step(dt=0.0, mechanical_torque=[0.0, 0.0, 0.0])
    assert state['omega'] == [0.0, 0.0, 0.0], "Initial angular velocity should be zero."
    
    # 2. Apply Y-axis torque for 1 second (10 ticks of 0.1s)
    for _ in range(10):
        state = dynamics.step(dt=0.1, mechanical_torque=[0.0, 1.0, 0.0])
        
    # 3. Verify State Evolution
    assert state['omega'][1] > 0.0, "Y-axis angular velocity should be positive!"
    assert state['attitude'][0] != 1.0, "Attitude quaternion should have evolved!"