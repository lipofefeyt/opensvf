# Plug In Your Own Binary

Run your first campaign against your own C flight software binary in under 15 minutes.

---

## What you need

- Your flight software compiled as an x86\_64 (or aarch64) Linux executable
- Python 3.10+, `pip install opensvf`
- Your binary must implement the **SVF wire protocol** (described below — it's small)

If you don't have a binary yet, work through the [MySat-1 quickstart](quickstart-mysat1.md) first to learn the campaign runner with a stub OBC.

---

## Step 1 — Install

```bash
pip install opensvf
```

---

## Step 2 — Wire protocol (implement this in your binary)

OpenSVF and your binary communicate over **stdin/stdout** using typed binary frames.

### SVF → binary (stdin)

Every simulation tick SVF sends two frames in order:

**Frame type 0x02 — sensor data**

```
[0x02] [uint16 BE length] [obsw_sensor_frame_t]
```

`obsw_sensor_frame_t` is a 47-byte packed little-endian struct:

```c
typedef struct __attribute__((packed)) {
    float mag_x, mag_y, mag_z;      // magnetic field (Tesla)
    uint8_t mag_valid;
    float st_q_w, st_q_x,
          st_q_y, st_q_z;           // attitude quaternion (body-to-ECI)
    uint8_t st_valid;
    float gyro_x, gyro_y, gyro_z;   // angular rate (rad/s)
    uint8_t gyro_valid;
    float sim_time;                  // simulation clock (seconds)
} obsw_sensor_frame_t;
```

**Frame type 0x01 — telecommand**

```
[0x01] [uint16 BE length] [PUS-C TC bytes]
```

SVF sends a TC(17,1) heartbeat every tick. Your binary can ignore it or parse it to verify connectivity.

### Binary → SVF (stdout)

After processing a tick, write your TM packets followed by the sync byte:

```
[uint16 BE length] [PUS-C TM packet bytes]   ← repeat for each packet
[0xFF]                                        ← sync byte, ends the tick
```

Minimal C implementation for a single tick:

```c
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#define FRAME_TC     0x01
#define FRAME_SENSOR 0x02
#define SYNC_BYTE    0xFF

// Read one frame from SVF. Returns frame type, fills buf, sets *len.
uint8_t svf_read_frame(uint8_t *buf, uint16_t *len) {
    uint8_t  type;
    uint8_t  hdr[2];
    fread(&type, 1, 1, stdin);
    fread(hdr,   1, 2, stdin);
    *len = (hdr[0] << 8) | hdr[1];
    fread(buf, 1, *len, stdin);
    return type;
}

// Write one TM packet + sync byte.
void svf_write_tm(const uint8_t *tm, uint16_t len) {
    uint8_t hdr[2] = { (uint8_t)(len >> 8), (uint8_t)(len & 0xFF) };
    fwrite(hdr, 1, 2, stdout);
    fwrite(tm,  1, len, stdout);
    uint8_t sync = SYNC_BYTE;
    fwrite(&sync, 1, 1, stdout);
    fflush(stdout);
}

int main(void) {
    uint8_t  buf[512];
    uint16_t len;

    while (1) {
        uint8_t type = svf_read_frame(buf, &len);

        if (type == FRAME_SENSOR) {
            // Parse obsw_sensor_frame_t from buf — float fields, little-endian
            float sim_time;
            memcpy(&sim_time, buf + 43, 4);   // last field
            // ... your OBSW logic here ...

            // Send a TC(1,0) acceptance success as a heartbeat TM response
            uint8_t tm[] = { 0x0F, 0xC0, 0xC0, 0x00, 0x00, 0x06,
                             0x20, 0x01, 0x01, 0x00, 0x00, 0x00 };
            svf_write_tm(tm, sizeof(tm));
        }
    }
}
```

!!! tip
    aarch64 binaries are auto-detected and run via QEMU — no config change needed.

---

## Step 3 — spacecraft.yaml

Create `my_mission/spacecraft.yaml`:

```yaml
version: 1
spacecraft: MyMission

obsw:
  type: pipe
  binary: ./bin/obsw_sim   # path to your compiled binary
  arch: x86_64             # or aarch64

equipment:
  - id: mag1
    model: magnetometer
    hardware_profile: mag_default

  - id: gyro1
    model: gyroscope
    hardware_profile: gyro_default

  - id: str1
    model: star_tracker
    hardware_profile: str_default

wiring:
  auto: true

simulation:
  dt: 0.1
  stop_time: 300.0
  realtime: false
```

Validate the config before running a campaign:

```bash
svf validate my_mission/spacecraft.yaml
```

---

## Step 4 — Write a procedure

Create `my_mission/procedures/smoke_test.py`:

```python
from svf.campaign.procedure import Procedure, ProcedureContext

class SmokeTest(Procedure):
    id          = "TC-SYS-001"
    title       = "OBC heartbeat verification"
    requirement = "SYS-001"

    def run(self, ctx: ProcedureContext) -> None:
        self.step("Wait for simulation to stabilise")
        ctx.wait(2.0)

        self.step("Verify sim time is advancing")
        ctx.assert_parameter("svf.sim_time", greater_than=1.0)

        self.step("Inject magnetometer power and verify status")
        ctx.inject("aocs.mag1.power_enable", 1.0)
        ctx.wait(1.0)
        ctx.assert_parameter("aocs.mag1.status", equals=1.0)
```

---

## Step 5 — campaign.yaml

Create `my_mission/campaign.yaml`:

```yaml
campaign: MyMission Smoke Test
spacecraft: spacecraft.yaml
requirements:
  - SYS-001
procedures:
  - procedures/smoke_test.py
```

---

## Step 6 — Run

```bash
svf campaign my_mission/campaign.yaml --report
open results/campaign_report.html
```

The HTML report shows the verdict per procedure, each step's pass/fail, and which declared requirements are covered or uncovered.

---

## Common issues

| Symptom | Cause | Fix |
|---------|-------|-----|
| `Simulation failed to start` | Binary crashed before first sensor frame | Run binary standalone and check stderr |
| `assert_parameter … timed out` | Binary not flushing stdout after sync byte | Add `fflush(stdout)` after writing `0xFF` |
| aarch64 binary not found | `qemu-aarch64` missing | `apt install qemu-user` |
| Config error on load | Missing equipment field or unknown model | `svf validate spacecraft.yaml` for details |

---

## What's next

- Add fault injection: `ctx.inject_equipment_fault("mag1", "aocs.mag1.field_x", fault_type="bias", value=1e-5, duration_s=30.0)`
- Add temporal assertions: `monitor = ctx.monitor("aocs.gyro1.rate_x", less_than=0.5)` then `monitor.assert_no_violations()`
- Run the full MySat-1 reference mission for more procedure patterns: `mission_mysat1/`
