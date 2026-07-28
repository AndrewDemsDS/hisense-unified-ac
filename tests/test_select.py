"""The sleep profile select proxy. Needs `homeassistant` importable."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from stubs import SLEEP_OPTIONS, base_states, make_select, run, state

from hisense_unified_ac.const import SLEEP_PROFILE_OPTIONS


def test_mirrors_the_native_options_rather_than_hardcoding_them() -> None:
    entity, _ = make_select()
    assert entity.options == SLEEP_OPTIONS
    # A unit reporting a different list must be followed, since the firmware owns it.
    entity, _ = make_select(
        base_states() | {"select.s": state("Off", options=["Off", "General"])}
    )
    assert entity.options == ["Off", "General"]


def test_falls_back_to_the_constant_but_is_never_optionless() -> None:
    # Before the native entity has a state there is nothing to mirror, and a select with
    # no options cannot be used at all.
    entity, _ = make_select({})
    assert entity.options == list(SLEEP_PROFILE_OPTIONS)
    entity, _ = make_select(base_states() | {"select.s": state("unavailable")})
    assert entity.options == list(SLEEP_PROFILE_OPTIONS)


def test_reports_the_native_state_and_nothing_optimistic() -> None:
    for profile in SLEEP_OPTIONS:
        entity, _ = make_select(
            base_states() | {"select.s": state(profile, options=SLEEP_OPTIONS)}
        )
        assert entity.current_option == profile
        assert entity.available


def test_is_unavailable_and_optionless_in_state_when_the_native_entity_is() -> None:
    for missing in (state("unavailable"), state("unknown")):
        entity, _ = make_select(base_states() | {"select.s": missing})
        assert entity.current_option is None
        assert not entity.available
    entity, _ = make_select({})
    assert entity.current_option is None
    assert not entity.available


def test_forwards_the_write_to_the_native_select() -> None:
    entity, recorder = make_select()
    run(entity.async_select_option("Kids"))
    assert recorder.calls == [("select", "select_option", "select.s", "Kids")]


def test_is_not_created_when_the_unit_has_no_sleep_modeselect() -> None:
    # async_setup_entry returns early, so no permanently unavailable entity is published.
    import asyncio
    from types import SimpleNamespace

    from hisense_unified_ac.const import DOMAIN
    from hisense_unified_ac.select import async_setup_entry

    added: list = []
    entry = SimpleNamespace(data={"base_climate": "climate.b"}, entry_id="e1")
    hass = SimpleNamespace(
        data={DOMAIN: {"e1": {"config": {"base_climate": "climate.b"}}}}
    )
    asyncio.run(async_setup_entry(hass, entry, added.extend))
    assert added == []

    hass.data[DOMAIN]["e1"]["config"]["sleep_select"] = "select.s"
    asyncio.run(async_setup_entry(hass, entry, added.extend))
    assert len(added) == 1


if __name__ == "__main__":
    from _runner import run_module

    raise SystemExit(run_module(dict(globals())))
