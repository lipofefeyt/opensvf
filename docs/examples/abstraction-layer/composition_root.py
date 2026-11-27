"""Build and run a simulation by hand: the composition root."""
from pathlib import Path

from cyclonedds.domain import DomainParticipant

from svf.ground.dds_sync import DdsSyncProtocol
from svf.models.aocs.magnetometer import make_magnetometer
from svf.models.aocs.reaction_wheel import make_reaction_wheel
from svf.sim.simulation import SimulationMaster
from svf.sim.software_tick import SoftwareTickSource
from svf.srdb.loader import SrdbLoader
from svf.stores.command_store import CommandStore
from svf.stores.parameter_store import ParameterStore


def main(srdb_dir: Path = Path("srdb/baseline")) -> float:
    # 1. Infrastructure: SRDB, stores, sync protocol
    loader = SrdbLoader()
    for baseline in sorted(srdb_dir.glob("*.yaml")):
        loader.load_baseline(baseline)
    srdb = loader.build()
    store = ParameterStore(srdb=srdb)
    cmd_store = CommandStore(srdb=srdb)
    sync = DdsSyncProtocol(DomainParticipant())

    # 2. Equipment
    rw1 = make_reaction_wheel(sync, store, cmd_store, equipment_id="rw1",
                              hardware_profile="rw_default")
    mag = make_magnetometer(sync, store, cmd_store, hardware_profile="mag_default")

    # 3. Simulation
    master = SimulationMaster(
        tick_source=SoftwareTickSource(),  # or RealtimeTickSource()
        sync_protocol=sync,                # or SharedMemorySyncProtocol(...)
        models=[rw1, mag],
        dt=0.1,
        stop_time=2.0,
        command_store=cmd_store,
        param_store=store,
    )
    cmd_store.inject("aocs.rw1.torque_cmd", 0.01, source_id="example")
    master.run()

    entry = store.read("aocs.rw1.speed")
    assert entry is not None
    return entry.value


if __name__ == "__main__":
    print(f"aocs.rw1.speed after 2 s: {main():.1f} rpm")
