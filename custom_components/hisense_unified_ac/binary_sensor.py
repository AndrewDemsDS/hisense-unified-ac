"""Diagnostic binary sensors: A/C faults (from Faults1) + RS-485 bus link health.

Faults come from the packed Faults1 mfg attribute (full per-bit detail in attributes);
bus link mirrors the firmware's #56 liveness (the base climate entity goes unavailable on
bus silence), needing no firmware/matter-server change (docs/14 Phase 1b).
"""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_BASE_CLIMATE,
    CONF_NAME,
    DOMAIN,
    FAULT1_BITS,
    FAULTS1_ANY_BIT,
    FAULTS1_VALID_BIT,
)
from .coordinator import HisenseDiagCoordinator

UNAVAILABLE = {"unavailable", "unknown", None}


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the fault (coordinator) + bus-link (availability) binary sensors."""
    store = hass.data[DOMAIN][entry.entry_id]
    entities: list[BinarySensorEntity] = []
    coord: HisenseDiagCoordinator | None = store.get("diag")
    if coord is not None:
        entities.append(FaultsBinarySensor(coord, entry))
    if entry.data.get(CONF_BASE_CLIMATE):
        entities.append(BusLinkBinarySensor(entry))
    async_add_entities(entities)


def _device_info(entry: ConfigEntry) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.data.get(CONF_NAME) or "Unified AC",
        manufacturer="Hisense (de-clouded W41H1)",
    )


class FaultsBinarySensor(CoordinatorEntity[HisenseDiagCoordinator], BinarySensorEntity):
    """PROBLEM sensor: on when any f_e_* fault is set. Per-fault detail in attributes.

    `any` matches the firmware aggregate (ep10) exactly: the frost-guard mode flag is
    already excluded, so this never cries wolf on a healthy unit in 8 C heat.
    """

    _attr_has_entity_name = True
    _attr_name = "Faults"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coord: HisenseDiagCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coord)
        self._attr_unique_id = f"{entry.entry_id}_faults"
        self._attr_device_info = _device_info(entry)

    def _valid_value(self) -> int | None:
        v = self.coordinator.data.get("faults1")
        if isinstance(v, int) and (v >> FAULTS1_VALID_BIT) & 1:
            return v
        return None

    @property
    def is_on(self) -> bool | None:
        v = self._valid_value()
        if v is None:
            return None
        return bool((v >> FAULTS1_ANY_BIT) & 1)

    @property
    def extra_state_attributes(self) -> dict:
        v = self._valid_value()
        if v is None:
            return {}
        attrs: dict[str, object] = {
            key: bool((v >> bit) & 1) for bit, key, _name in FAULT1_BITS
        }
        active = [name for bit, _key, name in FAULT1_BITS if (v >> bit) & 1]
        attrs["active"] = active or ["none"]
        return attrs


class BusLinkBinarySensor(BinarySensorEntity):
    """CONNECTIVITY sensor: on while the RS-485 bus is alive.

    The firmware nulls the standard liveness attributes on bus silence (#56), so the base
    climate entity goes unavailable. We simply mirror that, with no firmware/matter-server
    dependency.
    """

    _attr_has_entity_name = True
    _attr_name = "Bus link"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry) -> None:
        self._base = entry.data[CONF_BASE_CLIMATE]
        self._attr_unique_id = f"{entry.entry_id}_bus_link"
        self._attr_device_info = _device_info(entry)

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_track_state_change_event(self.hass, [self._base], self._changed)
        )

    @callback
    def _changed(self, _event: Event) -> None:
        self.async_write_ha_state()

    @property
    def is_on(self) -> bool:
        state = self.hass.states.get(self._base)
        return bool(state and state.state not in UNAVAILABLE)
