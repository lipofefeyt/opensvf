# OpenSVF

Standards-based Software Validation Facility for spacecraft applications.

Simulation, test orchestration, and requirements traceability in one open-core toolchain.

## What's new in v0.2

**OBCEmulatorAdapter** (`src/svf/models/obc_emulator.py`) — closes the loop between OpenSVF and [openobsw](https://github.com/lipofefeyt/openobsw). The real OBSW binary runs as a subprocess, driven by the simulation master via a binary pipe protocol. Drop-in replacement for `ObcStub` at the composition root.

```python
# Before — simulated OBC:
obc = ObcStub(config=ObcConfig(...), rules=[...], ...)

# After — real OBSW under test:
from svf.models.obc_emulator import OBCEmulatorAdapter
obc = OBCEmulatorAdapter(sim_path="path/to/obsw_sim", ...)
```

Protocol (stdin/stdout binary pipe):
- **stdin**: `[uint16 BE length][TC frame bytes]`
- **stdout**: `[uint16 BE length][TM packet bytes]` + `[0xFF]` sync byte per cycle

The `0xFF` sync byte drives SimulationMaster lockstep — one OBC control cycle per simulation tick.

## Quick start

```bash
git clone https://github.com/lipofefeyt/opensvf
cd opensvf
pip install -e ".[dev]"
pytest
```

## Running the OBC emulator tests

Build `obsw_sim` from [openobsw](https://github.com/lipofefeyt/openobsw), copy the binary to the OpenSVF workspace, then:

```bash
OBSW_SIM=/path/to/obsw_sim pytest tests/test_obc_emulator_adapter.py -v
```

## Architecture

```
SimulationMaster
    ├── ReactionWheelEquipment   (FMU physics)
    ├── StarTrackerEquipment     (FMU physics)
    ├── PCDUEquipment            (FMU physics)
    ├── SBandTransponderEquipment(FMU physics)
    └── OBCEmulatorAdapter  ←── openobsw obsw_sim subprocess
            │  stdin: TC frames
            │  stdout: TM packets + 0xFF sync
            └── obsw_sim (real OBSW binary)
```

## Standards

ECSS-E-TM-10-21A system-level validation. Equipment models implement FMI 3.0.

## License

Apache 2.0