"""Hisense W41H1 Unified AC.

Presents a de-clouded W41H1 on Matter as one device with the same entities as the
hisense-w41h1 ESPHome build: one climate entity (wrapping the native Matter climate + fan
+ special-mode switches), the special-mode / display / beeper switches, the sleep select,
the temperature and electrical sensors, and diagnostics (compressor Hz, faults,
capabilities, bus counters, bus link) read from the manufacturer cluster via
python-matter-server (docs/14). Configured via the UI.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr, entity_registry as er

from .const import CONF_BASE_CLIMATE, CONF_MATTER_URL, CONF_NAME, CONF_NODE_ID, DOMAIN
from .coordinator import HisenseDiagCoordinator
from .discovery import resolve_config
from .entity import DEFAULT_NAME, device_info

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.CLIMATE,
    Platform.SWITCH,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
]


def _effective_config(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, Any]:
    return resolve_config(
        hass, dict(entry.data), dict(entry.options), entry.data[CONF_BASE_CLIMATE]
    )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a unified AC (+ optional diagnostics coordinator) from a config entry."""
    store: dict = {}
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = store

    # Re-derive the siblings every setup and use them for whatever the entry does not
    # already name. An entry created before the firmware relabelled its switches stored
    # no eco/quiet/turbo, which left those presets advertised but dead; this heals it.
    # It is also how an entry created by an older version of this integration gets the
    # entities added since (switches, mirrored sensors) without being re-added.
    cfg = _effective_config(hass, entry)
    store["config"] = cfg
    _link_to_native_device(hass, entry)
    url = cfg.get(CONF_MATTER_URL)
    node_id = cfg.get(CONF_NODE_ID)
    if url and node_id is not None:
        coord = HisenseDiagCoordinator(
            hass, url, int(node_id), entry.data.get(CONF_NAME) or DEFAULT_NAME
        )
        # Diagnostics are optional: a failed first read must not block the climate entity,
        # so use async_refresh() (which does not raise) rather than the first-refresh helper.
        await coord.async_refresh()
        store["diag"] = coord

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    entry.async_on_unload(
        hass.bus.async_listen(
            er.EVENT_ENTITY_REGISTRY_UPDATED, _reload_on_new_sibling(hass, entry)
        )
    )
    return True


def _reload_on_new_sibling(hass: HomeAssistant, entry: ConfigEntry):
    """Reload when the A/C's native device gains an entity this integration can use.

    A firmware update that adds an endpoint (the beeper switch) makes Home Assistant
    create a new native entity. Nothing else tells this entry about it, so without this
    the new switch would only show up after a manual reload or a restart. The reload is
    only scheduled when discovery really resolves differently, so the dozens of registry
    events around it (including this integration's own entities) cost a dict compare.
    """

    @callback
    def handle(event: Event) -> None:
        if event.data.get("action") != "create":
            return
        store = hass.data.get(DOMAIN, {}).get(entry.entry_id)
        if store is None:
            return
        created = er.async_get(hass).async_get(event.data["entity_id"])
        if created is None or created.platform == DOMAIN:
            return
        if _effective_config(hass, entry) != store["config"]:
            _LOGGER.debug("%s: new native entity %s", entry.title, created.entity_id)
            hass.config_entries.async_schedule_reload(entry.entry_id)

    return handle


def _link_to_native_device(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Show the unified device as connected via the Matter node, with its firmware.

    Cosmetic: it adds the model, the firmware / hardware version and the "connected
    via" link that an ESPHome device page has. Everything else about the device comes
    from the entities' own device info, so a base climate with no device just skips it.
    """
    base = er.async_get(hass).async_get(entry.data[CONF_BASE_CLIMATE])
    if base is None or base.device_id is None:
        return
    devices = dr.async_get(hass)
    native = devices.async_get(base.device_id)
    if native is None or not native.identifiers:
        return
    info = device_info(entry)
    unified = devices.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers=info["identifiers"],
        name=info["name"],
        manufacturer=info["manufacturer"],
        model=native.model,
        sw_version=native.sw_version,
        hw_version=native.hw_version,
    )
    if unified.via_device_id != native.id:
        devices.async_update_device(unified.id, via_device_id=native.id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    return unloaded


async def _async_reload(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when its options change."""
    await hass.config_entries.async_reload(entry.entry_id)
