"""Capability decoding and gating. No Home Assistant needed: features.py imports only const.py."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _pkg  # noqa: E402

_pkg.install()

from hisense_unified_ac.const import (  # noqa: E402
    COMBO_SETTLE_SECONDS,
    FAN_FORCING_PRESETS,
    PRESET_ECO,
    PRESET_QUIET,
    PRESET_SLEEP,
    PRESET_TURBO,
)
from hisense_unified_ac.features import (  # noqa: E402
    HEAT_CAPABILITY,
    PRESET_CAPABILITY,
    PRESET_COMBOS,
    decode_features1,
    supports,
)

# Read live from node 14: valid + ext_valid, cool_heat + power_save + fan_mute + heat_8c
# + q_display set, power_display 1. The Capabilities sensor showed 5 flags true for it.
REAL_FEATURES1 = 3221292313
COOL_ONLY_FEATURES1 = 1 << 31  # valid, every flag absent, ext tier unknown


def test_decodes_a_real_capability_word() -> None:
    caps = decode_features1(REAL_FEATURES1)
    assert caps is not None
    assert sorted(k for k, v in caps.items() if v is True) == [
        "cool_heat",
        "fan_mute",
        "heat_8c",
        "power_save",
        "q_display",
    ]
    assert caps["power_display"] == 1
    assert caps["demand_resp"] == 0
    # The Capabilities sensor's state is this count, and it reads 5 on the live units.
    assert sum(1 for v in caps.values() if v is True) == 5


def test_unreported_or_invalid_word_gates_nothing() -> None:
    # Permissive on unknown, mirroring the firmware predicates: unknown is not unsupported.
    for value in (None, 0, 123, "x", 1 << 30, [], 3.5):
        assert decode_features1(value) is None
        assert supports(decode_features1(value), HEAT_CAPABILITY)
        assert supports(decode_features1(value), "power_save")


def test_absent_flags_gate_but_unknown_ext_tier_does_not() -> None:
    caps = decode_features1(COOL_ONLY_FEATURES1)
    assert caps is not None
    assert caps["cool_heat"] is False
    assert not supports(caps, HEAT_CAPABILITY)
    assert not supports(caps, "power_save")
    # ext-tier flags are unknown, not absent, when the reply was too short to carry them.
    assert caps["q_display"] is None
    assert supports(caps, "q_display")


def test_ext_tier_present_and_absent_is_a_hard_no() -> None:
    caps = decode_features1((1 << 31) | (1 << 30))
    assert caps is not None
    assert caps["q_display"] is False
    assert not supports(caps, "q_display")


def test_interlock_table_matches_the_hardware() -> None:
    # Measured on node 14: eco+quiet coexist; turbo is exclusive with everything, so it
    # must never appear in a combination.
    assert PRESET_COMBOS == {"eco_quiet": (PRESET_ECO, PRESET_QUIET)}
    for combo, members in PRESET_COMBOS.items():
        assert "turbo" not in members, combo
        assert "sleep" not in members, combo
        assert len(set(members)) == len(members), combo


def test_command_spacing_stays_above_the_measured_floor() -> None:
    # Measured on node 14 by commanding eco then quiet at varying gaps: at 6 s the second
    # command was swallowed every time, at 8 s and 12 s it engaged. Lowering this below 8
    # brings back silently dropped commands, which is exactly the bug that made
    # combinations look broken, so it is worth a test of its own.
    assert COMBO_SETTLE_SECONDS >= 8, (
        f"{COMBO_SETTLE_SECONDS}s is at or below the measured drop threshold"
    )


def test_a_fan_forcing_special_is_listed_for_each_mode_that_pins_the_fan() -> None:
    # Measured: quiet and sleep hold the fan at low, turbo holds it high, eco does not
    # touch it. Dropping one of these silently reopens the "fan change reverts a second
    # later" bug for that mode.
    assert FAN_FORCING_PRESETS == {
        PRESET_TURBO: "high",
        PRESET_QUIET: "low",
        PRESET_SLEEP: "low",
    }
    assert PRESET_ECO not in FAN_FORCING_PRESETS
    # Turbo first: it wins the A/C's arbitration, so it must be the one reported.
    assert next(iter(FAN_FORCING_PRESETS)) == PRESET_TURBO


def test_only_eco_and_quiet_have_capability_bits() -> None:
    # Turbo and the sleep profiles have no bit in the capability word, so they are gated
    # on their backing entity alone. Guard against a bit being invented here by mistake.
    assert PRESET_CAPABILITY == {PRESET_ECO: "power_save", PRESET_QUIET: "fan_mute"}


if __name__ == "__main__":
    from _runner import run_module

    raise SystemExit(run_module(dict(globals())))
