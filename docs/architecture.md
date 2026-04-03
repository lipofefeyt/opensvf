# SVF Architecture

> **Status:** v1.1
> **Last updated:** 2026-03
> **Author:** lipofefeyt

---

## 1. Overview

The Software Validation Facility (SVF) is an open-core platform for the validation of spacecraft software and systems. It provides a simulation infrastructure, a communication bus, a spacecraft reference database, a component modelling framework, bus protocol adapters, PUS TM/TC support, and a test orchestration layer — designed to be standards-based, modular, and incrementally scalable.

From ECSS-E-TM-10-21A:

> *System modelling and simulation is a support activity to OBSW validation. The ability to inject failures in the models enables the user to trigger the OBSW monitoring processes as well as to exercise the FDIR mechanisms. Sometimes simpler so-called "model responders" may be sufficient to test the open-loop behaviour of the OBSW. The SVF is used repeatedly during the programme for each version of the onboard software and each version of the spacecraft database associated with it.*

OpenSVF implements this definition across four validation levels:

```
Level 1 — Model validation (M8/M9):     each subsystem verified in isolation
Level 2 — Interface validation (M6/M9): bus interfaces + full fault matrix
Level 3 — Integration validation (M10): models + interfaces + PUS chain
Level 4 — System validation (M11):      real OBSW binary under test via HIL
```

---

## 2. Design Principles

**Equipment as the universal model abstraction.**
Every spacecraft model — FMU, native Python, bus adapter, OBC, TTC, or real OBSW binary — is an `Equipment`. Equipment extends `ModelAdapter` so every model is directly driveable by `SimulationMaster`.

**Interface-typed ports.**
Equipment ports carry an `InterfaceType`. The `WiringLoader` validates compatibility at load time. You cannot wire a 1553 BC port to a SpaceWire node.

**Bus as Equipment.**
Every bus adapter extends `Bus` which extends `Equipment`. Buses have typed ports and built-in fault injection. `SimulationMaster` drives buses identically to any other Equipment.

**TM and TC are architecturally separate.**
`ParameterStore` holds telemetry (TM). `CommandStore` holds telecommands (TC). Never conflated.

**One data one source.**
Every parameter has exactly one authoritative definition in the SRDB.

**PUS as the commanding language.**
All ground-to-spacecraft commanding flows through PUS-C (ECSS-E-ST-70-41C).

**ObcInterface protocol — the HIL plug-in point.**
`TtcEquipment` accepts any `ObcInterface` implementation:
- `ObcEquipment` — simulated OBC
- `ObcStub` — configurable OBSW behaviour simulator
- `OBCEmulatorAdapter` — real OBSW binary under test

Swap at the composition root with one line. Nothing else changes.

**Port commands are consumed.**
One-shot commands (mode_cmd, watchdog_kick, dump_cmd) are consumed after processing. No sticky state.

**Requirements traceability from day one.**
Every test references a requirement. Every BASELINED requirement has a test. The traceability matrix is generated automatically after every CI run.

---

## 3. Layered Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    GROUND SEGMENT (M12)                         │
│         YAMCS | SCOS-2000 | XTCE export | MIB import            │
└──────────────────────────┬──────────────────────────────────────┘
                           │ PUS TC/TM bytes
┌──────────────────────────▼──────────────────────────────────────┐
│                    TTC EQUIPMENT                                 │
│  send_tc(PusTcPacket) → forwards to OBC via ObcInterface        │
│  get_tm_responses() ← exposes TM for test assertions            │
└──────────────────────────┬──────────────────────────────────────┘
                           │ ObcInterface
              ┌────────────┼────────────────────┐
              │            │                    │
┌─────────────▼──┐ ┌───────▼──────┐ ┌──────────▼──────────────┐
│ ObcEquipment   │ │  ObcStub     │ │  OBCEmulatorAdapter     │
│ Simulated OBC  │ │  Rule engine │ │  Real OBSW under test   │
│ M7/M8          │ │  M10         │ │  M11 ← YOU ARE HERE     │
│ PUS routing    │ │  Closed-loop │ │  obsw_sim binary        │
│ DHS state      │ │  FDIR rules  │ │  Pipe protocol          │
└────────────────┘ └──────────────┘ └─────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────────┐
│                    BUS ADAPTERS                                  │
│  Mil1553Bus: bc_in (MIL1553_BC) + rtN_out (MIL1553_RT)         │
│  BusFault: NO_RESPONSE | LATE_RESPONSE | BAD_PARITY | BUS_ERROR │
│  bus.{id}.fault.{target}.{type} via CommandStore                 │
└──────────────────────────┬──────────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────────┐
│                 EQUIPMENT & PORT LAYER                           │
│  Equipment(ModelAdapter): typed IN/OUT ports                    │
│  on_tick(): CommandStore → do_step() → ParameterStore           │
│  FmuEquipment | NativeEquipment | Bus(abstract)                 │
└──────┬──────────────────────┬───────────────────────────────────┘
       │                      │
┌──────▼──────┐  ┌────────────▼──────────────────────────────────┐
│ PARAMETER   │  │  COMMAND STORE                                 │
│ STORE (TM)  │  │  TC only — take() atomic                       │
│ SRDB keys   │  │  written by: inject, schedule, wiring, OBC     │
└──────┬──────┘  └────────────────────────────────────────────────┘
       │
┌──────▼──────────────────────────────────────────────────────────┐
│              SRDB | PUS TM/TC | DDS | Campaign | Plugin         │
└─────────────────────────────────────────────────────────────────┘
```

---

## 4. OBC Implementation Options

Three drop-in implementations of `ObcInterface`:

### ObcEquipment (M7/M8)
Simulated OBC. PUS TC routing + DHS state machine (mode FSM, OBT, watchdog, memory). Use for unit and integration testing without OBSW.

### ObcStub (M10)
Configurable OBSW behaviour simulator. Rule engine evaluates ParameterStore conditions and fires CommandStore actions each tick. Use for closed-loop Level 3/4 validation without a real OBSW binary.

```python
stub = ObcStub(config, sync, store, cmd_store, rules=[
    Rule(
        name="low_battery_safe",
        watch="eps.battery.soc",
        condition=lambda e: e is not None and e.value < 0.3,
        action=lambda cs, t: cs.inject("dhs.obc.mode_cmd", 0.0, t=t),
    ),
])
```

### OBCEmulatorAdapter (M11)
Real OBSW binary under test. Wraps `obsw_sim` as an Equipment. One OBC control cycle per SVF tick:

```
SVF tick → send TC frames to obsw_sim stdin → wait 0xFF sync byte
         → parse TM packets from stdout → update OUT ports
```

```python
obc = OBCEmulatorAdapter(
    sim_path="obsw_sim",
    sync_protocol=sync,
    store=store,
    command_store=cmd_store,
)
```

### Swapping implementations

```python
# Level 3 — simulated OBC
obc = ObcStub(config, sync, store, cmd_store, rules=[...])

# Level 4 — real OBSW under test (one line change)
obc = OBCEmulatorAdapter(sim_path="obsw_sim", sync_protocol=sync,
                         store=store, command_store=cmd_store)

# TtcEquipment accepts all three via ObcInterface protocol
ttc = TtcEquipment(obc, sync, store, cmd_store)
```

---

## 5. ObcInterface Protocol

```python
@runtime_checkable
class ObcInterface(Protocol):
    def receive_tc(self, raw_tc: bytes, t: float = 0.0) -> list[PusTmPacket]: ...
    def get_tm_queue(self) -> list[PusTmPacket]: ...
    def get_tm_by_service(self, service: int, subservice: int) -> list[PusTmPacket]: ...
```

All three OBC implementations satisfy this protocol. `TtcEquipment` accepts any `ObcInterface`.

---

## 6. OBCEmulatorAdapter — Wire Protocol

```
SVF → obsw_sim stdin:
  [uint16 BE length][TC frame bytes]   (one or more per tick)

obsw_sim → SVF stdout:
  [uint16 BE length][TM packet bytes]  (zero or more per cycle)
  [0xFF]                               (sync byte — end of cycle)
```

S5 events drive mode state in the adapter:
- `event_id=0x0002` → `MODE_SAFE`
- `event_id=0x0003` → `MODE_NOMINAL`

S17 ping sent as heartbeat every tick so `obsw_sim` never blocks.

---

## 7. Interface-Typed Port System

```python
class InterfaceType(enum.Enum):
    FLOAT       = "float"        # Default
    MIL1553_BC  = "mil1553_bc"   # 1553 Bus Controller
    MIL1553_RT  = "mil1553_rt"   # 1553 Remote Terminal
    SPACEWIRE   = "spacewire"    # SpaceWire node
    CAN         = "can"          # CAN node
    UART        = "uart"         # UART
    ANALOG      = "analog"       # Analog signal
    DIGITAL     = "digital"      # Digital signal
```

WiringLoader rejects mismatched interface types at load time.

---

## 8. Bus Protocol Architecture

```
Equipment (ABC)
    └── Bus (ABC)
            └── Mil1553Bus      — complete (M6)
            └── SpaceWireBus    — planned (M12)
            └── CanBus          — planned (M12)
```

Fault injection via `BusFault` or `CommandStore`:

```python
bus.inject_fault(BusFault(FaultType.NO_RESPONSE, "rt5", 5.0, t))
# or via svf_command_schedule:
(10.0, "bus.platform_1553.fault.rt5.no_response", 5.0)
```

---

## 9. PUS TM/TC Architecture

**Packet structure (ECSS-E-ST-70-41C):**
```
TC: [Primary 6B][DFH 5B][App Data][CRC-16 2B]
TM: [Primary 6B][DFH 10B][App Data][CRC-16 2B]
```

**Services implemented:**

| Service | Description |
|---|---|
| S1 | Request Verification (acceptance, completion, failure) |
| S3 | Housekeeping (define, enable/disable, TM(3,25), essential HK) |
| S5 | Event Reporting (severity 1-4) |
| S17 | Test (are-you-alive) |
| S20 | Parameter Management (set, get) |

---

## 10. Reference Equipment Library

| Equipment | Subsystem | Interface | Key Physics | Status |
|---|---|---|---|---|
| `ObcEquipment` | DHS | 1553 BC | Mode FSM, OBT, watchdog, PUS routing | M7/M8 |
| `ObcStub` | DHS | — | Rule engine, closed-loop FDIR | M10 |
| `OBCEmulatorAdapter` | DHS | binary pipe | Real OBSW under test | M11 |
| `TtcEquipment` | TTC | ObcInterface | TC/TM byte pipe | M7 |
| `make_reaction_wheel()` | AOCS | 1553 RT | Torque, friction, temperature | M6/M8 |
| `make_star_tracker()` | AOCS | SpW/1553 | Quaternion, noise, sun blinding | M8 |
| `make_sbt()` | TTC | UART | Carrier lock, mode FSM, bit rates | M8 |
| `make_pcdu()` | EPS | 1553/CAN | LCL switching, MPPT, UVLO | M9 |
| `EpsFmu` | EPS | FMI 3.0 | Solar array, Li-Ion battery, PCDU | M4 |

Full contracts: `docs/equipment-library.md`

---

## 11. Test Structure

```
tests/
├── unit/pus/        PUS TC/TM tests
├── unit/campaign/   Campaign manager tests
├── unit/            SVF platform tests
├── equipment/       Equipment contract + bus tests
├── integration/     SVF infrastructure tests
├── spacecraft/      Model behaviour + end-to-end + system tests
└── hardware/        HIL tests (require obsw_sim binary)
                     Run explicitly: pytest tests/hardware/ -v
```

---

## 12. Campaigns

| Campaign | Scenario | Level |
|---|---|---|
| `eps_validation.yaml` | EPS power system | 1 |
| `mil1553_validation.yaml` | 1553 bus + FDIR | 2 |
| `pus_validation.yaml` | PUS commanding chain | 3 |
| `platform_validation.yaml` | Full platform | 3 |
| `safe_mode_recovery.yaml` | Closed-loop recovery | 3/4 |
| `nominal_ops.yaml` | Nominal operations | 3/4 |
| `contact_pass.yaml` | Ground contact | 3/4 |
| `fdir_chain.yaml` | FDIR end-to-end | 3/4 |

---

## 13. Development Milestones

| Milestone | Objective | Status |
|---|---|---|
| M1-M5 | Core platform, campaigns, reporting | ✅ Done |
| M6 - Bus Protocols | 1553, fault injection | ✅ Done |
| M7 - PUS TM/TC | TC/TM packets, S1/3/5/17/20, OBC, TTC | ✅ Done |
| M8 - Equipment Interface Library | OBC/RW/ST/SBT/PCDU models | ✅ Done |
| M9 - Model & Interface Validation | Failure coverage, full fault matrix | ✅ Done |
| M10 - Integration & System Validation | OBC stub, closed-loop scenarios | ✅ Done |
| M11 - OBC Emulator Integration | OBCEmulatorAdapter, real OBSW | ✅ Done |
| M12 - Ground Segment | YAMCS, XTCE, MIB, SpW, CAN | Planned |