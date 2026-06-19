# MySat-1 Mission Requirements

> **Mission:** MySat-1 reference 3U CubeSat
> **Verification method:** All requirements in this file are verifiable by SVF campaign procedures.
> **Status:** AOCS requirements covered by `quickstart_campaign.yaml`. EPS requirements pending procedures.

---

## AOCS Requirements

**MIS-AOCS-001**
The AOCS sensor suite (magnetometer and rate gyroscope) shall reach nominal
operational status within 5 seconds of receiving a power-enable command.

*Verified by:* TC-AOCS-001 (`quickstart_procedures.py`)

---

**MIS-AOCS-002**
The star tracker shall complete cold-start acquisition and output a valid
attitude quaternion within 15 seconds of power-on, provided the sun is
outside the 30° exclusion cone.

*Verified by:* TC-AOCS-002 (`quickstart_procedures.py`)

---

**MIS-AOCS-003**
The reaction wheel shall achieve positive angular velocity within 10 seconds
of receiving a positive torque command.

*Verified by:* TC-AOCS-003 (`quickstart_procedures.py`)

---

**MIS-AOCS-004**
The reaction wheel thermal protection function shall de-assert the nominal
status flag (set to 0.0) when wheel bearing temperature exceeds 80 °C.

*Verified by:* TC-FAULT-001 (`quickstart_procedures.py`)

---

## EPS Requirements

**MIS-EPS-001**
The battery state of charge shall increase when the solar array illumination
is 100 % and the bus load is below the array output power.

*Verified by:* TC-PWR-001 (`eps_procedures.py`)  -  add EPS models to spacecraft.yaml to enable.

---

**MIS-EPS-002**
The battery state of charge shall decrease monotonically during full eclipse
when the bus load exceeds zero.

*Verified by:* TC-PWR-002 (`eps_procedures.py`)  -  add EPS models to spacecraft.yaml to enable.

---

**MIS-EPS-003**
The regulated bus voltage shall remain above 3.0 V during deep eclipse with
nominal bus load for at least 120 seconds.

*Verified by:* TC-PWR-005 (`eps_procedures.py`)  -  add EPS models to spacecraft.yaml to enable.

---

**MIS-EPS-004**
The PCDU shall provide regulated 3.3 V and 5.0 V rails within ±5 % under
nominal load conditions.

*Verification:* Requires PCDU telemetry  -  pending campaign procedure.

---

## FreeRTOS HIL Requirements

**MIS-RTOS-001**
The simulation tick p95 wall-clock latency shall remain below 3 500 ms
throughout a nominal operational session to maintain IWDG keepalive margin
when SVF is connected to an STM32H750 running FreeRTOS (IWDG timeout 4 000 ms,
3 500 ms budget leaves 500 ms margin for jitter).

*Verified by:* TC-RTOS-001 (`freertos_procedures.py`)

---

**MIS-RTOS-002**
The SRDB `dhs.obc.freertos.*` PUS parameter ID namespace (0x4020–0x402F)
shall contain no collisions with any other parameter definition at mission
integration time, preserving the reservation for future FreeRTOS health
telemetry (task stack HWM, tick miss counter, context switch rate).

*Verified by:* TC-RTOS-002 (`freertos_procedures.py`)

---

**MIS-RTOS-003**
No FreeRTOS fault events (stack overflow, IWDG reset) shall be detected in
the `svf.obc.freertos.*` diagnostic counters during a nominal OBC operational
period of 10 simulation seconds.

*Verified by:* TC-RTOS-003 (`freertos_procedures.py`)

---

## FreeRTOS HIL Integration Requirements

> These requirements apply only when SVF is connected to a real openobsw binary
> (pipe or socket transport). Procedures raise INCONCLUSIVE if no binary is found.

**MIS-HIL-001**
The OBSW shall respond to a TC(17,1) Are-You-Alive ping with a TM(17,2) pong
within 2 seconds of connection establishment in pipe mode.

*Verified by:* TC-HIL-001 (`freertos_hil_procedures.py`)

---

**MIS-HIL-002**
The OBSW shall emit DHS_OBC_HK telemetry (S3, SID 3) with OBC mode, OBT,
health, reset count, and CPU load within 5 seconds of HK reporting being
enabled, and the OBT shall advance monotonically across ticks.

*Verified by:* TC-HIL-002 (`freertos_hil_procedures.py`)

---

**MIS-HIL-003**
The SVF simulation master shall maintain tick synchronisation with the OBSW
(no consecutive desync events) for a minimum of 30 simulation seconds, and
the tick p95 latency shall remain below 3 500 ms throughout.

*Verified by:* TC-HIL-003 (`freertos_hil_procedures.py`)

---

**MIS-HIL-004**
No FreeRTOS fault events (stack overflow, IWDG reset) shall be detected in
the SVF diagnostic counters during a 30-second nominal HIL session.

*Verified by:* TC-HIL-004 (`freertos_hil_procedures.py`)
