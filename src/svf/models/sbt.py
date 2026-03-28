"""
SVF S-Band Transponder (SBT) Equipment
TTC interface model: uplink carrier lock, downlink,
mode state machine, TC/TM forwarding.

Physics:
- Uplink: carrier lock/unlock based on signal level threshold
- Downlink: active when in TM_TX mode
- Mode state machine: IDLE -> RANGING -> TC_RX -> TM_TX
- Lock acquisition: requires signal above threshold for LOCK_TIME_S

Implements: SVF-DEV-038
"""

from __future__ import annotations

import logging
from typing import Optional

from svf.abstractions import SyncProtocol
from svf.equipment import PortDefinition, PortDirection
from svf.native_equipment import NativeEquipment
from svf.parameter_store import ParameterStore
from svf.command_store import CommandStore

logger = logging.getLogger(__name__)

# Signal thresholds
LOCK_THRESHOLD_DBM  = -110.0   # dBm minimum for carrier lock
LOCK_TIME_S         = 2.0      # seconds above threshold before lock

# Bit rates
TC_BITRATE_BPS      = 4000.0   # standard S-Band TC uplink
TM_BITRATE_BPS      = 64000.0  # standard S-Band TM downlink

# SBT modes
MODE_IDLE     = 0
MODE_RANGING  = 1
MODE_TC_RX    = 2
MODE_TM_TX    = 3

# Temperature
AMBIENT_TEMP_C  = 20.0
OPERATING_TEMP  = 35.0
TEMP_RISE_RATE  = 0.05


def make_sbt(
    sync_protocol: SyncProtocol,
    store: ParameterStore,
    command_store: Optional[CommandStore] = None,
) -> NativeEquipment:
    """Create an SBT NativeEquipment."""

    state: dict[str, float] = {
        "mode":           float(MODE_IDLE),
        "uplink_lock":    0.0,
        "lock_elapsed":   0.0,
        "temperature":    AMBIENT_TEMP_C,
        "powered":        0.0,
    }

    def _sbt_step(eq: NativeEquipment, t: float, dt: float) -> None:
        power_enable  = eq.read_port("ttc.sbt.power_enable")
        signal_level  = eq.read_port("ttc.sbt.uplink_signal_level")
        mode_cmd      = eq.read_port("ttc.sbt.mode_cmd")

        # Power transitions
        if power_enable < 0.5:
            state["mode"]        = float(MODE_IDLE)
            state["uplink_lock"] = 0.0
            state["lock_elapsed"] = 0.0
            state["powered"]     = 0.0
            eq.write_port("ttc.sbt.uplink_lock",    0.0)
            eq.write_port("ttc.sbt.downlink_active", 0.0)
            eq.write_port("ttc.sbt.mode",           float(MODE_IDLE))
            eq.write_port("ttc.sbt.rx_bitrate",     0.0)
            eq.write_port("ttc.sbt.tx_bitrate",     0.0)
            eq.write_port("ttc.sbt.temperature",
                          state["temperature"])
            return

        state["powered"] = 1.0

        # Temperature
        state["temperature"] += TEMP_RISE_RATE * (
            OPERATING_TEMP - state["temperature"]
        ) * dt

        # Mode transition from command
        if mode_cmd > 0:
            new_mode = int(round(mode_cmd))
            if new_mode != int(state["mode"]):
                logger.info(
                    f"[sbt] Mode: {int(state['mode'])} -> {new_mode}"
                    f" at t={t:.1f}s"
                )
                state["mode"] = float(new_mode)
                eq.receive("ttc.sbt.mode_cmd", 0.0)  # consume

        # Carrier lock logic
        if signal_level >= LOCK_THRESHOLD_DBM:
            state["lock_elapsed"] += dt
            if state["lock_elapsed"] >= LOCK_TIME_S:
                if state["uplink_lock"] < 0.5:
                    logger.info(
                        f"[sbt] Carrier lock acquired at t={t:.1f}s "
                        f"(signal={signal_level:.1f} dBm)"
                    )
                state["uplink_lock"] = 1.0
        else:
            if state["uplink_lock"] > 0.5:
                logger.warning(
                    f"[sbt] Carrier lock lost at t={t:.1f}s "
                    f"(signal={signal_level:.1f} dBm)"
                )
            state["uplink_lock"] = 0.0
            state["lock_elapsed"] = 0.0

        # Bit rates based on mode and lock
        mode = int(state["mode"])
        rx_bitrate = TC_BITRATE_BPS if (
            state["uplink_lock"] > 0.5
            and mode in (MODE_TC_RX, MODE_RANGING)
        ) else 0.0

        tx_bitrate = TM_BITRATE_BPS if mode == MODE_TM_TX else 0.0
        downlink   = 1.0 if mode == MODE_TM_TX else 0.0

        eq.write_port("ttc.sbt.uplink_lock",     state["uplink_lock"])
        eq.write_port("ttc.sbt.downlink_active",  downlink)
        eq.write_port("ttc.sbt.mode",            float(mode))
        eq.write_port("ttc.sbt.rx_bitrate",      rx_bitrate)
        eq.write_port("ttc.sbt.tx_bitrate",      tx_bitrate)
        eq.write_port("ttc.sbt.temperature",     state["temperature"])

    return NativeEquipment(
        equipment_id="sbt",
        ports=[
            PortDefinition("ttc.sbt.power_enable", PortDirection.IN,
                           description="Power enable (0=off, 1=on)"),
            PortDefinition("ttc.sbt.uplink_signal_level", PortDirection.IN,
                           unit="dBm",
                           description="Received uplink signal level"),
            PortDefinition("ttc.sbt.mode_cmd", PortDirection.IN,
                           description="Mode command"),
            PortDefinition("ttc.sbt.uplink_lock", PortDirection.OUT,
                           description="Carrier lock (0=unlocked, 1=locked)"),
            PortDefinition("ttc.sbt.downlink_active", PortDirection.OUT,
                           description="Downlink active flag"),
            PortDefinition("ttc.sbt.mode", PortDirection.OUT,
                           description="Current mode"),
            PortDefinition("ttc.sbt.rx_bitrate", PortDirection.OUT,
                           unit="bps", description="Uplink bit rate"),
            PortDefinition("ttc.sbt.tx_bitrate", PortDirection.OUT,
                           unit="bps", description="Downlink bit rate"),
            PortDefinition("ttc.sbt.temperature", PortDirection.OUT,
                           unit="degC", description="Unit temperature"),
        ],
        step_fn=_sbt_step,
        sync_protocol=sync_protocol,
        store=store,
        command_store=command_store,
    )
