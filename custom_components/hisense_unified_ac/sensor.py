"""Diagnostic sensors for the de-clouded Hisense W41H1: compressor Hz + capabilities.

Values come from the raw mfg-cluster attributes read via HisenseDiagCoordinator (docs/14).
"""

from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfFrequency
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_NAME,
    DOMAIN,
    FEAT1_BITS,
    FEATURES1_DEMAND_RESP_SHIFT,
    FEATURES1_EXT_VALID_BIT,
    FEATURES1_POWER_DISPLAY_SHIFT,
    FEATURES1_VALID_BIT,
)
from .coordinator import HisenseDiagCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the diagnostic sensors, if a diagnostics coordinator was configured."""
    coord: HisenseDiagCoordinator | None = hass.data[DOMAIN][entry.entry_id].get("diag")
    if coord is None:
        return
    async_add_entities(
        [CompressorHzSensor(coord, entry), CapabilitiesSensor(coord, entry)]
    )


def _device_info(entry: ConfigEntry) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.data.get(CONF_NAME) or "Unified AC",
        manufacturer="Hisense (de-clouded W41H1)",
    )


class CompressorHzSensor(CoordinatorEntity[HisenseDiagCoordinator], SensorEntity):
    """Raw compressor frequency (Hz). 0 = compressor idle; higher = working harder."""

    _attr_has_entity_name = True
    _attr_name = "Compressor frequency"
    _attr_translation_key = "compressor_frequency"  # icon in icons.json
    _attr_native_unit_of_measurement = UnitOfFrequency.HERTZ
    _attr_device_class = SensorDeviceClass.FREQUENCY
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coord: HisenseDiagCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coord)
        self._attr_unique_id = f"{entry.entry_id}_compressor_hz"
        self._attr_device_info = _device_info(entry)

    @property
    def native_value(self) -> int | None:
        return self.coordinator.data.get("compressor_hz")


class CapabilitiesSensor(CoordinatorEntity[HisenseDiagCoordinator], SensorEntity):
    """Decoded per-unit capability flags (HisenseFeatures). State = count set; detail in attrs."""

    _attr_has_entity_name = True
    _attr_name = "Capabilities"
    _attr_translation_key = "capabilities"  # icon in icons.json
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coord: HisenseDiagCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coord)
        self._attr_unique_id = f"{entry.entry_id}_capabilities"
        self._attr_device_info = _device_info(entry)

    def _decode(self) -> tuple[int | None, dict]:
        v = self.coordinator.data.get("features1")
        if not isinstance(v, int) or not (v >> FEATURES1_VALID_BIT) & 1:
            return None, {}
        ext = bool((v >> FEATURES1_EXT_VALID_BIT) & 1)
        attrs: dict[str, object] = {}
        for bit, key, _name, is_ext in FEAT1_BITS:
            # ext-tier flags are UNKNOWN (not False) when the reply was too short.
            attrs[key] = None if (is_ext and not ext) else bool((v >> bit) & 1)
        attrs["power_display"] = (v >> FEATURES1_POWER_DISPLAY_SHIFT) & 3
        attrs["demand_resp"] = (v >> FEATURES1_DEMAND_RESP_SHIFT) & 3
        count = sum(1 for val in attrs.values() if val is True)
        return count, attrs

    @property
    def native_value(self) -> int | None:
        return self._decode()[0]

    @property
    def extra_state_attributes(self) -> dict:
        return self._decode()[1]
