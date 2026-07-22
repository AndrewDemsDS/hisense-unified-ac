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
FAN_PERCENT = {"low": 25, "medium": 58, "high": 100}

# Sleep ModeSelect option that means "sleep on" / "sleep off".
SLEEP_ON_OPTION = "General"
SLEEP_OFF_OPTION = "Off"

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
