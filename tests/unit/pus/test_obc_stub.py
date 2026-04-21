"""
Tests for OBC Stub — configurable OBSW behaviour simulator.
Implements: SVF-DEV-038
"""

import pytest
from svf.core.abstractions import SyncProtocol
from svf.stores.parameter_store import ParameterStore, ParameterEntry
from svf.stores.command_store import CommandStore
from svf.models.dhs.obc import ObcConfig, MODE_SAFE, MODE_NOMINAL
from svf.models.dhs.obc_stub import ObcStub, Rule


class _NoSync(SyncProtocol):
    def reset(self) -> None: pass
    def publish_ready(self, model_id: str, t: float) -> None: pass
    def wait_for_ready(self, expected: list[str], timeout: float) -> bool:
        return True


@pytest.fixture
def store() -> ParameterStore:
    return ParameterStore()


@pytest.fixture
def cmd_store() -> CommandStore:
    return CommandStore()


@pytest.fixture
def sync() -> _NoSync:
    return _NoSync()


def make_stub(
    store: ParameterStore,
    cmd_store: CommandStore,
    sync: _NoSync,
    rules: list[Rule] | None = None,
) -> ObcStub:
    config = ObcConfig(
        apid=0x101,
        watchdog_period_s=99999.0,
        initial_mode=MODE_NOMINAL,
    )
    stub = ObcStub(config, sync, store, cmd_store, rules=rules)
    stub.initialise()
    return stub


# ── Rule evaluation ───────────────────────────────────────────────────────────

@pytest.mark.requirement("SVF-DEV-038")
def test_rule_fires_when_condition_met(
    store: ParameterStore,
    cmd_store: CommandStore,
    sync: _NoSync,
) -> None:
    """Rule fires when watched parameter meets condition."""
    rule = Rule(
        name="low_soc",
        watch="eps.battery.soc",
        condition=lambda e: e is not None and e.value < 0.3,
        action=lambda cs, t: cs.inject(
            "dhs.obc.mode_cmd", float(MODE_SAFE), t=t,
            source_id="stub.low_soc"
        ),
    )
    stub = make_stub(store, cmd_store, sync, rules=[rule])

    store.write("eps.battery.soc", 0.2, t=0.0, model_id="eps")
    stub.do_step(t=0.0, dt=1.0)

    entry = cmd_store.peek("dhs.obc.mode_cmd")
    assert entry is not None
    assert entry.value == pytest.approx(float(MODE_SAFE))


@pytest.mark.requirement("SVF-DEV-038")
def test_rule_does_not_fire_when_condition_not_met(
    store: ParameterStore,
    cmd_store: CommandStore,
    sync: _NoSync,
) -> None:
    """Rule does not fire when condition is False."""
    rule = Rule(
        name="low_soc",
        watch="eps.battery.soc",
        condition=lambda e: e is not None and e.value < 0.3,
        action=lambda cs, t: cs.inject(
            "dhs.obc.mode_cmd", float(MODE_SAFE), t=t,
            source_id="stub.low_soc"
        ),
    )
    stub = make_stub(store, cmd_store, sync, rules=[rule])

    store.write("eps.battery.soc", 0.8, t=0.0, model_id="eps")
    stub.do_step(t=0.0, dt=1.0)

    entry = cmd_store.peek("dhs.obc.mode_cmd")
    assert entry is None


@pytest.mark.requirement("SVF-DEV-038")
def test_rule_does_not_fire_when_parameter_missing(
    store: ParameterStore,
    cmd_store: CommandStore,
    sync: _NoSync,
) -> None:
    """Rule does not fire when watched parameter not yet in store."""
    rule = Rule(
        name="low_soc",
        watch="eps.battery.soc",
        condition=lambda e: e is not None and e.value < 0.3,
        action=lambda cs, t: cs.inject(
            "dhs.obc.mode_cmd", float(MODE_SAFE), t=t,
            source_id="stub"
        ),
    )
    stub = make_stub(store, cmd_store, sync, rules=[rule])
    stub.do_step(t=0.0, dt=1.0)

    assert cmd_store.peek("dhs.obc.mode_cmd") is None


@pytest.mark.requirement("SVF-DEV-038")
def test_rule_fires_count_increments(
    store: ParameterStore,
    cmd_store: CommandStore,
    sync: _NoSync,
) -> None:
    """fired counter increments each time rule fires."""
    rule = Rule(
        name="low_soc",
        watch="eps.battery.soc",
        condition=lambda e: e is not None and e.value < 0.3,
        action=lambda cs, t: None,
    )
    stub = make_stub(store, cmd_store, sync, rules=[rule])
    store.write("eps.battery.soc", 0.2, t=0.0, model_id="eps")

    stub.do_step(t=0.0, dt=1.0)
    stub.do_step(t=1.0, dt=1.0)

    assert stub.rule_fired_count("low_soc") == 2


# ── Rule management ───────────────────────────────────────────────────────────

@pytest.mark.requirement("SVF-DEV-038")
def test_disabled_rule_does_not_fire(
    store: ParameterStore,
    cmd_store: CommandStore,
    sync: _NoSync,
) -> None:
    """Disabled rule does not fire even when condition is met."""
    rule = Rule(
        name="low_soc",
        watch="eps.battery.soc",
        condition=lambda e: e is not None and e.value < 0.3,
        action=lambda cs, t: cs.inject(
            "dhs.obc.mode_cmd", float(MODE_SAFE), t=t,
            source_id="stub"
        ),
        enabled=False,
    )
    stub = make_stub(store, cmd_store, sync, rules=[rule])
    store.write("eps.battery.soc", 0.2, t=0.0, model_id="eps")
    stub.do_step(t=0.0, dt=1.0)

    assert cmd_store.peek("dhs.obc.mode_cmd") is None


@pytest.mark.requirement("SVF-DEV-038")
def test_enable_disable_rule_at_runtime(
    store: ParameterStore,
    cmd_store: CommandStore,
    sync: _NoSync,
) -> None:
    """Rules can be enabled and disabled at runtime."""
    rule = Rule(
        name="low_soc",
        watch="eps.battery.soc",
        condition=lambda e: e is not None and e.value < 0.3,
        action=lambda cs, t: cs.inject(
            "dhs.obc.mode_cmd", float(MODE_SAFE), t=t,
            source_id="stub"
        ),
    )
    stub = make_stub(store, cmd_store, sync, rules=[rule])
    store.write("eps.battery.soc", 0.2, t=0.0, model_id="eps")

    stub.disable_rule("low_soc")
    stub.do_step(t=0.0, dt=1.0)
    assert cmd_store.peek("dhs.obc.mode_cmd") is None

    stub.enable_rule("low_soc")
    stub.do_step(t=1.0, dt=1.0)
    assert cmd_store.peek("dhs.obc.mode_cmd") is not None


@pytest.mark.requirement("SVF-DEV-038")
def test_once_rule_fires_only_once(
    store: ParameterStore,
    cmd_store: CommandStore,
    sync: _NoSync,
) -> None:
    """Rule with once=True disables itself after first firing."""
    rule = Rule(
        name="boot_init",
        watch="eps.battery.soc",
        condition=lambda e: e is not None and e.value > 0.0,
        action=lambda cs, t: cs.inject(
            "dhs.obc.mode_cmd", float(MODE_NOMINAL), t=t,
            source_id="stub"
        ),
        once=True,
    )
    stub = make_stub(store, cmd_store, sync, rules=[rule])
    store.write("eps.battery.soc", 0.8, t=0.0, model_id="eps")

    stub.do_step(t=0.0, dt=1.0)
    stub.do_step(t=1.0, dt=1.0)
    stub.do_step(t=2.0, dt=1.0)

    assert stub.rule_fired_count("boot_init") == 1
    assert not rule.enabled


@pytest.mark.requirement("SVF-DEV-038")
def test_add_rule_at_runtime(
    store: ParameterStore,
    cmd_store: CommandStore,
    sync: _NoSync,
) -> None:
    """Rules can be added after stub creation."""
    stub = make_stub(store, cmd_store, sync, rules=[])

    stub.add_rule(Rule(
        name="dynamic_rule",
        watch="eps.battery.soc",
        condition=lambda e: e is not None and e.value < 0.5,
        action=lambda cs, t: cs.inject(
            "dhs.obc.mode_cmd", float(MODE_SAFE), t=t,
            source_id="stub"
        ),
    ))

    store.write("eps.battery.soc", 0.3, t=0.0, model_id="eps")
    stub.do_step(t=0.0, dt=1.0)
    assert cmd_store.peek("dhs.obc.mode_cmd") is not None


# ── Integration: stub + OBC DHS ───────────────────────────────────────────────

@pytest.mark.requirement("SVF-DEV-038")
def test_stub_rule_triggers_mode_transition(
    store: ParameterStore,
    cmd_store: CommandStore,
    sync: _NoSync,
) -> None:
    """Stub rule injects mode command which OBC DHS processes next tick."""
    rule = Rule(
        name="low_soc_safe",
        watch="eps.battery.soc",
        condition=lambda e: e is not None and e.value < 0.3,
        action=lambda cs, t: cs.inject(
            "dhs.obc.mode_cmd", float(MODE_SAFE), t=t,
            source_id="stub"
        ),
    )
    stub = make_stub(store, cmd_store, sync, rules=[rule])
    stub._mode = MODE_NOMINAL

    store.write("eps.battery.soc", 0.2, t=0.0, model_id="eps")
    stub.on_tick(t=0.0, dt=1.0)  # rule fires, injects command
    stub.on_tick(t=1.0, dt=1.0)  # command consumed into port, rule fires again
    stub.on_tick(t=2.0, dt=1.0)  # port value processed, mode transitions

    assert stub.mode == MODE_SAFE


@pytest.mark.requirement("SVF-DEV-038")
def test_stub_inherits_pus_routing(
    store: ParameterStore,
    cmd_store: CommandStore,
    sync: _NoSync,
) -> None:
    """ObcStub inherits full PUS TC routing from ObcEquipment."""
    import struct
    from svf.pus.tc import PusTcPacket, PusTcBuilder

    config = ObcConfig(
        apid=0x101,
        param_id_map={0x2021: "aocs.rw1.torque_cmd"},
        watchdog_period_s=99999.0,
    )
    stub = ObcStub(config, sync, store, cmd_store)
    stub.initialise()

    tc = PusTcPacket(
        apid=0x100, sequence_count=1,
        service=17, subservice=1,
    )
    responses = stub.receive_tc(PusTcBuilder().build(tc), t=0.0)
    tm_17 = [r for r in responses if r.service == 17 and r.subservice == 2]
    assert len(tm_17) == 1
