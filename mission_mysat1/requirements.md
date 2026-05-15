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

*Verified by:* TC-PWR-001 (`eps_procedures.py`) — add EPS models to spacecraft.yaml to enable.

---

**MIS-EPS-002**
The battery state of charge shall decrease monotonically during full eclipse
when the bus load exceeds zero.

*Verified by:* TC-PWR-002 (`eps_procedures.py`) — add EPS models to spacecraft.yaml to enable.

---

**MIS-EPS-003**
The regulated bus voltage shall remain above 3.0 V during deep eclipse with
nominal bus load for at least 120 seconds.

*Verified by:* TC-PWR-005 (`eps_procedures.py`) — add EPS models to spacecraft.yaml to enable.

---

**MIS-EPS-004**
The PCDU shall provide regulated 3.3 V and 5.0 V rails within ±5 % under
nominal load conditions.

*Verification:* Requires PCDU telemetry — pending campaign procedure.
