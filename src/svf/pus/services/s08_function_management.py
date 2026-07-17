"""PUS Service 8  -  Function Management."""

from __future__ import annotations

from svf.pus.tc import PusTcPacket


class PusService8:
    """
    PUS Service 8  -  Function Management.

    TC(8,1)  -  Perform a function: function_id(2 BE) | args_len(1) | args(...)

    Function IDs are mission/OBSW-specific (not a fixed PUS-C enumeration);
    the platform only provides the generic codec. A given mission wires
    specific function IDs to specific on-board actions (see
    ObcConfig.function_mode_map for the mode-transition case).

    Byte layout matches the openobsw C reference implementation
    (src/pus/s8.c) so TC(8,1) built here is wire-compatible with a real
    OBSW binary over the pipe/socket wire protocol.
    """

    @staticmethod
    def is_perform(tc: PusTcPacket) -> bool:
        return tc.service == 8 and tc.subservice == 1

    @staticmethod
    def build_perform(function_id: int, args: bytes = b"") -> bytes:
        """Build TC(8,1) application data."""
        if len(args) > 255:
            raise ValueError(f"S8 args too long: {len(args)} bytes (max 255)")
        return function_id.to_bytes(2, "big") + bytes([len(args)]) + args

    @staticmethod
    def parse_perform(tc: PusTcPacket) -> tuple[int, bytes]:
        """Parse TC(8,1) application data. Returns (function_id, args)."""
        if len(tc.app_data) < 3:
            raise ValueError(f"TC(8,1) app_data too short: {len(tc.app_data)} bytes")
        function_id = int.from_bytes(tc.app_data[0:2], "big")
        args_len = tc.app_data[2]
        args = tc.app_data[3:3 + args_len]
        if len(args) < args_len:
            raise ValueError(f"TC(8,1) app_data truncated: expected {args_len} arg bytes")
        return function_id, args
