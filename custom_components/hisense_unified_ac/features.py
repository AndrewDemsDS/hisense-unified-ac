"""The per-unit capability matrix: decode HisenseFeatures, and gate on it.

One decoder shared by the Capabilities diagnostic sensor and the unified climate
entity, so what the climate advertises corresponds to what the unit reports rather
than to a hardcoded superset.

The gate mapping below mirrors the firmware predicates in
`firmware/src/rs485-driver/matter_aircon_map.h` (`matter_gate_eco`,
`matter_gate_quiet`, `matter_thermostat_featuremap`), including their permissive
rule: **unknown is not unsupported**, so a capability word that was never reported
or came back invalid gates nothing.
"""

from __future__ import annotations

from .const import (
    FEAT1_BITS,
    FEATURES1_DEMAND_RESP_SHIFT,
    FEATURES1_EXT_VALID_BIT,
    FEATURES1_POWER_DISPLAY_SHIFT,
    FEATURES1_VALID_BIT,
    PRESET_ECO,
    PRESET_QUIET,
)

# A decoded capability word. Single-bit flags are True (present) / False (absent) /
# None (unknown: an ext-tier flag whose reply was too short). None is permissive.
Capabilities = dict[str, object]

# --- The matrix: what the unified climate advertises <- which capability gates it ---
# Presets not listed here have no capability bit (turbo, sleep), so they are gated on
# their backing entity alone.
PRESET_CAPABILITY: dict[str, str] = {
    PRESET_ECO: "power_save",  # matter_gate_eco
    PRESET_QUIET: "fan_mute",  # matter_gate_quiet
}
# Heat + Auto exist only on a heat-pump unit; a cooling-only unit gets Cooling only
# (firmware: FeatureMap 35 vs 2 in matter_thermostat_featuremap).
HEAT_CAPABILITY = "cool_heat"

# --- The interlock matrix: which special modes may be commanded together ---
# From the per-driver interlocks in firmware/docs/05 "Special functions":
#   Turbo  shares the byte33 feature enum with eco, so Turbo XOR Eco is an exclusion in
#          the encoding itself, and at the A/C turbo also drops quiet and sleep (it maxes
#          power, they all reduce it). So turbo never combines: it stays on its own.
#   Quiet  forces the fan quiet but is independent of byte33 -> combines with eco.
# Sleep is deliberately absent: it is a five-profile ModeSelect, not a flag, so it lives
# on its own select entity (select.py) instead of being flattened into a preset. That
# keeps one writer per underlying attribute. It is not listed as a combination member
# because it cannot be one: quiet and sleep are mutually exclusive at the A/C, measured on
# node 14 in both orders (the second one commanded always drops the first). That is the
# A/C, not us: our mute frame leaves the sleep byte at 0x00 and our sleep frame leaves the
# mute byte at 0x00, and 0x00 is "don't touch" on this wire (the sniffed dongle's power-on
# frame carries 0x00 at byte 17 while its power-off frame carries an explicit 0x01).
# Eco and turbo also drop a running sleep profile, but their attribution is weaker: both
# ride the combined frame, which re-asserts the fan from the command shadow, and sleep owns
# the fan profile. So that may be our frame rather than an A/C interlock, and the stock app
# reportedly allows eco + sleep. Untested either way; do not read it as established.
# HA's preset is single-valued, so a combination is offered as its own preset value.
PRESET_COMBOS: dict[str, tuple[str, ...]] = {
    "eco_quiet": (PRESET_ECO, PRESET_QUIET),
}


def decode_features1(value: object) -> Capabilities | None:
    """Decode the packed HisenseFeatures word; None if unreported or not valid."""
    if not isinstance(value, int) or not (value >> FEATURES1_VALID_BIT) & 1:
        return None
    ext = bool((value >> FEATURES1_EXT_VALID_BIT) & 1)
    caps: Capabilities = {}
    for bit, key, _name, is_ext in FEAT1_BITS:
        # ext-tier flags are UNKNOWN (not False) when the reply was too short.
        caps[key] = None if (is_ext and not ext) else bool((value >> bit) & 1)
    caps["power_display"] = (value >> FEATURES1_POWER_DISPLAY_SHIFT) & 3
    caps["demand_resp"] = (value >> FEATURES1_DEMAND_RESP_SHIFT) & 3
    return caps


def supports(caps: Capabilities | None, key: str) -> bool:
    """Permissive capability test: only a hard False hides a feature."""
    return caps is None or caps.get(key) is not False
