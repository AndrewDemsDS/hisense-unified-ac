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
