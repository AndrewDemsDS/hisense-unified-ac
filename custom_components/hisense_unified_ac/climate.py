"""Unified climate entity for a de-clouded Hisense W41H1.

Read-through wrapper: presents one climate entity whose state mirrors the native
Matter climate + fan, and whose commands fan out to them + the special-mode
switches. Setpoint is only meaningful in cool/heat, so it is gated there (a temp
change in dry/fan-only/auto/off is a no-op and reports no target).
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event

from .const import (
    CONF_BASE_CLIMATE,
    CONF_ECO,
    CONF_FAN,
    CONF_NAME,
    CONF_QUIET,
    CONF_SLEEP,
    CONF_TURBO,
    DOMAIN,
    FAN_PERCENT,
    PRESET_ECO,
    PRESET_NONE,
    PRESET_QUIET,
    PRESET_SLEEP,
    PRESET_TURBO,
    SLEEP_OFF_OPTION,
    SLEEP_ON_OPTION,
)

_LOGGER = logging.getLogger(__name__)

UNAVAILABLE_STATES = {"unavailable", "unknown", None}
# Modes where a target temperature is meaningful (setpoint gated to these).
SETPOINT_MODES = {HVACMode.COOL, HVACMode.HEAT}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the unified climate entity from a config entry."""
    async_add_entities([UnifiedClimate(entry)])


class UnifiedClimate(ClimateEntity):
    """A single climate entity wrapping the W41H1's native Matter entities."""

    _attr_should_poll = False
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_hvac_modes = [
        HVACMode.OFF,
        HVACMode.COOL,
        HVACMode.HEAT,
        HVACMode.HEAT_COOL,
        HVACMode.DRY,
        HVACMode.FAN_ONLY,
    ]
    _attr_fan_modes = ["auto", "low", "medium", "high"]
    _attr_swing_modes = ["off", "vertical"]
    _attr_preset_modes = [
        PRESET_NONE,
        PRESET_ECO,
        PRESET_QUIET,
        PRESET_TURBO,
        PRESET_SLEEP,
    ]
    _attr_min_temp = 16
    _attr_max_temp = 32
    _attr_target_temperature_step = 1
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.FAN_MODE
        | ClimateEntityFeature.SWING_MODE
        | ClimateEntityFeature.PRESET_MODE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )

    def __init__(self, entry: ConfigEntry) -> None:
        d = entry.data
        self._base: str = d[CONF_BASE_CLIMATE]
        self._fan: str | None = d.get(CONF_FAN)
        self._eco: str | None = d.get(CONF_ECO)
        self._quiet: str | None = d.get(CONF_QUIET)
        self._turbo: str | None = d.get(CONF_TURBO)
        self._sleep: str | None = d.get(CONF_SLEEP)
        self._attr_name = d.get(CONF_NAME) or "Unified AC"
        self._attr_unique_id = f"{entry.entry_id}_unified"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=self._attr_name,
            manufacturer="Hisense (de-clouded W41H1)",
        )

    # ------------------------------------------------------------------ helpers
    @property
    def _tracked(self) -> list[str]:
        return [
            e
            for e in (
                self._base,
                self._fan,
                self._eco,
                self._quiet,
                self._turbo,
                self._sleep,
            )
            if e
        ]

    def _state(self, entity_id: str | None):
        return self.hass.states.get(entity_id) if entity_id else None

    def _is_on(self, entity_id: str | None) -> bool:
        s = self._state(entity_id)
        return bool(s and s.state == "on")

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_track_state_change_event(
                self.hass, self._tracked, self._handle_change
            )
        )

    @callback
    def _handle_change(self, _event: Event) -> None:
        self.async_write_ha_state()

    # --------------------------------------------------------------- properties
    @property
    def available(self) -> bool:
        s = self._state(self._base)
        return bool(s and s.state not in UNAVAILABLE_STATES)

    @property
    def hvac_mode(self) -> HVACMode | None:
        s = self._state(self._base)
        if not s or s.state in UNAVAILABLE_STATES:
            return None
        try:
            return HVACMode(s.state)
        except ValueError:
            return None

    @property
    def hvac_action(self) -> HVACAction | None:
        s = self._state(self._base)
        action = s.attributes.get("hvac_action") if s else None
        try:
            return HVACAction(action) if action else None
        except ValueError:
            return None

    @property
    def current_temperature(self) -> float | None:
        s = self._state(self._base)
        return s.attributes.get("current_temperature") if s else None

    @property
    def target_temperature(self) -> float | None:
        # Setpoint only meaningful in cool/heat -> hide it elsewhere.
        if self.hvac_mode not in SETPOINT_MODES:
            return None
        s = self._state(self._base)
        return s.attributes.get("temperature") if s else None

    @property
    def fan_mode(self) -> str | None:
        s = self._state(self._fan)
        if not s:
            return "auto"
        return s.attributes.get("preset_mode") or "auto"

    @property
    def swing_mode(self) -> str:
        s = self._state(self._fan)
        return "vertical" if (s and s.attributes.get("oscillating")) else "off"

    @property
    def preset_mode(self) -> str:
        if self._is_on(self._turbo):
            return PRESET_TURBO
        if self._is_on(self._eco):
            return PRESET_ECO
        if self._is_on(self._quiet):
            return PRESET_QUIET
        s = self._state(self._sleep)
        if s and s.state not in ({SLEEP_OFF_OPTION} | UNAVAILABLE_STATES):
            return PRESET_SLEEP
        return PRESET_NONE

    # ----------------------------------------------------------------- commands
    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        await self.hass.services.async_call(
            "climate",
            "set_hvac_mode",
            {"entity_id": self._base, "hvac_mode": hvac_mode},
            blocking=True,
        )

    async def async_turn_on(self) -> None:
        await self.async_set_hvac_mode(HVACMode.COOL)

    async def async_turn_off(self) -> None:
        await self.async_set_hvac_mode(HVACMode.OFF)

    async def async_set_temperature(self, **kwargs: Any) -> None:
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return
        if self.hvac_mode not in SETPOINT_MODES:
            _LOGGER.debug(
                "%s: ignoring setpoint in mode %s", self.entity_id, self.hvac_mode
            )
            return
        await self.hass.services.async_call(
            "climate",
            "set_temperature",
            {"entity_id": self._base, "temperature": temperature},
            blocking=True,
        )

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        if not self._fan:
            return
        if fan_mode == "auto":
            await self.hass.services.async_call(
                "fan",
                "set_preset_mode",
                {"entity_id": self._fan, "preset_mode": "auto"},
                blocking=True,
            )
        else:
            await self.hass.services.async_call(
                "fan",
                "set_percentage",
                {
                    "entity_id": self._fan,
                    "percentage": FAN_PERCENT.get(fan_mode, 58),
                },
                blocking=True,
            )

    async def async_set_swing_mode(self, swing_mode: str) -> None:
        if not self._fan:
            return
        await self.hass.services.async_call(
            "fan",
            "oscillate",
            {"entity_id": self._fan, "oscillating": swing_mode == "vertical"},
            blocking=True,
        )

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        # Presets are mutually exclusive: clear all switches, set sleep select,
        # then enable the chosen one.
        switches = [e for e in (self._eco, self._quiet, self._turbo) if e]
        if switches:
            await self.hass.services.async_call(
                "switch", "turn_off", {"entity_id": switches}, blocking=True
            )
        if self._sleep:
            await self.hass.services.async_call(
                "select",
                "select_option",
                {
                    "entity_id": self._sleep,
                    "option": SLEEP_ON_OPTION
                    if preset_mode == PRESET_SLEEP
                    else SLEEP_OFF_OPTION,
                },
                blocking=True,
            )
        target = {
            PRESET_ECO: self._eco,
            PRESET_QUIET: self._quiet,
            PRESET_TURBO: self._turbo,
        }.get(preset_mode)
        if target:
            await self.hass.services.async_call(
                "switch", "turn_on", {"entity_id": target}, blocking=True
            )
