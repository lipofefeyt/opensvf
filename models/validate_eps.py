"""
Quick smoke test for the EPS FMU.
Runs two scenarios: sunlight charging and eclipse discharge.
"""
from pathlib import Path
from svf.simulation import SimulationMaster
from svf.software_tick import SoftwareTickSource
from svf.dds_sync import DdsSyncProtocol
from svf.fmu_adapter import FmuModelAdapter
from svf.parameter_store import ParameterStore
from svf.command_store import CommandStore
from cyclonedds.domain import DomainParticipant

FMU_PATH = Path(__file__).parent / "EpsFmu.fmu"

def run_scenario(name: str, illumination: float, load: float, stop_time: float) -> None:
    print(f"\n--- {name} ---")
    participant = DomainParticipant()
    store = ParameterStore()
    cmd_store = CommandStore()
    sync = DdsSyncProtocol(participant)

    cmd_store.inject("solar_illumination", illumination, source_id="smoke_test")
    cmd_store.inject("load_power", load, source_id="smoke_test")

    master = SimulationMaster(
        tick_source=SoftwareTickSource(),
        sync_protocol=sync,
        models=[FmuModelAdapter(FMU_PATH, "eps", sync, store, cmd_store)],
        dt=1.0,
        stop_time=stop_time,
        sync_timeout=10.0,
    )
    master.run()

    soc   = store.read("battery_soc")
    v_bus = store.read("bus_voltage")
    pgen  = store.read("generated_power")
    ichrg = store.read("charge_current")

    print(f"  SoC:              {soc.value:.3f}" if soc else "  SoC: None")
    print(f"  Bus voltage:      {v_bus.value:.3f} V" if v_bus else "  Bus voltage: None")
    print(f"  Generated power:  {pgen.value:.1f} W" if pgen else "  Generated power: None")
    print(f"  Charge current:   {ichrg.value:.3f} A" if ichrg else "  Charge current: None")

run_scenario("Full sun, 30W load, 60s",    illumination=1.0, load=30.0, stop_time=60.0)
run_scenario("Eclipse, 30W load, 60s",     illumination=0.0, load=30.0, stop_time=60.0)
run_scenario("Penumbra (50%), 30W, 60s",   illumination=0.5, load=30.0, stop_time=60.0)

print("\nEPS smoke test complete.")