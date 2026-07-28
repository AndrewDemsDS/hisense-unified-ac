"""Sleep profile select: proxies the A/C's native sleep ModeSelect entity.

Sleep is a five-option ModeSelect on ep6 (Off/General/Old/Young/Kids), but it used to
reach Home Assistant only as an on/off climate preset, which could express one profile
and silently rewrote the other three. It gets its own dropdown instead, so all five are
selectable and sleep stays orthogonal to the presets, which is how the A/C treats it.

Read-through proxy, the same pattern as the climate entity: state is mirrored from the
underlying select, commands are forwarded to it. Nothing here is optimistic, so if the
A/C cancels a profile itself (turbo drops sleep) or the command debounce eats a write,
the dropdown snaps back to what the A/C actually reports rather than lying.
"""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event

from .const import CONF_NAME, CONF_SLEEP, DOMAIN, SLEEP_PROFILE_OPTIONS

UNAVAILABLE_STATES = {"unavailable", "unknown", None}


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the sleep profile select, if this unit has a sleep ModeSelect wired up."""
    config = hass.data[DOMAIN][entry.entry_id]["config"]
    if not (sleep := config.get(CONF_SLEEP)):
        return
    async_add_entities([SleepProfileSelect(entry, sleep)])


class SleepProfileSelect(SelectEntity):
    """Read-through proxy for the native sleep ModeSelect."""

    _attr_has_entity_name = True
    _attr_name = "Sleep profile"
    _attr_translation_key = "sleep_profile"  # icons in icons.json
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry, sleep_entity_id: str) -> None:
        self._sleep = sleep_entity_id
        self._attr_unique_id = f"{entry.entry_id}_sleep_profile"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.data.get(CONF_NAME) or "Unified AC",
            manufacturer="Hisense (de-clouded W41H1)",
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_track_state_change_event(
                self.hass, [self._sleep], self._handle_change
            )
        )

    @callback
    def _handle_change(self, _event: Event) -> None:
        self.async_write_ha_state()

    def _state(self):
        return self.hass.states.get(self._sleep)

    @property
    def available(self) -> bool:
        s = self._state()
        return bool(s and s.state not in UNAVAILABLE_STATES)

    @property
    def options(self) -> list[str]:
        """Mirror the native select's options rather than hardcoding them.

        The firmware owns this list (ModeSelect SupportedModes), so mirroring it means a
        drift cannot make this entity offer an option the A/C would reject. The constant
        is only a fallback for the moment before the native entity has a state, so this
        select is never optionless.
        """
        s = self._state()
        options = s.attributes.get("options") if s else None
        return list(options) if options else list(SLEEP_PROFILE_OPTIONS)

    @property
    def current_option(self) -> str | None:
        s = self._state()
        if not s or s.state in UNAVAILABLE_STATES:
            return None
        return s.state

    async def async_select_option(self, option: str) -> None:
        await self.hass.services.async_call(
            "select",
            "select_option",
            {"entity_id": self._sleep, "option": option},
            blocking=True,
        )
