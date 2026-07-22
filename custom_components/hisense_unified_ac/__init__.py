"""Hisense W41H1 Unified AC.

Merges a de-clouded W41H1's native Matter climate + fan + special-mode switches into a
single climate entity, and adds diagnostics (compressor Hz, faults, capabilities, bus link)
read from the manufacturer cluster via python-matter-server (docs/14). Configured via the UI.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import CONF_MATTER_URL, CONF_NAME, CONF_NODE_ID, DOMAIN
from .coordinator import HisenseDiagCoordinator

PLATFORMS: list[Platform] = [
    Platform.CLIMATE,
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a unified AC (+ optional diagnostics coordinator) from a config entry."""
    store: dict = {}
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = store

    url = entry.data.get(CONF_MATTER_URL)
    node_id = entry.data.get(CONF_NODE_ID)
    if url and node_id is not None:
        coord = HisenseDiagCoordinator(
            hass, url, int(node_id), entry.data.get(CONF_NAME) or "Unified AC"
        )
        # Diagnostics are optional: a failed first read must not block the climate entity,
        # so use async_refresh() (which does not raise) rather than the first-refresh helper.
        await coord.async_refresh()
        store["diag"] = coord

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unloaded


async def _async_reload(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when its options change."""
    await hass.config_entries.async_reload(entry.entry_id)
