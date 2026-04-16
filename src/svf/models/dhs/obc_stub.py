"""
SVF OBC Stub
Configurable OBSW behaviour simulator.

Replaces ObcEquipment for closed-loop system validation
without a real OBSW binary. Rules are evaluated each tick
against the ParameterStore and fire CommandStore injections.

This is the ECSS "model responder" concept — a test stub
representing equipment, sufficient to test open-loop and
closed-loop OBSW behaviour against its specification.

Reference: ECSS-E-TM-10-21A section on model responders.

Implements: SVF-DEV-038
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable, Optional

from svf.abstractions import SyncProtocol
from svf.command_store import CommandStore
from svf.models.dhs.obc import ObcEquipment, ObcConfig
from svf.parameter_store import ParameterStore, ParameterEntry

logger = logging.getLogger(__name__)


@dataclass
class Rule:
    """
    A single OBSW behaviour rule.

    Attributes:
        name:       Human-readable rule name for logging and debugging
        watch:      SRDB canonical parameter name to monitor
        condition:  Called with current ParameterEntry — return True to fire
        action:     Called with (CommandStore, t) when condition is True
        enabled:    Whether this rule is currently active
        fired:      Number of times this rule has fired (for debugging)
        once:       If True, rule disables itself after first firing
    """
    name: str
    watch: str
    condition: Callable[[Optional[ParameterEntry]], bool]
    action: Callable[[CommandStore, float], None]
    enabled: bool = True
    fired: int = field(default=0, init=False)
    once: bool = False

    def evaluate(
        self,
        store: ParameterStore,
        cmd_store: CommandStore,
        t: float,
    ) -> bool:
        """
        Evaluate the rule against the current store state.
        Returns True if the rule fired.
        """
        if not self.enabled:
            return False

        entry = store.read(self.watch)
        if not self.condition(entry):
            return False

        self.action(cmd_store, t)
        self.fired += 1

        if self.once:
            self.enabled = False
            logger.info(
                f"[stub] Rule '{self.name}' fired and disabled (once=True)"
            )
        else:
            logger.debug(f"[stub] Rule '{self.name}' fired at t={t:.1f}s")

        return True


class ObcStub(ObcEquipment):
    """
    OBC Stub — configurable OBSW behaviour simulator.

    Extends ObcEquipment with a rule engine that evaluates
    conditions against the ParameterStore each tick and fires
    CommandStore injections when conditions are met.

    This is the HIL adapter plug-in point — when the real OBC
    emulator is available, replace ObcStub with HardwareEquipment
    at the composition root. Nothing else changes.

    Usage:
        from svf.models.dhs.obc import MODE_SAFE, MODE_NOMINAL
        from svf.models.dhs.obc_stub import ObcStub, Rule

        stub = ObcStub(
            config=ObcConfig(apid=0x101, ...),
            rules=[
                Rule(
                    name='low_battery_safe_mode',
                    watch='eps.battery.soc',
                    condition=lambda e: e is not None and e.value < 0.3,
                    action=lambda cs, t: cs.inject(
                        'dhs.obc.mode_cmd', float(MODE_SAFE), t=t,
                        source_id='stub.low_battery'
                    ),
                ),
                Rule(
                    name='st_valid_enable_rw',
                    watch='aocs.str1.validity',
                    condition=lambda e: e is not None and e.value > 0.5,
                    action=lambda cs, t: cs.inject(
                        'aocs.rw1.torque_cmd', 0.05, t=t,
                        source_id='stub.st_valid'
                    ),
                ),
            ],
            sync_protocol=sync,
            store=store,
            command_store=cmd_store,
        )
    """

    def __init__(
        self,
        config: ObcConfig,
        sync_protocol: SyncProtocol,
        store: ParameterStore,
        command_store: Optional[CommandStore] = None,
        rules: Optional[list[Rule]] = None,
    ) -> None:
        self._rules: list[Rule] = rules or []
        super().__init__(config, sync_protocol, store, command_store)
        logger.info(
            f"[stub] Initialised with {len(self._rules)} rules: "
            f"{[r.name for r in self._rules]}"
        )

    def do_step(self, t: float, dt: float) -> None:
        """
        Extended do_step: evaluate rules then run OBC DHS step.
        Rules fire before DHS step so commands are available
        for equipment on the same tick.
        """
        if self._command_store is not None:
            for rule in self._rules:
                rule.evaluate(self._store, self._command_store, t)

        super().do_step(t, dt)

    # ── Rule management ───────────────────────────────────────────────────────

    def add_rule(self, rule: Rule) -> None:
        """Add a rule at runtime."""
        self._rules.append(rule)
        logger.info(f"[stub] Rule added: '{rule.name}'")

    def enable_rule(self, name: str) -> None:
        """Enable a rule by name."""
        for rule in self._rules:
            if rule.name == name:
                rule.enabled = True
                logger.info(f"[stub] Rule enabled: '{name}'")
                return
        logger.warning(f"[stub] Rule not found: '{name}'")

    def disable_rule(self, name: str) -> None:
        """Disable a rule by name."""
        for rule in self._rules:
            if rule.name == name:
                rule.enabled = False
                logger.info(f"[stub] Rule disabled: '{name}'")
                return
        logger.warning(f"[stub] Rule not found: '{name}'")

    def rule_fired_count(self, name: str) -> int:
        """Return how many times a rule has fired."""
        for rule in self._rules:
            if rule.name == name:
                return rule.fired
        return 0

    @property
    def rules(self) -> list[Rule]:
        return list(self._rules)
