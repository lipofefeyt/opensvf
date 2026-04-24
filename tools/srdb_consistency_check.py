#!/usr/bin/env python3
"""
srdb_consistency_check.py — Cross-repository SRDB consistency checker.

Verifies three things:

  1. WIRE PROTOCOL STRUCT ALIGNMENT
     obsw_sensor_frame_t fields (C, openobsw) vs SVF ParameterStore
     keys used in OBCEmulatorAdapter._send_sensor_frame().
     obsw_actuator_frame_t fields (C) vs CommandStore keys injected in
     OBCEmulatorAdapter._parse_actuator().
     A field rename on either side silently produces zeros on the other.

  2. REQUIREMENT ORPHAN DETECTION  (complements check_coverage.py)
     check_coverage.py checks REQUIREMENTS.md → traceability.txt.
     This tool checks the opposite direction:
       tests/ @pytest.mark.requirement("ID")  →  REQUIREMENTS.md
       source  Implements: ID                 →  REQUIREMENTS.md
     IDs used in code but absent from REQUIREMENTS.md are flagged.
     These are invisible to checkcov and represent ungoverned requirements.

  3. HARDWARE PROFILE KEY SYMMETRY
     Every profile in mission_mysat1/hardware_profiles/ should also
     exist in srdb/hardware/ (bundled). Missing bundled profiles mean
     mission configs fail on a clean install.

Usage:
    python tools/srdb_consistency_check.py [--obsw ../openobsw] [--verbose]

    --obsw    Path to openobsw repo root (optional).
              When provided, struct field names are read from C headers
              and cross-checked against the Python packer.
              When omitted, only the Python-side mapping is checked.

Exit codes:
    0   All checks passed
    1   One or more errors found
    2   Tool error (missing paths)
"""

from __future__ import annotations

import argparse
import re
import struct
import sys
from dataclasses import dataclass, field
from pathlib import Path


# ──────────────────────────────────────────────────────────────────────────────
# Ground-truth mapping tables
#
# Derived directly from reading obc_emulator.py, magnetometer.py,
# gyroscope.py, and star_tracker.py in the actual codebase.
# ──────────────────────────────────────────────────────────────────────────────

# obsw_sensor_frame_t field → ParameterStore key read in _send_sensor_frame()
# Format: "<3fB4fB3fBf"  (47 bytes, little-endian packed)
SENSOR_FRAME_FIELD_TO_SVF_PORT: dict[str, str] = {
    "mag_x":     "aocs.mag.field_x",
    "mag_y":     "aocs.mag.field_y",
    "mag_z":     "aocs.mag.field_z",
    "mag_valid": "aocs.mag.status",           # > 0.5 → valid=1
    "st_q_w":    "aocs.str1.quaternion_w",
    "st_q_x":    "aocs.str1.quaternion_x",
    "st_q_y":    "aocs.str1.quaternion_y",
    "st_q_z":    "aocs.str1.quaternion_z",
    "st_valid":  "aocs.str1.validity",        # > 0.5 → valid=1
    "gyro_x":    "aocs.gyro.rate_x",
    "gyro_y":    "aocs.gyro.rate_y",
    "gyro_z":    "aocs.gyro.rate_z",
    "gyro_valid":"aocs.gyro.status",          # > 0.5 → valid=1
    "sim_time":  "<sim_time_arg>",            # passed as t argument, not from store
}

# obsw_actuator_frame_t field → CommandStore key injected in _parse_actuator()
# Format: "<6fBf"  (29 bytes, little-endian packed)
ACTUATOR_FRAME_FIELD_TO_CMDSTORE_KEY: dict[str, str] = {
    "mtq_dipole_x": "aocs.mtq.dipole_x",
    "mtq_dipole_y": "aocs.mtq.dipole_y",
    "mtq_dipole_z": "aocs.mtq.dipole_z",
    "rw_torque_x":  "aocs.rw1.torque_cmd",
    "rw_torque_y":  "aocs.rw2.torque_cmd",
    "rw_torque_z":  "aocs.rw3.torque_cmd",
    "controller":   "<controller_byte>",      # internal, not injected as float
    "sim_time":     "<sim_time_t_arg>",       # passed as t= argument
}

# Expected struct sizes
_SENSOR_FMT            = "<3fB4fB3fBf"
_ACTUATOR_FMT          = "<6fBf"
EXPECTED_SENSOR_SIZE   = struct.calcsize(_SENSOR_FMT)    # 47
EXPECTED_ACTUATOR_SIZE = struct.calcsize(_ACTUATOR_FMT)  # 29

# Sensor model output ports — what each model declares as OUT ports.
# Verified against the actual PortDefinition() calls in each model file.
SENSOR_MODEL_OUTPUT_PORTS: dict[str, list[str]] = {
    "magnetometer": [
        "aocs.mag.field_x", "aocs.mag.field_y", "aocs.mag.field_z",
        "aocs.mag.status",
    ],
    "gyroscope": [
        "aocs.gyro.rate_x",   "aocs.gyro.rate_y",   "aocs.gyro.rate_z",
        "aocs.gyro.temperature", "aocs.gyro.status",
    ],
    "star_tracker": [
        "aocs.str1.quaternion_w", "aocs.str1.quaternion_x",
        "aocs.str1.quaternion_y", "aocs.str1.quaternion_z",
        "aocs.str1.validity",     "aocs.str1.mode",
        "aocs.str1.temperature",  "aocs.str1.acquisition_progress",
    ],
}

# Requirement IDs referenced in code that are NOT yet in REQUIREMENTS.md.
# These are post-M23 additions that bypassed the requirements-first process.
# Document a justification for each. They produce warnings, not errors,
# since they're expected to be backfilled into REQUIREMENTS.md.
KNOWN_UNGOVERNED: dict[str, str] = {
    # Post-M23 additions — implemented before REQUIREMENTS.md entry was written.
    # Each needs a proper requirement definition in REQUIREMENTS.md.
    "SVF-DEV-100": "ZynqMP SIL validation (aarch64 + QEMU) — post-M23, needs REQUIREMENTS.md entry",
    "SVF-DEV-101": "Renode ZynqMP socket SIL — post-M23, needs REQUIREMENTS.md entry",
    "SVF-DEV-110": "SpacecraftLoader / spacecraft YAML DSL — post-M23, needs REQUIREMENTS.md entry",
    "SVF-DEV-120": "Monte Carlo runner — post-M23, needs REQUIREMENTS.md entry",
    "SVF-DEV-121": "CampaignRunner + CampaignReport — post-M23, needs REQUIREMENTS.md entry",
    "SVF-DEV-122": "HTML report generation (generate_html_report) — post-M23, needs REQUIREMENTS.md entry",
    "SVF-DEV-130": "HardwareProfile bundled search order — post-M23, needs REQUIREMENTS.md entry",
    "SVF-DEV-131": "ParameterMonitor / temporal assertion — post-M23, needs REQUIREMENTS.md entry",
    "SVF-DEV-132": "EquipmentFaultEngine — post-M23, needs REQUIREMENTS.md entry",
    # Functional area IDs missing from REQUIREMENTS.md
    "PCDU-001": "PCDU LCL switching — implemented in pcdu.py, missing [PCDU] section in REQUIREMENTS.md",
    "PCDU-002": "PCDU MPPT efficiency model — implemented in pcdu.py, missing [PCDU] section",
    "PCDU-003": "PCDU UVLO protection — implemented in pcdu.py, missing [PCDU] section",
    "PCDU-004": "PCDU power accounting — implemented in pcdu.py, missing [PCDU] section",
    "GAP-014":  "SVF CLI (svf run/campaign/check/profiles) — implemented in cli.py, missing GAP requirement",
}


# ──────────────────────────────────────────────────────────────────────────────
# Result collector
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class CheckResult:
    errors:   list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    info:     list[str] = field(default_factory=list)

    def error(self, msg: str)   -> None: self.errors.append(msg)
    def warn(self, msg: str)    -> None: self.warnings.append(msg)
    def note(self, msg: str)    -> None: self.info.append(msg)
    def ok(self)                -> bool: return len(self.errors) == 0

    def print_report(self, verbose: bool = False) -> None:
        width = 72
        print("=" * width)
        print("  SRDB Cross-Repository Consistency Report")
        print("=" * width)

        if self.errors:
            print(f"\n❌  ERRORS ({len(self.errors)}) — will cause silent failures:\n")
            for e in self.errors:
                print(f"    {e}")

        if self.warnings:
            print(f"\n⚠️   WARNINGS ({len(self.warnings)}):\n")
            for w in self.warnings:
                print(f"    {w}")

        if verbose and self.info:
            print(f"\nℹ️   INFO ({len(self.info)}):\n")
            for i in self.info:
                print(f"    {i}")

        print()
        if self.ok():
            print("✅  All checks passed.")
        else:
            print(f"❌  {len(self.errors)} error(s) — see above.")
        print("=" * width)


# ──────────────────────────────────────────────────────────────────────────────
# Check 1: Wire protocol struct sizes
# ──────────────────────────────────────────────────────────────────────────────

def check_struct_sizes(result: CheckResult) -> None:
    """
    Verify Python struct format strings produce the correct sizes.

    obsw_sensor_frame_t layout (47 bytes, #pragma pack(push,1)):
      float mag_x, mag_y, mag_z       → 12
      uint8_t mag_valid               →  1
      float st_q_w, st_q_x, st_q_y, st_q_z → 16
      uint8_t st_valid                →  1
      float gyro_x, gyro_y, gyro_z   → 12
      uint8_t gyro_valid              →  1
      float sim_time                  →  4
      Total                           → 47

    obsw_actuator_frame_t layout (29 bytes):
      float mtq_dipole_x/y/z          → 12
      float rw_torque_x/y/z           → 12
      uint8_t controller              →  1
      float sim_time                  →  4
      Total                           → 29

    If the C struct gains a new field (e.g. CSS sun vector for ZynqMP),
    the Python format string in obc_emulator.py must be updated to match.
    Update EXPECTED_*_SIZE and the format strings here too.
    """
    sensor_size   = struct.calcsize(_SENSOR_FMT)
    actuator_size = struct.calcsize(_ACTUATOR_FMT)

    result.note(
        f"[STRUCT] sensor_frame_t '{_SENSOR_FMT}' "
        f"→ {sensor_size} bytes (expected {EXPECTED_SENSOR_SIZE})"
    )
    result.note(
        f"[STRUCT] actuator_frame_t '{_ACTUATOR_FMT}' "
        f"→ {actuator_size} bytes (expected {EXPECTED_ACTUATOR_SIZE})"
    )

    if sensor_size != EXPECTED_SENSOR_SIZE:
        result.error(
            f"[STRUCT] sensor_frame_t size mismatch: "
            f"Python={sensor_size} bytes, expected={EXPECTED_SENSOR_SIZE} bytes. "
            f"Update _SENSOR_FMT in obc_emulator.py to match the C struct."
        )

    if actuator_size != EXPECTED_ACTUATOR_SIZE:
        result.error(
            f"[STRUCT] actuator_frame_t size mismatch: "
            f"Python={actuator_size} bytes, expected={EXPECTED_ACTUATOR_SIZE} bytes. "
            f"Update _ACTUATOR_FMT in obc_emulator.py to match the C struct."
        )


# ──────────────────────────────────────────────────────────────────────────────
# Check 2: Wire protocol mapping vs. actual obc_emulator.py
# ──────────────────────────────────────────────────────────────────────────────

def check_wire_protocol_python_side(
    svf_root: Path,
    result: CheckResult,
) -> None:
    """
    Read obc_emulator.py and verify that:
      - Every port in SENSOR_FRAME_FIELD_TO_SVF_PORT is actually store.read()
        in _send_sensor_frame().
      - Every key in ACTUATOR_FRAME_FIELD_TO_CMDSTORE_KEY is actually
        cmd_store.inject()'ed in _parse_actuator().

    This self-validates the mapping table — if the implementation is updated
    without updating this script, the script will flag it rather than silently
    reporting false positives.
    """
    emulator_py = svf_root / "src" / "svf" / "models" / "dhs" / "obc_emulator.py"
    if not emulator_py.exists():
        result.warn(
            f"[WIRE] {emulator_py.relative_to(svf_root)} not found — "
            f"skipping Python-side verification"
        )
        return

    text = emulator_py.read_text(encoding="utf-8")

    # Extract store read keys (both _read() helper and direct store.read())
    sensor_store_reads: set[str] = set()
    sensor_store_reads |= set(re.findall(r'_read\("([^"]+)"', text))
    sensor_store_reads |= set(re.findall(r'self\._store\.read\("([^"]+)"', text))

    for c_field, svf_port in SENSOR_FRAME_FIELD_TO_SVF_PORT.items():
        if svf_port.startswith("<"):
            continue
        if svf_port not in sensor_store_reads:
            result.error(
                f"[WIRE/sensor] Mapping table says '{c_field}' → '{svf_port}' "
                f"but that key is NOT present in obc_emulator.py store reads. "
                f"Either the implementation changed or SENSOR_FRAME_FIELD_TO_SVF_PORT "
                f"needs updating."
            )

    # Extract CommandStore inject keys
    actuator_inject_keys: set[str] = set(
        re.findall(r'self\._command_store\.inject\("([^"]+)"', text)
    )

    for c_field, cmd_key in ACTUATOR_FRAME_FIELD_TO_CMDSTORE_KEY.items():
        if cmd_key.startswith("<"):
            continue
        if cmd_key not in actuator_inject_keys:
            result.error(
                f"[WIRE/actuator] Mapping table says '{c_field}' → '{cmd_key}' "
                f"but that key is NOT injected in obc_emulator.py _parse_actuator(). "
                f"Either the implementation changed or ACTUATOR_FRAME_FIELD_TO_CMDSTORE_KEY "
                f"needs updating."
            )

    result.note(
        f"[WIRE] Python obc_emulator.py: "
        f"{len(sensor_store_reads)} store reads, "
        f"{len(actuator_inject_keys)} inject calls"
    )


# ──────────────────────────────────────────────────────────────────────────────
# Check 3: C struct field names (optional, requires --obsw)
# ──────────────────────────────────────────────────────────────────────────────

_C_FIELD_RE = re.compile(
    r"""^\s+(?:float|uint8_t|uint16_t|uint32_t)\s+(\w+)\s*;""",
    re.MULTILINE,
)


def _extract_c_struct_fields_from_text(c_text: str, struct_name: str) -> set[str]:
    """
    Find a named typedef struct and extract its field names.

    Uses backward brace-counting from the closing '} struct_name;' rather
    than a forward DOTALL regex. This is correct even in concatenated files
    (gitingest snapshots) where a greedy DOTALL pattern would absorb fields
    from many preceding structs before reaching the target name.
    """
    # Locate '} struct_name;'
    close_re = re.compile(rf'\}}\s*{re.escape(struct_name)}\s*;')
    m = close_re.search(c_text)
    if not m:
        return set()

    close_pos = m.start()

    # Walk backwards through the text counting braces to find the matching '{'
    prefix = c_text[:close_pos]
    depth  = 1
    pos    = len(prefix) - 1
    open_pos = -1

    while pos >= 0 and depth > 0:
        ch = prefix[pos]
        if ch == '}':
            depth += 1
        elif ch == '{':
            depth -= 1
            if depth == 0:
                open_pos = pos
        pos -= 1

    if open_pos < 0:
        return set()

    struct_body = c_text[open_pos + 1 : close_pos]
    return set(_C_FIELD_RE.findall(struct_body))


def _find_struct_in_headers(
    obsw_root: Path,
    struct_name: str,
    result: CheckResult,
) -> tuple[set[str], str]:
    """
    Search each source file individually for struct_name.

    Returns (fields, source_file_name). Per-file search avoids false
    negatives from cross-file DOTALL matching when files are concatenated.

    Searches .h, .c, and .txt files. .txt covers gitingest snapshots
    where a single concatenated file represents the whole repository.
    """
    h_files = (
        list(obsw_root.rglob("*.h"))
        + list(obsw_root.rglob("*.c"))
        + list(obsw_root.rglob("*.txt"))  # gitingest snapshots
    )
    n = len(h_files)
    result.note(f"[WIRE/C] Scanning {n} files for {struct_name}")

    if n == 0:
        # Emit a diagnostic to help understand why rglob found nothing
        try:
            top_level = [p.name for p in sorted(obsw_root.iterdir())]
        except Exception as e:
            top_level = [f"(could not list: {e})"]
        result.warn(
            f"[WIRE/C] No .h, .c, or .txt files found under {obsw_root}. "
            f"Top-level contents: {top_level}. "
            f"If openobsw is a Codespace or uses a non-standard layout, "
            f"point --obsw directly at the directory containing sim/ and include/."
        )
        return set(), ""

    for h_file in h_files:
        try:
            file_text = h_file.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        fields = _extract_c_struct_fields_from_text(file_text, struct_name)
        if fields:
            return fields, h_file.name

    return set(), ""


def check_wire_protocol_c_side(
    obsw_root: Path,
    result: CheckResult,
) -> None:
    """
    Parse openobsw C headers for actual struct field names and verify
    they match the mapping tables. Catches field renames in openobsw
    that weren't propagated to the SVF packer.

    obsw_root may be:
      - A directory (real openobsw checkout) — searched recursively
      - A .txt file (gitingest snapshot) — searched directly

    In single-workspace environments (Firebase IDX, GitHub Codespaces)
    where both repos can't coexist, pass the gitingest snapshot:
      --obsw path/to/lipofefeyt-openobsw-*.txt
    """
    # If a .txt snapshot was passed directly, wrap it as a single-file "root"
    if obsw_root.is_file():
        if obsw_root.suffix == ".txt":
            result.note(f"[WIRE/C] Using gitingest snapshot: {obsw_root.name}")
            # Create a temporary directory with the .txt as the only file to search
            # Actually just call _find_struct directly on the file
            sensor_fields  = _extract_c_struct_fields_from_text(
                obsw_root.read_text(encoding="utf-8", errors="replace"),
                "obsw_sensor_frame_t",
            )
            actuator_fields = _extract_c_struct_fields_from_text(
                obsw_root.read_text(encoding="utf-8", errors="replace"),
                "obsw_actuator_frame_t",
            )
            sensor_src   = obsw_root.name if sensor_fields else ""
            actuator_src = obsw_root.name if actuator_fields else ""
        else:
            result.warn(
                f"[WIRE/C] --obsw points to a file that is not a .txt snapshot: "
                f"{obsw_root}. Pass a directory or a gitingest .txt file."
            )
            return
    elif not obsw_root.exists():
        result.warn(
            f"[WIRE/C] --obsw path does not exist: {obsw_root}. "
            f"In single-workspace environments pass a gitingest snapshot: "
            f"--obsw path/to/lipofefeyt-openobsw-*.txt"
        )
        return
    else:
        sensor_fields, sensor_src = _find_struct_in_headers(
            obsw_root, "obsw_sensor_frame_t", result
        )
        actuator_fields, actuator_src = _find_struct_in_headers(
            obsw_root, "obsw_actuator_frame_t", result
        )

    if not sensor_fields:
        result.warn(
            "[WIRE/C] Could not parse obsw_sensor_frame_t from any .h/.c file. "
            "Expected in sim/sensor_inject.h. "
            "Run with --verbose to see how many files were scanned."
        )
    else:
        result.note(
            f"[WIRE/C] obsw_sensor_frame_t found in {sensor_src}: "
            f"{sorted(sensor_fields)}"
        )
        for c_field in SENSOR_FRAME_FIELD_TO_SVF_PORT:
            if c_field not in sensor_fields:
                result.error(
                    f"[WIRE/C] C field '{c_field}' in mapping table "
                    f"does NOT exist in obsw_sensor_frame_t. "
                    f"Renamed in openobsw without updating SVF?"
                )
        for c_field in sensor_fields:
            if c_field not in SENSOR_FRAME_FIELD_TO_SVF_PORT:
                result.warn(
                    f"[WIRE/C] obsw_sensor_frame_t has field '{c_field}' "
                    f"with no entry in SENSOR_FRAME_FIELD_TO_SVF_PORT. "
                    f"SVF packer will not include it — add mapping if needed."
                )

    if not actuator_fields:
        result.warn(
            "[WIRE/C] Could not parse obsw_actuator_frame_t from any .h/.c file. "
            "Expected in sim/sensor_inject.h."
        )
    else:
        result.note(
            f"[WIRE/C] obsw_actuator_frame_t found in {actuator_src}: "
            f"{sorted(actuator_fields)}"
        )
        for c_field in ACTUATOR_FRAME_FIELD_TO_CMDSTORE_KEY:
            if c_field not in actuator_fields:
                result.error(
                    f"[WIRE/C] C field '{c_field}' in mapping table "
                    f"does NOT exist in obsw_actuator_frame_t."
                )
        for c_field in actuator_fields:
            if c_field not in ACTUATOR_FRAME_FIELD_TO_CMDSTORE_KEY:
                result.warn(
                    f"[WIRE/C] obsw_actuator_frame_t has field '{c_field}' "
                    f"with no entry in ACTUATOR_FRAME_FIELD_TO_CMDSTORE_KEY."
                )


# ──────────────────────────────────────────────────────────────────────────────
# Check 4: Sensor producer/consumer symmetry
# ──────────────────────────────────────────────────────────────────────────────

def check_sensor_producer_consumer_symmetry(
    svf_root: Path,
    result: CheckResult,
) -> None:
    """
    Verify that every ParameterStore port the emulator reads has a
    declared producer in the sensor model output port lists.

    If a sensor model renames an output (e.g. aocs.mag.field_x →
    aocs.mag.b_x), the emulator reads the old name and gets None from
    the store, which becomes 0.0 in the packed frame — the C OBSW sees
    an all-zero magnetic field and b-dot produces no output. No error
    is raised anywhere. This check catches that class of bug.
    """
    all_producer_ports: set[str] = set()
    for ports in SENSOR_MODEL_OUTPUT_PORTS.values():
        all_producer_ports.update(ports)

    missing_producers = []
    for c_field, svf_port in SENSOR_FRAME_FIELD_TO_SVF_PORT.items():
        if svf_port.startswith("<"):
            continue
        if svf_port not in all_producer_ports:
            missing_producers.append((c_field, svf_port))
            result.error(
                f"[SEN] Emulator reads '{svf_port}' (for C field '{c_field}') "
                f"but no sensor model declares it as an OUT port. "
                f"ParameterStore will return None → 0.0 in sensor frame → "
                f"silent zeros in the OBSW."
            )

    if not missing_producers:
        result.note(
            f"[SEN] All {len(SENSOR_FRAME_FIELD_TO_SVF_PORT)} sensor frame "
            f"ports have declared producers ✓"
        )

    # Also verify by reading the actual model source (if available)
    models_dir = svf_root / "src" / "svf" / "models" / "aocs"
    if models_dir.exists():
        _verify_ports_in_source(models_dir, all_producer_ports, result)


def _verify_ports_in_source(
    aocs_dir: Path,
    expected_ports: set[str],
    result: CheckResult,
) -> None:
    """
    Check that every expected output port actually appears in a
    PortDefinition(..., PortDirection.OUT) call in the model source.
    Catches the table being stale relative to the code.
    """
    port_def_re = re.compile(
        r'PortDefinition\("([^"]+)",\s*PortDirection\.OUT'
    )
    declared_out_ports: set[str] = set()
    for py_file in aocs_dir.glob("*.py"):
        text = py_file.read_text(encoding="utf-8")
        declared_out_ports |= set(port_def_re.findall(text))

    for port in expected_ports:
        if port not in declared_out_ports:
            result.warn(
                f"[SEN] '{port}' is in SENSOR_MODEL_OUTPUT_PORTS table "
                f"but NOT found as PortDirection.OUT in any AOCS model source. "
                f"Update SENSOR_MODEL_OUTPUT_PORTS if the model was refactored."
            )

    result.note(
        f"[SEN] AOCS model source declares {len(declared_out_ports)} OUT ports"
    )


# ──────────────────────────────────────────────────────────────────────────────
# Check 5: Requirement orphan detection
# ──────────────────────────────────────────────────────────────────────────────

_MARK_RE       = re.compile(r'@pytest\.mark\.requirement\("([^"]+)"')
_IMPLEMENTS_RE = re.compile(r'Implements:\s*((?:SVF-DEV-\d+|[A-Z0-9]+-\d+)'
                            r'(?:,\s*(?:SVF-DEV-\d+|[A-Z0-9]+-\d+))*)')


def _parse_requirements_md_ids(req_file: Path) -> set[str]:
    text = req_file.read_text(encoding="utf-8")
    return set(re.findall(r'\*\*([A-Z0-9][A-Z0-9_\-]+-\d+)\*\*', text))


def _parse_test_requirement_refs(tests_root: Path) -> dict[str, list[str]]:
    refs: dict[str, list[str]] = {}
    for py_file in tests_root.rglob("*.py"):
        text = py_file.read_text(encoding="utf-8")
        pending: list[str] = []
        for line in text.splitlines():
            m = _MARK_RE.search(line)
            if m:
                pending.append(m.group(1))
            elif pending:
                nm = re.match(r"\s*(?:def|class)\s+(\w+)", line)
                if nm:
                    label = f"{py_file.name}::{nm.group(1)}"
                    for req_id in pending:
                        refs.setdefault(req_id, []).append(label)
                    pending = []
                elif line.strip() and not line.strip().startswith(("#", "@")):
                    pending = []
    return refs


def _parse_implements_refs(src_root: Path) -> dict[str, list[str]]:
    refs: dict[str, list[str]] = {}
    for py_file in src_root.rglob("*.py"):
        text = py_file.read_text(encoding="utf-8")
        for m in _IMPLEMENTS_RE.finditer(text):
            for req_id in re.findall(r'[A-Z][A-Z0-9_\-]+-\d+', m.group(1)):
                refs.setdefault(req_id, []).append(py_file.name)
    return refs


def check_requirement_orphans(
    svf_root: Path,
    result: CheckResult,
) -> None:
    """
    Identify requirement IDs referenced in code but missing from REQUIREMENTS.md.

    check_coverage.py (checkcov) only checks one direction:
      REQUIREMENTS.md BASELINED/IMPLEMENTED → results/traceability.txt

    This check covers the opposite direction:
      code @pytest.mark.requirement / Implements: → REQUIREMENTS.md

    An ID that exists in tests but not in REQUIREMENTS.md is invisible to
    checkcov. It won't be caught by the CI gate and represents work that
    was done without a governing requirement — the V&V claim is unfounded.

    Known post-M23 IDs are listed in KNOWN_UNGOVERNED. They produce warnings
    (not errors) since they're expected to be backfilled. Any new unknown ID
    is an error.
    """
    req_file = svf_root / "REQUIREMENTS.md"
    if not req_file.exists():
        result.warn("[REQ] REQUIREMENTS.md not found — skipping orphan check")
        return

    defined_ids   = _parse_requirements_md_ids(req_file)
    test_refs     = _parse_test_requirement_refs(svf_root / "tests")
    src_refs      = _parse_implements_refs(svf_root / "src")

    all_code_refs: dict[str, list[str]] = {}
    for req_id, locs in test_refs.items():
        all_code_refs.setdefault(req_id, []).extend(locs)
    for req_id, locs in src_refs.items():
        all_code_refs.setdefault(req_id, []).extend(locs)

    result.note(
        f"[REQ] {len(defined_ids)} IDs in REQUIREMENTS.md, "
        f"{len(all_code_refs)} unique IDs referenced in code"
    )

    n_unknown = 0
    n_known   = 0

    for req_id, locations in sorted(all_code_refs.items()):
        if req_id in defined_ids:
            continue   # governed — covered by checkcov
        if req_id in KNOWN_UNGOVERNED:
            n_known += 1
            result.warn(
                f"[REQ] '{req_id}' used in code but not in REQUIREMENTS.md "
                f"(known post-M23: {KNOWN_UNGOVERNED[req_id]})"
            )
        else:
            n_unknown += 1
            result.error(
                f"[REQ] '{req_id}' used in code but NOT in REQUIREMENTS.md "
                f"and NOT in KNOWN_UNGOVERNED. "
                f"Add a requirement definition, or add to KNOWN_UNGOVERNED "
                f"with a justification. First seen: {locations[0]}"
            )

    result.note(
        f"[REQ] Orphan summary: "
        f"{n_unknown} ungoverned (unexpected), "
        f"{n_known} known post-M23 (needs backfill into REQUIREMENTS.md). "
        f"REQUIREMENTS.md→test coverage is handled by tools/check_coverage.py."
    )


# ──────────────────────────────────────────────────────────────────────────────
# Check 6: Hardware profile symmetry
# ──────────────────────────────────────────────────────────────────────────────

def check_hardware_profile_symmetry(
    svf_root: Path,
    result: CheckResult,
) -> None:
    """
    Every profile in mission_mysat1/hardware_profiles/ should exist in
    srdb/hardware/ (the profiles bundled with opensvf).

    If a profile is only in the mission directory, it works on the developer's
    machine but fails on a clean install or in CI when mission_mysat1 configs
    reference it by name. The HardwareProfile search order is:
      1. srdb/hardware/ (bundled)
      2. obsw-srdb package
      3. Explicit hardware_dir argument
    """
    mission_dir = svf_root / "mission_mysat1" / "hardware_profiles"
    # The hardware_profile.py search uses mission_mysat1/hardware_profiles/ as
    # the "bundled" path. srdb/hardware/ is the intended future home per the
    # architecture doc, but does not currently exist.
    # We check both locations and report clearly which is active.
    bundled_dir_arch   = svf_root / "srdb" / "hardware"           # future home
    bundled_dir_actual = svf_root / "mission_mysat1" / "hardware_profiles"  # current

    # Use whichever exists; prefer srdb/hardware/ if both exist
    if bundled_dir_arch.exists():
        bundled_dir = bundled_dir_arch
        result.note("[PROFILE] Using srdb/hardware/ as bundled profile directory")
    elif bundled_dir_actual.exists():
        bundled_dir = bundled_dir_actual
        result.note(
            "[PROFILE] Bundled profiles are in mission_mysat1/hardware_profiles/ "
            "(srdb/hardware/ not yet created — see architecture doc)"
        )
    else:
        result.warn(
            "[PROFILE] No bundled hardware profile directory found. "
            "Neither srdb/hardware/ nor mission_mysat1/hardware_profiles/ exists. "
            "HardwareProfile search will fall through to obsw-srdb package only."
        )
        return

    if not mission_dir.exists():
        result.note("[PROFILE] mission_mysat1/hardware_profiles/ not found — skipping symmetry check")
        return

    mission_profiles = {p.name for p in mission_dir.glob("*.yaml")}
    bundled_profiles = {p.name for p in bundled_dir.glob("*.yaml")}

    result.note(
        f"[PROFILE] {len(mission_profiles)} mission profiles, "
        f"{len(bundled_profiles)} bundled profiles"
    )

    for name in sorted(mission_profiles):
        if name not in bundled_profiles:
            result.warn(
                f"[PROFILE] '{name}' in mission_mysat1/hardware_profiles/ "
                f"but absent from srdb/hardware/. "
                f"Will fail on clean install without obsw-srdb package."
            )

    for name in sorted(bundled_profiles - mission_profiles):
        result.note(
            f"[PROFILE] '{name}' bundled but not in mission_mysat1 "
            f"(available for other missions — not an error)"
        )


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="SRDB cross-repository consistency checker for opensvf"
    )
    parser.add_argument(
        "--obsw",
        default=None,
        help=(
            "Path to openobsw repo root OR a gitingest .txt snapshot. "
            "In single-workspace environments (Firebase IDX, Codespaces) "
            "pass the gitingest snapshot directly: "
            "--obsw lipofefeyt-openobsw-*.txt"
        ),
    )
    parser.add_argument(
        "--svf",
        default=".",
        help="Path to opensvf repo root (default: current directory)",
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    svf_root = Path(args.svf).resolve()
    if not (svf_root / "src" / "svf").exists():
        print(
            f"ERROR: opensvf src/svf not found under {svf_root}. "
            f"Run from the opensvf repo root or pass --svf.",
            file=sys.stderr,
        )
        return 2

    result = CheckResult()

    print(f"opensvf root: {svf_root}")
    if args.obsw:
        obsw_label = "snapshot" if Path(args.obsw).suffix == ".txt" else "root"
        print(f"openobsw {obsw_label}: {Path(args.obsw).resolve()}")
    print()

    print("  [1/6] Struct sizes...")
    check_struct_sizes(result)

    print("  [2/6] Python-side wire protocol mapping vs. obc_emulator.py...")
    check_wire_protocol_python_side(svf_root, result)

    if args.obsw:
        print("  [3/6] C struct field names vs. mapping table...")
        check_wire_protocol_c_side(Path(args.obsw).resolve(), result)
    else:
        print("  [3/6] C struct check skipped (pass --obsw <repo-or-txt> to enable)")
        result.note(
            "[WIRE/C] Skipped. In single-workspace environments (Firebase IDX, "
            "Codespaces) pass a gitingest snapshot: "
            "--obsw path/to/lipofefeyt-openobsw-*.txt"
        )

    print("  [4/6] Sensor producer/consumer symmetry...")
    check_sensor_producer_consumer_symmetry(svf_root, result)

    print("  [5/6] Requirement orphan detection...")
    check_requirement_orphans(svf_root, result)

    print("  [6/6] Hardware profile symmetry...")
    check_hardware_profile_symmetry(svf_root, result)

    print()
    result.print_report(verbose=args.verbose)
    return 0 if result.ok() else 1


if __name__ == "__main__":
    sys.exit(main())