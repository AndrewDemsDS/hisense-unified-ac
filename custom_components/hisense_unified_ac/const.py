"""Constants for the Hisense W41H1 Unified AC integration."""

DOMAIN = "hisense_unified_ac"

CONF_NAME = "name"
CONF_BASE_CLIMATE = "base_climate"
CONF_FAN = "fan"
CONF_ECO = "eco_switch"
CONF_QUIET = "quiet_switch"
CONF_TURBO = "turbo_switch"
CONF_SLEEP = "sleep_select"

# Preset names surfaced on the unified climate entity.
PRESET_NONE = "none"
PRESET_ECO = "eco"
PRESET_QUIET = "quiet"
PRESET_TURBO = "turbo"
PRESET_SLEEP = "sleep"

# Named fan modes -> percentage on the underlying Matter fan (the path that
# actually drives the A/C bus; auto uses the fan preset instead).
# The firmware ladder (k_hisense_fan_table in matter_aircon_map.h) has five named steps above
# quiet, and these are their PercentCurrent values. The names match the hisense-w41h1 ESPHome
# build's fan modes, so a climate group sees the same vocabulary on either firmware.
FAN_MODES = ["auto", "low", "medium_low", "medium", "medium_high", "high"]
FAN_PERCENT = {
    "low": 25,
    "medium_low": 42,
    "medium": 58,
    "medium_high": 75,
    "high": 100,
}


def fan_mode_from_percentage(pct: float) -> str:
    """Name a non-auto fan percentage, using the firmware's own bands.

    Mirrors percent_to_hisense_fan() in matter_aircon_map.h, so whatever percentage the
    firmware reports lands on the step it is actually running. The quiet band (<= 16) reads
    as low: quiet is a preset (the mute flag), not a fan mode, on both firmwares.
    """
    if pct <= 33:
        return "low"
    if pct <= 50:
        return "medium_low"
    if pct <= 67:
        return "medium"
    if pct <= 83:
        return "medium_high"
    return "high"


# The sleep ModeSelect option that means "no sleep profile".
SLEEP_OFF_OPTION = "Off"
# Each remaining profile is also offered as a climate preset named with this prefix
# ("General" -> "sleep_general"), so sleep is controllable from the thermostat card and
# not only from its own select. One preset per profile, so choosing sleep never has to
# guess which profile was meant.
SLEEP_PRESET_PREFIX = "sleep_"
# Its five profiles (ep6 cluster 80 SupportedModes 0-4), in firmware order. Only a
# fallback for the sleep select's options: the live list from the underlying entity is
# preferred, since the firmware owns this list.
SLEEP_PROFILE_OPTIONS = ("Off", "General", "Old", "Young", "Kids")

# This A/C debounces rapid commands: a special mode commanded too soon after another is
# swallowed outright. Measured on node 14 by commanding eco then quiet at varying gaps:
# 6 s FAILED repeatedly (quiet never engaged), 8 s and 12 s both engaged. 10 s is 8 with
# margin, since the threshold sits between 6 and 8 and bus load varies. Note this is the
# gap the NEXT command needs, not how long a mode takes to appear: once accepted, a mode
# reports back in about 3 s. Only paid when a preset command sends more than one frame.
COMBO_SETTLE_SECONDS = 10

# Special modes that own the A/C's fan profile, and the fan mode each pins it to
# (firmware/docs/05 "Special functions"). The A/C's quiet fan step has no Matter
# FanMode of its own, so it reads back as Low. While one of these is on, any other fan
# mode is overwritten about a second later by the next status downlink, so the unified
# climate refuses the change instead of reporting success for something that undoes
# itself. Order is the A/C's own arbitration: turbo wins, then quiet, then sleep.
FAN_FORCING_PRESETS = {
    PRESET_TURBO: "high",
    PRESET_QUIET: "low",
    PRESET_SLEEP: "low",
}

# --- Diagnostics: mfg-cluster attrs read RAW from python-matter-server (docs/14) ------
# HA's native Matter integration does not render a custom cluster, but matter-server stores
# every device-reported attribute at path "<endpoint>/<cluster_id>/<attr_id>", so we read
# those raw and build our own entities. Firmware packs the diagnostics into these attrs.
CONF_MATTER_URL = "matter_url"
CONF_NODE_ID = "node_id"
DEFAULT_MATTER_URL = "ws://homeassistant.local:5580/ws"
DIAG_SCAN_INTERVAL = (
    30  # seconds; diagnostics are slow-moving, matter-server keeps them fresh
)

MFG_CLUSTER = 4294048768  # 0xFFF1FC00
ATTR_COMPRESSOR_HZ = 16  # 0x0010 int8u, Hz
ATTR_FEATURES1 = 18  # 0x0012 int32u, packed HisenseFeatures
ATTR_FAULTS1 = 19  # 0x0013 int32u, packed HisenseFaults

# Bit contract. MUST match HISENSE_FAULT1_* / HISENSE_FEAT1_* in
# firmware/src/rs485-driver/hisense_rs485.h; a host test in the firmware repo
# (firmware/test/test_diag_contract.py) asserts these agree, so do not edit one side alone.
FAULTS1_VALID_BIT = 31
FAULTS1_ANY_BIT = 30
# (bit, key, friendly name) for the 18 named f_e_* fault bits, struct order.
FAULT1_BITS: list[tuple[int, str, str]] = [
    (0, "in_temp", "Indoor temp sensor"),
    (1, "in_coil_temp", "Indoor coil sensor"),
    (2, "in_humidity", "Indoor humidity sensor"),
    (3, "water_full", "Condensate tray full"),
    (4, "in_fan_motor", "Indoor fan motor"),
    (5, "grille", "Grille / up-down machine"),
    (6, "in_vzero", "Zero-cross detect"),
    (7, "in_com", "Indoor-outdoor comms"),
    (8, "in_display", "Indoor display"),
    (9, "in_keys", "Indoor keypad"),
    (10, "in_wifi", "Indoor Wi-Fi module"),
    (11, "in_ele", "Indoor electrical"),
    (12, "in_eeprom", "Indoor EEPROM"),
    (13, "out_eeprom", "Outdoor EEPROM"),
    (14, "out_coil_temp", "Outdoor coil sensor"),
    (15, "out_gas_temp", "Outdoor gas sensor"),
    (16, "out_temp", "Outdoor temp sensor"),
    (17, "over_temp", "Over-temp protection"),
]

FEATURES1_VALID_BIT = 31
FEATURES1_EXT_VALID_BIT = 30
FEATURES1_POWER_DISPLAY_SHIFT = 16  # 2-bit
FEATURES1_DEMAND_RESP_SHIFT = 18  # 2-bit
# (bit, key, friendly name, is_ext_tier) for the single-bit capability flags.
FEAT1_BITS: list[tuple[int, str, str, bool]] = [
    (0, "cool_heat", "Heat-pump (cool+heat)", False),
    (1, "ai", "AI / smart mode", False),
    (2, "infinite_fan", "Infinite fan speed", False),
    (3, "power_save", "Eco / power save", False),
    (4, "fan_mute", "Quiet / fan mute", False),
    (5, "swing_dir_8", "8-position louvre", False),
    (6, "swing_follow", "Swing follow", False),
    (7, "humidity", "Humidity sensing", False),
    (8, "heat_8c", "8 C frost-guard heat", False),
    (9, "purify", "Ionizer / purify", False),
    (10, "q_display", "Quiet display", True),
    (11, "enable_8heat", "8 C heat enable", True),
    (12, "trans_102_64", "Stock profile 199", True),
]
