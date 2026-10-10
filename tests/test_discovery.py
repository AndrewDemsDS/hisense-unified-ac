"""Discovery against the entity registry, and how a stored entry is resolved at setup.

Needs `homeassistant` importable (discovery.py reads the entity registry).
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))

from stubs import FakeRegistry, make_hass, row, state, use_registry

from hisense_unified_ac.discovery import (
    derive_node_id,
    derive_siblings,
    resolve_config,
)

NODE = "00000000000004D2-000000000000002A-MatterNodeDevice"


def native_rows() -> list[SimpleNamespace]:
    return [
        row("climate.b", f"{NODE}-1-MatterThermostat-513-0"),
        row("fan.f", f"{NODE}-1-MatterFan-514-0"),
        row("switch.e", f"{NODE}-3-MatterPlug-6-0", "Switch (Eco)"),
        row("switch.q", f"{NODE}-4-MatterPlug-6-0", "Switch (Quiet)"),
        row("switch.t", f"{NODE}-5-MatterPlug-6-0", "Switch (Turbo)"),
        row("switch.d", f"{NODE}-9-MatterPlug-6-0", "Switch (Display)"),
        row("select.s", f"{NODE}-6-MatterModeSelect-80-3", "Sleep"),
    ]


def derive(rows: list[SimpleNamespace], base: str = "climate.b") -> dict[str, str]:
    hass, _ = make_hass({})
    with use_registry(FakeRegistry(rows)):
        return derive_siblings(hass, base)


def test_finds_the_siblings_on_the_base_climates_device() -> None:
    assert derive(native_rows()) == {
        "fan": "fan.f",
        "eco_switch": "switch.e",
        "quiet_switch": "switch.q",
        "turbo_switch": "switch.t",
        "display_switch": "switch.d",
        "sleep_select": "select.s",
    }


def test_another_devices_entities_are_never_siblings() -> None:
    other = row("switch.other", "x", "Switch (Beeper)", device_id="dev2")
    assert "beeper_switch" not in derive([*native_rows(), other])


def test_this_integrations_own_entities_are_never_siblings() -> None:
    # If the unified entities ever share the device, a proxy must not wrap a proxy.
    own = row("switch.own", "e1_switch_beeper", "Beeper", platform="hisense_unified_ac")
    assert "beeper_switch" not in derive([*native_rows(), own])


def test_a_disabled_native_entity_is_not_a_sibling() -> None:
    # It has no state, so anything built on it would be permanently unavailable.
    rows = native_rows()
    beeper = row(
        "switch.bp", f"{NODE}-11-MatterPlug-6-0", "Switch (Beeper)", disabled_by="user"
    )
    assert "beeper_switch" not in derive([*rows, beeper])
    beeper.disabled_by = None
    assert derive([*rows, beeper])["beeper_switch"] == "switch.bp"


def test_an_unknown_or_deviceless_base_finds_nothing() -> None:
    assert derive(native_rows(), base="climate.missing") == {}
    assert derive([row("climate.b", "x", device_id=None), row("fan.f", "y")]) == {}


def resolve(
    data: dict, options: dict | None = None, states: dict | None = None
) -> dict:
    hass, _ = make_hass(states or {})
    with use_registry(FakeRegistry(native_rows())):
        return resolve_config(hass, data, options or {}, "climate.b")


def test_an_old_entry_gains_the_siblings_it_never_stored() -> None:
    # What an entry created by 1.5.0 looks like: no display switch key at all.
    cfg = resolve({"base_climate": "climate.b", "name": "AC", "fan": "fan.f"})
    assert cfg["display_switch"] == "switch.d"
    assert cfg["eco_switch"] == "switch.e"
    assert "beeper_switch" not in cfg  # this firmware has no beeper endpoint


def test_stored_values_and_options_still_win_over_discovery() -> None:
    states = {"switch.mine": state("off"), "switch.opt": state("off")}
    cfg = resolve(
        {"base_climate": "climate.b", "eco_switch": "switch.mine"},
        {"beeper_switch": "switch.opt"},
        states,
    )
    assert cfg["eco_switch"] == "switch.mine"
    assert cfg["beeper_switch"] == "switch.opt"


def test_a_stored_entity_that_no_longer_exists_is_replaced_by_the_live_one() -> None:
    cfg = resolve({"base_climate": "climate.b", "eco_switch": "switch.gone"})
    assert cfg["eco_switch"] == "switch.e"


def test_a_missing_stored_entity_with_no_replacement_is_left_alone() -> None:
    # Not in the registry and no state yet is also what a YAML entity looks like early
    # in startup, so without a live alternative the stored choice is kept.
    cfg = resolve({"base_climate": "climate.b", "beeper_switch": "switch.later"})
    assert cfg["beeper_switch"] == "switch.later"


def test_reads_the_node_id_from_the_base_climate() -> None:
    hass, _ = make_hass({})
    with use_registry(FakeRegistry(native_rows())):
        assert derive_node_id(hass, "climate.b") == 42
        assert derive_node_id(hass, "climate.missing") is None
    template = row(
        "climate.b", "0000000000000001-0000000000000002-x", platform="template"
    )
    with use_registry(FakeRegistry([template])):
        assert derive_node_id(hass, "climate.b") is None


# --------------------------------------------------- reload when the node gains an entity
def reload_harness(rows: list[SimpleNamespace]):
    """The registry listener of a set-up entry, plus what it would reload."""
    import importlib

    # The package __init__ is deliberately not executed by the test package stub, so
    # load it as a plain submodule to reach the listener.
    init = importlib.import_module("hisense_unified_ac.__init__")
    from hisense_unified_ac.const import DOMAIN

    registry = FakeRegistry(rows)
    reloads: list[str] = []
    hass, _ = make_hass({})
    hass.config_entries = SimpleNamespace(async_schedule_reload=reloads.append)
    entry = SimpleNamespace(
        data={"base_climate": "climate.b", "name": "AC"},
        options={},
        entry_id="e1",
        title="AC",
    )
    with use_registry(registry):
        config = resolve_config(hass, entry.data, {}, "climate.b")
    hass.data = {DOMAIN: {"e1": {"config": config}}}
    handle = init._reload_on_new_sibling(hass, entry)

    def fire(action: str, entity_id: str) -> None:
        event = SimpleNamespace(data={"action": action, "entity_id": entity_id})
        with use_registry(registry):
            handle(event)

    return registry, reloads, fire


def test_a_new_native_endpoint_reloads_the_entry_so_its_switch_appears() -> None:
    # The beeper arrives with a firmware update: Home Assistant registers a new native
    # switch on the node's device, and the entry has to pick it up by itself.
    registry, reloads, fire = reload_harness(native_rows())
    beeper = row("switch.bp", f"{NODE}-11-MatterPlug-6-0", "Switch (Beeper)")
    registry.entities[beeper.entity_id] = beeper
    fire("create", "switch.bp")
    assert reloads == ["e1"]


def test_registry_noise_does_not_reload_the_entry() -> None:
    registry, reloads, fire = reload_harness(native_rows())
    # An entity that fills no role (the unit's own power switch).
    power = row("switch.pw", f"{NODE}-1-MatterPlug-6-0", "Switch (Climate)")
    # Another device's beeper.
    other = row("switch.o", "x-11-MatterPlug-6-0", "Switch (Beeper)", device_id="dev2")
    # One of this integration's own entities being registered during setup.
    own = row("switch.own", "e1_switch_eco", "Eco", platform="hisense_unified_ac")
    for extra in (power, other, own):
        registry.entities[extra.entity_id] = extra
        fire("create", extra.entity_id)
    # A rename of an existing sibling, and an event for an entity already gone.
    fire("update", "switch.e")
    fire("create", "switch.vanished")
    assert reloads == []


if __name__ == "__main__":
    from _runner import run_module

    raise SystemExit(run_module(dict(globals())))
