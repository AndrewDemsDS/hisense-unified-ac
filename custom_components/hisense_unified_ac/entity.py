"""Shared plumbing: the one device every entity hangs off, and read-through mirrors."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, State, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.event import async_track_state_change_event

from .const import CONF_NAME, DOMAIN

UNAVAILABLE_STATES = {"unavailable", "unknown", None}
DEFAULT_NAME = "Unified AC"


def device_info(entry: ConfigEntry) -> DeviceInfo:
    """The unified device. Every platform must describe it identically."""
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.data.get(CONF_NAME) or DEFAULT_NAME,
        manufacturer="Hisense (de-clouded W41H1)",
    )


class MirrorEntity(Entity):
    """Read-through proxy for one native Matter entity.

    State is mirrored and nothing is optimistic, the same pattern as the climate entity:
    if the A/C drops a mode itself, the proxy follows what the unit reports. It is
    unavailable exactly when its source is.
    """

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry, source: str, slug: str, name: str) -> None:
        self._source = source
        self._attr_name = name
        self._attr_unique_id = f"{entry.entry_id}_{slug}"
        self._attr_device_info = device_info(entry)

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_track_state_change_event(
                self.hass, [self._source], self._source_changed
            )
        )

    @callback
    def _source_changed(self, _event: Event) -> None:
        self.async_write_ha_state()

    def _source_state(self) -> State | None:
        return self.hass.states.get(self._source)

    @property
    def available(self) -> bool:
        s = self._source_state()
        return bool(s and s.state not in UNAVAILABLE_STATES)

    def _source_attr(self, name: str) -> Any:
        s = self._source_state()
        return s.attributes.get(name) if s else None


@callback
def remove_stale_entities(
    hass: HomeAssistant, entry: ConfigEntry, domain: str, absent_slugs: list[str]
) -> None:
    """Drop registry rows for optional entities this setup did not create.

    An optional entity exists only while its source does (an endpoint, an attribute).
    When the source goes away, for example after a firmware change, the row would
    otherwise stay on the device page as a permanently unavailable entity.
    """
    reg = er.async_get(hass)
    for slug in absent_slugs:
        entity_id = reg.async_get_entity_id(domain, DOMAIN, f"{entry.entry_id}_{slug}")
        if entity_id:
            reg.async_remove(entity_id)
