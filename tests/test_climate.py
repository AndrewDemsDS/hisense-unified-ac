"""What the unified climate advertises, reports, and sends. Needs `homeassistant` importable."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from stubs import (
    COOL_ONLY_FEATURES1,
    base_states,
    make_climate,
    run,
    run_no_wait,
    state,
)

from homeassistant.components.climate import ClimateEntityFeature, HVACMode
from homeassistant.exceptions import ServiceValidationError

from hisense_unified_ac.const import COMBO_SETTLE_SECONDS

ALL_PRESETS = [
    "none",
    "eco",
    "quiet",
    "turbo",
    "eco_quiet",
    "sleep_general",
    "sleep_old",
    "sleep_young",
    "sleep_kids",
    # eco coexists with every sleep profile on the hardware (measured, all four), so each
    # pair gets its own preset value. Nothing pairs quiet or turbo with sleep: those are
    # mutually exclusive at the A/C.
    "eco_sleep_general",
    "eco_sleep_old",
    "eco_sleep_young",
    "eco_sleep_kids",
]


# --------------------------------------------------------------- what it advertises
def test_a_fully_wired_unit_advertises_everything() -> None:
    entity, _ = make_climate()
    assert entity.preset_modes == ALL_PRESETS
    assert entity.hvac_modes == [
        HVACMode.OFF,
        HVACMode.COOL,
        HVACMode.HEAT,
        HVACMode.HEAT_COOL,
        HVACMode.DRY,
        HVACMode.FAN_ONLY,
    ]
    features = entity.supported_features
    for wanted in (
        ClimateEntityFeature.PRESET_MODE,
        ClimateEntityFeature.FAN_MODE,
        ClimateEntityFeature.SWING_MODE,
        ClimateEntityFeature.TARGET_TEMPERATURE,
        ClimateEntityFeature.TURN_ON,
        ClimateEntityFeature.TURN_OFF,
    ):
        assert features & wanted, wanted


def test_hvac_modes_mirror_the_native_climate() -> None:
    # Without the extra-hvac-modes unlock the native entity omits dry / fan-only, and we
    # must not offer what it would reject.
    entity, _ = make_climate(
        base_states()
        | {"climate.b": state("cool", hvac_modes=["off", "cool", "heat", "heat_cool"])}
    )
    assert HVACMode.DRY not in entity.hvac_modes
    assert HVACMode.FAN_ONLY not in entity.hvac_modes


def test_a_cooling_only_unit_loses_heat_and_its_gated_presets() -> None:
    # Native entity unavailable, so the capability word is the only source.
    entity, _ = make_climate(
        base_states() | {"climate.b": state("unavailable")},
        features1=COOL_ONLY_FEATURES1,
    )
    assert entity.hvac_modes == [
        HVACMode.OFF,
        HVACMode.COOL,
        HVACMode.DRY,
        HVACMode.FAN_ONLY,
    ]
    # eco and quiet are gated out by power_save/fan_mute being absent, so no combination
    # either. Turbo and the sleep profiles have no capability bit, so they stay.
    # No eco means no eco+sleep pairs either.
    assert entity.preset_modes == [
        "none",
        "turbo",
        "sleep_general",
        "sleep_old",
        "sleep_young",
        "sleep_kids",
    ]


def test_nothing_wired_but_the_climate_advertises_nothing_extra() -> None:
    entity, _ = make_climate(config={"base_climate": "climate.b", "name": "AC"})
    assert entity.preset_modes == ["none"]
    features = entity.supported_features
    assert not features & ClimateEntityFeature.FAN_MODE
    assert not features & ClimateEntityFeature.SWING_MODE
    assert not features & ClimateEntityFeature.PRESET_MODE
    assert features & ClimateEntityFeature.TARGET_TEMPERATURE


def test_without_diagnostics_gating_is_permissive() -> None:
    entity, _ = make_climate(features1=None)
    assert entity.preset_modes == ALL_PRESETS
    assert len(entity.hvac_modes) == 6


def test_sleep_presets_follow_the_selects_own_option_list() -> None:
    # The firmware owns SupportedModes, so a unit reporting fewer profiles offers fewer.
    entity, _ = make_climate(
        base_states() | {"select.s": state("Off", options=["Off", "General"])}
    )
    assert entity.preset_modes == [
        "none",
        "eco",
        "quiet",
        "turbo",
        "eco_quiet",
        "sleep_general",
        "eco_sleep_general",
    ]


# ------------------------------------------------------------------ what it reports
def _reporting(**engaged: object):
    states = base_states()
    for key, entity_id in (
        ("eco", "switch.e"),
        ("quiet", "switch.q"),
        ("turbo", "switch.t"),
    ):
        if engaged.get(key):
            states[entity_id] = state("on")
    if profile := engaged.get("sleep"):
        states["select.s"] = state(
            str(profile), options=["Off", "General", "Old", "Young", "Kids"]
        )
    entity, _ = make_climate(states)
    return entity


def test_reports_every_single_and_the_combination() -> None:
    assert _reporting().preset_mode == "none"
    assert _reporting(eco=True).preset_mode == "eco"
    assert _reporting(quiet=True).preset_mode == "quiet"
    assert _reporting(turbo=True).preset_mode == "turbo"
    assert _reporting(eco=True, quiet=True).preset_mode == "eco_quiet"


def test_reports_the_running_sleep_profile_by_name() -> None:
    for profile in ("General", "Old", "Young", "Kids"):
        entity = _reporting(sleep=profile)
        assert entity.preset_mode == f"sleep_{profile.lower()}"


def test_reports_eco_plus_a_profile_as_its_own_state() -> None:
    # These genuinely coexist, so the pair is a real state and must be named as one.
    for profile in ("General", "Old", "Young", "Kids"):
        assert (
            _reporting(eco=True, sleep=profile).preset_mode
            == f"eco_sleep_{profile.lower()}"
        )


def test_an_impossible_pair_reports_the_strongest_mid_arbitration() -> None:
    # quiet+sleep and turbo+sleep cannot hold, so seeing both means the A/C has not
    # finished dropping one. Report something real rather than snapping to none.
    assert _reporting(turbo=True, sleep="General").preset_mode == "turbo"
    assert _reporting(quiet=True, sleep="Kids").preset_mode == "quiet"


def test_never_reports_a_preset_it_does_not_advertise() -> None:
    # eco is gated out by the capability word, but its switch reads on.
    entity, _ = make_climate(
        base_states() | {"switch.e": state("on")}, features1=COOL_ONLY_FEATURES1
    )
    assert "eco" not in entity.preset_modes
    assert entity.preset_mode == "none"


def test_fan_mode_is_unknown_rather_than_a_guess() -> None:
    # Reporting "auto" when the fan has not told us its mode would claim a speed the unit
    # is not running: right after a restart it can be sitting at Low with quiet on, which
    # is what made the fan look stuck. Cover BOTH ways the mode can be missing, since an
    # unavailable fan short-circuits earlier and would hide a default creeping back in.
    entity, _ = make_climate(base_states() | {"fan.f": state("unavailable")})
    assert entity.fan_mode is None
    entity, _ = make_climate(
        base_states() | {"fan.f": state("on")}
    )  # up, no preset_mode
    assert entity.fan_mode is None
    entity, _ = make_climate({})  # no fan entity in the machine at all
    assert entity.fan_mode is None
    entity, _ = make_climate(base_states() | {"fan.f": state("on", preset_mode="low")})
    assert entity.fan_mode == "low"


def test_setpoint_is_hidden_outside_cool_and_heat() -> None:
    for mode in ("dry", "fan_only", "off", "heat_cool"):
        entity, _ = make_climate(
            base_states()
            | {"climate.b": state(mode, hvac_modes=["off", "cool"], temperature=22)}
        )
        assert entity.target_temperature is None, mode
    entity, _ = make_climate()
    assert entity.target_temperature == 22


# ------------------------------------------------------------------- what it sends
def _sent(preset: str, states: dict | None = None):
    entity, recorder = make_climate(states)
    _, waits = run_no_wait(entity.async_set_preset_mode(preset))
    return recorder.calls, waits


def test_a_switch_preset_clears_the_others_and_enables_its_own() -> None:
    calls, waits = _sent("eco", base_states() | {"switch.q": state("on")})
    assert calls == [
        ("switch", "turn_off", ["switch.q"], None),
        ("switch", "turn_on", "switch.e", None),
    ]
    assert waits == [COMBO_SETTLE_SECONDS]


def test_the_combination_enables_both_members_spaced() -> None:
    calls, waits = _sent("eco_quiet")
    assert calls == [
        ("switch", "turn_on", "switch.e", None),
        ("switch", "turn_on", "switch.q", None),
    ]
    assert waits == [COMBO_SETTLE_SECONDS]


def test_no_frame_is_sent_for_something_already_in_the_wanted_state() -> None:
    # Every frame costs a settle, so a no-op preset change must cost nothing.
    calls, waits = _sent(
        "eco_quiet", base_states() | {"switch.e": state("on"), "switch.q": state("on")}
    )
    assert calls == []
    assert waits == []


def test_a_sleep_preset_clears_the_switches_and_selects_the_profile() -> None:
    calls, waits = _sent("sleep_kids", base_states() | {"switch.e": state("on")})
    assert calls == [
        ("switch", "turn_off", ["switch.e"], None),
        ("select", "select_option", "select.s", "Kids"),
    ]
    assert waits == [COMBO_SETTLE_SECONDS]


def test_switching_between_sleep_profiles_only_moves_the_select() -> None:
    calls, waits = _sent(
        "sleep_general",
        base_states()
        | {
            "select.s": state(
                "Kids", options=["Off", "General", "Old", "Young", "Kids"]
            )
        },
    )
    assert calls == [("select", "select_option", "select.s", "General")]
    assert waits == []


def test_a_plain_switch_preset_turns_a_running_sleep_profile_off() -> None:
    # Plain "eco" means eco and nothing else, so it clears a running profile. Use
    # eco_sleep_* to keep both. quiet/turbo cannot hold sleep at all.
    calls, _ = _sent(
        "eco",
        base_states()
        | {
            "select.s": state(
                "Kids", options=["Off", "General", "Old", "Young", "Kids"]
            )
        },
    )
    assert ("select", "select_option", "select.s", "Off") in calls
    assert ("switch", "turn_on", "switch.e", None) in calls


def test_eco_plus_sleep_sends_eco_first_and_sleep_last() -> None:
    # Ordering is load-bearing: eco rides the combined frame, which re-asserts the fan,
    # and sleep owns the fan. Commanding eco after sleep loses the profile (measured).
    calls, waits = _sent("eco_sleep_kids")
    assert calls == [
        ("switch", "turn_on", "switch.e", None),
        ("select", "select_option", "select.s", "Kids"),
    ], calls
    assert waits == [COMBO_SETTLE_SECONDS]
    # And with quiet on to clear first, sleep is still last of the three frames.
    calls, _ = _sent("eco_sleep_general", base_states() | {"switch.q": state("on")})
    assert [c[1] for c in calls] == ["turn_off", "turn_on", "select_option"], calls
    assert calls[-1] == ("select", "select_option", "select.s", "General")


def test_switching_profile_while_eco_stays_on_only_moves_the_select() -> None:
    calls, waits = _sent(
        "eco_sleep_kids",
        base_states()
        | {
            "switch.e": state("on"),
            "select.s": state(
                "General", options=["Off", "General", "Old", "Young", "Kids"]
            ),
        },
    )
    assert calls == [("select", "select_option", "select.s", "Kids")]
    assert waits == []


def test_none_clears_everything_and_enables_nothing() -> None:
    calls, _ = _sent(
        "none",
        base_states()
        | {
            "switch.e": state("on"),
            "switch.t": state("on"),
            "select.s": state("General", options=["Off", "General"]),
        },
    )
    assert calls == [
        ("switch", "turn_off", ["switch.e", "switch.t"], None),
        ("select", "select_option", "select.s", "Off"),
    ]
    assert not any(service == "turn_on" for _, service, *_ in calls)


# -------------------------------------------------------------------- the fan guard
def _set_fan(fan_mode: str, **engaged: object) -> str:
    entity = _reporting(**engaged)
    try:
        run(entity.async_set_fan_mode(fan_mode))
    except ServiceValidationError as err:
        return "refused:" + str(err.translation_placeholders["preset"])
    return "allowed"


def test_the_guard_refuses_only_what_the_ac_would_overwrite() -> None:
    assert _set_fan("auto") == "allowed"
    # quiet and sleep pin the fan at low, turbo pins it high.
    assert _set_fan("auto", quiet=True) == "refused:quiet"
    assert _set_fan("medium", quiet=True) == "refused:quiet"
    assert _set_fan("low", quiet=True) == "allowed"
    assert _set_fan("auto", sleep="Kids") == "refused:sleep"
    assert _set_fan("low", sleep="Kids") == "allowed"
    assert _set_fan("auto", turbo=True) == "refused:turbo"
    assert _set_fan("high", turbo=True) == "allowed"
    # Turbo wins the arbitration order, so it is the one named.
    assert _set_fan("auto", quiet=True, turbo=True) == "refused:turbo"
    # Eco does not touch the fan.
    assert _set_fan("auto", eco=True) == "allowed"


def test_the_guard_stays_out_of_the_way_when_the_state_is_unknown() -> None:
    # An unavailable switch reads as absent, which is the permissive direction on purpose.
    entity, recorder = make_climate(base_states() | {"switch.q": state("unavailable")})
    run(entity.async_set_fan_mode("auto"))
    assert recorder.calls == [("fan", "set_preset_mode", "fan.f", None)]


def test_named_fan_speeds_go_through_the_percentage_path() -> None:
    entity, recorder = make_climate()
    run(entity.async_set_fan_mode("medium"))
    assert recorder.calls == [("fan", "set_percentage", "fan.f", None)]


if __name__ == "__main__":
    from _runner import run_module

    raise SystemExit(run_module(dict(globals())))
