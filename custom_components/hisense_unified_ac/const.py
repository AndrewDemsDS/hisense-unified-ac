"""Constants for the Hisense W41H1 Unified AC integration."""

DOMAIN = "hisense_unified_ac"

CONF_NAME = "name"
CONF_BASE_CLIMATE = "base_climate"
CONF_FAN = "fan"
CONF_ECO = "eco_switch"
CONF_QUIET = "quiet_switch"
CONF_TURBO = "turbo_switch"
CONF_SLEEP = "sleep_select"
# Siblings that are only re-exposed (never driven by the climate entity), so the unified
# device page carries the same entities as the hisense-w41h1 ESPHome build.
CONF_DISPLAY = "display_switch"
CONF_BEEPER = "beeper_switch"
CONF_OUTDOOR_TEMP = "outdoor_temperature_sensor"
CONF_COIL_TEMP = "coil_temperature_sensor"
CONF_POWER = "power_sensor"
CONF_VOLTAGE = "voltage_sensor"
CONF_CURRENT = "current_sensor"
CONF_AUX_HEAT = "aux_heat_sensor"
CONF_FAULT = "fault_sensor"
# Every key that names a native Matter entity found by discovery.py. One list, so the
# setup-time healing, the reload-on-new-entity check and the tests cannot disagree.
SIBLING_KEYS = (
    CONF_FAN,
    CONF_ECO,
    CONF_QUIET,
    CONF_TURBO,
    CONF_SLEEP,
    CONF_DISPLAY,
    CONF_BEEPER,
    CONF_OUTDOOR_TEMP,
    CONF_COIL_TEMP,
    CONF_POWER,
    CONF_VOLTAGE,
    CONF_CURRENT,
    CONF_AUX_HEAT,
    CONF_FAULT,
)

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

# --- Attributes newer firmware adds (all read-only, endpoint 1) -------------------------
# Not on every node, so nothing below is assumed to exist. An entity backed by one of
# these is created only when its path "1/<MFG_CLUSTER>/<id>" is present in the node's
# attribute data as matter-server reports it. On older firmware there is no entity at
# all, and one appears by itself (no reload) once an updated node starts reporting it.
ATTR_LINK_TOKEN = 0x0018  # int16u: device type in the high byte, sub type in the low
ATTR_BUS_LINK = 0x0019  # boolean: the A/C is answering on the RS-485 bus

# The four bus counters, int32u, counted since boot (they restart at 0 when the node
# reboots). key -> (attribute id, entity name, mdi icon). Names and icons are the ESPHome
# build's (firmware/esphome/w41h1.yaml and components/hisense_ac/sensor.py).
BUS_COUNTER_ATTRS: dict[str, tuple[int, str, str]] = {
    "checksum_errors": (0x0014, "Bus checksum errors", "mdi:alert-circle-outline"),
    "reply_timeouts": (0x0015, "Bus reply timeouts", "mdi:timer-alert-outline"),
    "unanswered_commands": (0x0016, "Unanswered commands", "mdi:message-alert-outline"),
    "link_losses": (0x0017, "Bus link losses", "mdi:lan-disconnect"),
}

# coordinator.data keys for the two attributes above.
KEY_LINK_TOKEN = "link_token"
KEY_BUS_LINK = "bus_link"
# Every optional attribute, by coordinator key. The one table the coordinator reads.
OPTIONAL_ATTRS: dict[str, int] = {
    **{key: attr for key, (attr, _name, _icon) in BUS_COUNTER_ATTRS.items()},
    KEY_LINK_TOKEN: ATTR_LINK_TOKEN,
    KEY_BUS_LINK: ATTR_BUS_LINK,
}


def format_link_token(value: object) -> str | None:
    """The device type / sub type pair as the ESPHome build prints it: "HH LL".

    None for anything that is not a learned token: 0 is the firmware's "not learned
    yet", and the A/C's DevType reply is what fills it in.
    """
    if isinstance(value, bool) or not isinstance(value, int) or not 0 < value <= 0xFFFF:
        return None
    return f"{value >> 8:02X} {value & 0xFF:02X}"


# Bit contract. MUST match HISENSE_FAULT1_* / HISENSE_FEAT1_* in
# firmware/src/rs485-driver/hisense_rs485.h; a host test in the firmware repo
# (firmware/test/test_diag_contract.py) asserts these agree, so do not edit one side alone.
FAULTS1_VALID_BIT = 31
FAULTS1_ANY_BIT = 30
# (bit, key, entity name) for the 18 named f_e_* fault bits, struct order. The names are the
# ESPHome component's defaults (FAULT_BITS in firmware/esphome/components/hisense_ac/
# binary_sensor.py), so a fault reads the same on either firmware.
FAULT1_BITS: list[tuple[int, str, str]] = [
    (0, "in_temp", "Fault indoor temp sensor"),
    (1, "in_coil_temp", "Fault indoor coil sensor"),
    (2, "in_humidity", "Fault indoor humidity sensor"),
    (3, "water_full", "Fault condensate tray full"),
    (4, "in_fan_motor", "Fault indoor fan motor"),
    (5, "grille", "Fault grille"),
    (6, "in_vzero", "Fault zero-cross detect"),
    (7, "in_com", "Fault indoor to outdoor comms"),
    (8, "in_display", "Fault indoor display"),
    (9, "in_keys", "Fault indoor keypad"),
    (10, "in_wifi", "Fault indoor wifi module"),
    (11, "in_ele", "Fault indoor electrical"),
    (12, "in_eeprom", "Fault indoor EEPROM"),
    (13, "out_eeprom", "Fault outdoor EEPROM"),
    (14, "out_coil_temp", "Fault outdoor coil sensor"),
    (15, "out_gas_temp", "Fault outdoor gas sensor"),
    (16, "out_temp", "Fault outdoor temp sensor"),
    (17, "over_temp", "Fault over temperature"),
]

FEATURES1_VALID_BIT = 31
FEATURES1_EXT_VALID_BIT = 30
FEATURES1_POWER_DISPLAY_SHIFT = 16  # 2-bit
FEATURES1_DEMAND_RESP_SHIFT = 18  # 2-bit
# (bit, key, entity name, is_ext_tier) for the single-bit capability flags. Names are the
# ESPHome component's defaults (CAPABILITY_BITS in the same file).
FEAT1_BITS: list[tuple[int, str, str, bool]] = [
    (0, "cool_heat", "Capability heat pump", False),
    (1, "ai", "Capability AI mode", False),
    (2, "infinite_fan", "Capability infinite fan", False),
    (3, "power_save", "Capability eco", False),
    (4, "fan_mute", "Capability quiet", False),
    (5, "swing_dir_8", "Capability 8-position louvre", False),
    (6, "swing_follow", "Capability swing follow", False),
    (7, "humidity", "Capability humidity", False),
    (8, "heat_8c", "Capability 8C frost guard", False),
    (9, "purify", "Capability purify", False),
    (10, "q_display", "Capability display control", True),
    (11, "enable_8heat", "Capability enable 8C heat", True),
    (12, "trans_102_64", "Capability trans 102-64", True),
]

# Which per-bit entities are enabled on a fresh install: the ones the ESPHome build's
# w41h1.yaml declares. The rest exist but start disabled, so the device page has the same
# rows on either firmware and the long tail is one click away. Enabled state is stored in
# the entity registry, so this never changes an entity that already exists.
FAULTS_ENABLED_BY_DEFAULT = frozenset({"in_temp", "in_com", "water_full", "out_temp"})
CAPABILITIES_ENABLED_BY_DEFAULT = frozenset({"cool_heat", "power_save", "fan_mute"})

# Icon per capability flag (a capability has no device class, so without one every flag
# shows the generic binary-sensor icon). Same icons as the ESPHome component.
CAPABILITY_ICONS: dict[str, str] = {
    "cool_heat": "mdi:heat-pump",
    "ai": "mdi:brain",
    "infinite_fan": "mdi:fan",
    "power_save": "mdi:leaf",
    "fan_mute": "mdi:volume-off",
    "swing_dir_8": "mdi:arrow-up-down",
    "swing_follow": "mdi:arrow-oscillating",
    "humidity": "mdi:water-percent",
    "heat_8c": "mdi:snowflake-thermometer",
    "purify": "mdi:air-purifier",
    "q_display": "mdi:television-ambient-light",
    "enable_8heat": "mdi:snowflake-thermometer",
    "trans_102_64": "mdi:swap-horizontal",
}

# --- Re-exposed switches: config key -> (unique-id slug, entity name, mdi icon) --------
# Names and icons are the ESPHome build's (w41h1.yaml, components/hisense_ac/switch.py).
# Each one proxies the native Matter OnOff endpoint that discovery.py found; a switch
# whose endpoint this firmware does not have is not created.
SWITCHES: dict[str, tuple[str, str, str]] = {
    CONF_ECO: ("eco", "Eco", "mdi:leaf"),
    CONF_TURBO: ("turbo", "Turbo", "mdi:fan-plus"),
    CONF_QUIET: ("quiet", "Quiet", "mdi:volume-off"),
    CONF_DISPLAY: ("display", "Panel display", "mdi:television-ambient-light"),
    CONF_BEEPER: ("beeper", "Beeper", "mdi:volume-high"),
}

# --- Sibling discovery rules (siblings.py) ---------------------------------------------
# A native Matter entity is recognised two ways, in this order:
#   1. by the endpoint label in its name. The firmware gives every endpoint a UserLabel
#      "ha_entitylabel", which Home Assistant appends to the entity name for test-vendor
#      devices ("Switch (Eco)", "Temperature (Coil)").
#   2. by where it lives on the node, read out of the Matter unique id
#      ("...-<endpoint>-<key>-<cluster>-<attribute>"). This is what still works on a Home
#      Assistant that ignores the label and names the entity "Switch (3)".
# key -> (domain, label words, (cluster, attribute), fallback endpoint or None).
# A None endpoint means the cluster and attribute are unique on the node, so any
# endpoint matches (the electrical sensors).
CLUSTER_ONOFF = 6
CLUSTER_BOOLEAN_STATE = 69  # 0x0045
CLUSTER_MODE_SELECT = 80  # 0x0050
CLUSTER_ELECTRICAL_POWER = 144  # 0x0090
CLUSTER_TEMPERATURE = 1026  # 0x0402
SIBLING_RULES: dict[str, tuple[str, tuple[str, ...], tuple[int, int], int | None]] = {
    CONF_ECO: ("switch", ("eco",), (CLUSTER_ONOFF, 0), 3),
    CONF_QUIET: ("switch", ("quiet", "mute"), (CLUSTER_ONOFF, 0), 4),
    CONF_TURBO: ("switch", ("turbo",), (CLUSTER_ONOFF, 0), 5),
    CONF_DISPLAY: ("switch", ("display",), (CLUSTER_ONOFF, 0), 9),
    CONF_BEEPER: ("switch", ("beeper", "buzzer"), (CLUSTER_ONOFF, 0), 11),
    CONF_OUTDOOR_TEMP: ("sensor", ("outdoor",), (CLUSTER_TEMPERATURE, 0), 2),
    CONF_COIL_TEMP: ("sensor", ("coil",), (CLUSTER_TEMPERATURE, 0), 8),
    CONF_VOLTAGE: ("sensor", (), (CLUSTER_ELECTRICAL_POWER, 4), None),
    CONF_CURRENT: ("sensor", (), (CLUSTER_ELECTRICAL_POWER, 5), None),
    CONF_POWER: ("sensor", (), (CLUSTER_ELECTRICAL_POWER, 8), None),
    CONF_AUX_HEAT: ("binary_sensor", ("aux",), (CLUSTER_BOOLEAN_STATE, 0), 7),
    CONF_FAULT: ("binary_sensor", ("fault",), (CLUSTER_BOOLEAN_STATE, 0), 10),
}
