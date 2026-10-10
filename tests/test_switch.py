"""The proxy switches: eco, turbo, quiet, panel display, beeper. Needs `homeassistant`."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))

from stubs import (
    COOL_ONLY_FEATURES1,
    FULL_CONFIG,
    REAL_FEATURES1,
    FakeRegistry,
    attach,
    make_store,
    row,
    run,
    setup_platform,
    state,
)

from homeassistant.const import EntityCategory

from hisense_unified_ac import switch
from hisense_unified_ac.switch import ProxySwitch, switch_keys

WITH_BOTH = FULL_CONFIG | {"display_switch": "switch.d", "beeper_switch": "switch.bp"}
ENTRY = SimpleNamespace(data=FULL_CONFIG, entry_id="e1")


def beeper(states: dict) -> tuple[ProxySwitch, object]:
    entity = ProxySwitch(ENTRY, "beeper_switch", "switch.bp")
    return entity, attach(entity, states)


def test_one_switch_per_endpoint_this_node_has() -> None:
    hass, entry, _ = make_store(WITH_BOTH)
    names = [e.name for e in setup_platform(switch, hass, entry)]
    assert names == ["Eco", "Turbo", "Quiet", "Panel display", "Beeper"]


def test_no_beeper_or_display_entity_on_firmware_without_the_endpoint() -> None:
    # Today's firmware: the beeper endpoint is not merged, and an AmebaZ2 unit whose
    # capability word gates the display has no display endpoint either. The contract is
    # no entity at all, not a permanently unavailable one.
    hass, entry, _ = make_store(FULL_CONFIG)
    names = [e.name for e in setup_platform(switch, hass, entry)]
    assert names == ["Eco", "Turbo", "Quiet"]


def test_a_unit_with_no_special_mode_endpoints_gets_no_switches() -> None:
    hass, entry, _ = make_store({"base_climate": "climate.b", "name": "AC"})
    assert setup_platform(switch, hass, entry) == []


def test_a_switch_left_over_from_a_removed_endpoint_is_cleaned_up() -> None:
    # The beeper existed, then a firmware change took the endpoint away. Its registry
    # row would otherwise stay on the device page, unavailable for good.
    registry = FakeRegistry(
        [
            row("switch.ac_beeper", "e1_switch_beeper", platform="hisense_unified_ac"),
            row("switch.ac_eco", "e1_switch_eco", platform="hisense_unified_ac"),
        ]
    )
    hass, entry, _ = make_store(FULL_CONFIG)
    setup_platform(switch, hass, entry, registry)
    assert registry.removed == ["switch.ac_beeper"]


def test_eco_and_quiet_follow_the_capability_gate_of_their_presets() -> None:
    assert switch_keys(WITH_BOTH, REAL_FEATURES1) == list(switch.SWITCHES)
    # A unit that reports no eco and no quiet gets neither switch, like the presets.
    assert switch_keys(WITH_BOTH, COOL_ONLY_FEATURES1) == [
        "turbo_switch",
        "display_switch",
        "beeper_switch",
    ]
    # Unknown is not unsupported: no capability word gates nothing.
    assert switch_keys(WITH_BOTH, None) == list(switch.SWITCHES)


def test_mirrors_the_native_switch_and_is_never_optimistic() -> None:
    entity, _ = beeper({"switch.bp": state("on")})
    assert entity.is_on is True and entity.available
    entity, _ = beeper({"switch.bp": state("off")})
    assert entity.is_on is False and entity.available


def test_is_unavailable_exactly_when_the_native_switch_is() -> None:
    for states in (
        {},
        {"switch.bp": state("unavailable")},
        {"switch.bp": state("unknown")},
    ):
        entity, _ = beeper(states)
        assert not entity.available
        assert entity.is_on is None


def test_forwards_on_and_off_to_the_native_switch() -> None:
    entity, recorder = beeper({"switch.bp": state("on")})
    run(entity.async_turn_off())
    run(entity.async_turn_on())
    assert recorder.calls == [
        ("switch", "turn_off", "switch.bp", None),
        ("switch", "turn_on", "switch.bp", None),
    ]


def test_looks_like_the_esphome_switch() -> None:
    # Config category puts them under "Configuration", where the ESPHome device has them.
    for key, (slug, name, _icon) in switch.SWITCHES.items():
        entity = ProxySwitch(ENTRY, key, "switch.x")
        assert entity.name == name
        assert entity.entity_category is EntityCategory.CONFIG
        assert entity.translation_key == slug
        assert entity.unique_id == f"e1_switch_{slug}"
        assert entity.has_entity_name


if __name__ == "__main__":
    from _runner import run_module

    raise SystemExit(run_module(dict(globals())))
