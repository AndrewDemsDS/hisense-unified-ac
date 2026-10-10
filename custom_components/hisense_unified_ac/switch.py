"""Switches: eco, turbo, quiet, panel display and beeper, as on the ESPHome build.

Each one proxies the native Matter OnOff endpoint of the same name, so the unified
device page has the same switches as the ESPHome device, with the same names, icons and
"Configuration" grouping. Eco, quiet and turbo are also climate presets; the switches
are the direct controls, and both views read the same endpoint so they always agree.

A switch is created only when its endpoint exists on this node. The beeper endpoint is
new firmware, and the display endpoint is gated per capability, so on a unit without
one there is simply no entity (rather than a permanently unavailable one). When a
firmware update adds the endpoint, the entry reloads itself and the switch appears.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_ECO, CONF_QUIET, DOMAIN, PRESET_ECO, PRESET_QUIET, SWITCHES
from .entity import MirrorEntity, remove_stale_entities
from .features import PRESET_CAPABILITY, decode_features1, supports

# Switches whose function the unit may report as absent (the same gate as the presets).
_CAPABILITY = {
    CONF_ECO: PRESET_CAPABILITY[PRESET_ECO],
    CONF_QUIET: PRESET_CAPABILITY[PRESET_QUIET],
}


def switch_keys(config: dict[str, Any], features1: object) -> list[str]:
    """Which switches this unit gets: a backing endpoint, and no hard capability no."""
    caps = decode_features1(features1)
    return [
        key
        for key in SWITCHES
        if config.get(key)
        and ((cap := _CAPABILITY.get(key)) is None or supports(caps, cap))
    ]


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up one proxy switch per special-mode / display / beeper endpoint found."""
    store = hass.data[DOMAIN][entry.entry_id]
    config = store["config"]
    coord = store.get("diag")
    features1 = coord.data.get("features1") if coord and coord.data else None
    keys = switch_keys(config, features1)
    remove_stale_entities(
        hass,
        entry,
        "switch",
        [f"switch_{SWITCHES[k][0]}" for k in SWITCHES if k not in keys],
    )
    async_add_entities(ProxySwitch(entry, key, config[key]) for key in keys)


class ProxySwitch(MirrorEntity, SwitchEntity):
    """Read-through proxy for one native Matter OnOff switch."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, entry: ConfigEntry, key: str, source: str) -> None:
        slug, name, _icon = SWITCHES[key]
        super().__init__(entry, source, f"switch_{slug}", name)
        self._attr_translation_key = slug  # icon in icons.json

    @property
    def is_on(self) -> bool | None:
        s = self._source_state()
        return s.state == "on" if s and self.available else None

    async def _forward(self, service: str) -> None:
        await self.hass.services.async_call(
            "switch", service, {"entity_id": self._source}, blocking=True
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._forward("turn_on")

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._forward("turn_off")
