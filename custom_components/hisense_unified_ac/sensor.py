"""Sensors, matching the ESPHome build's: temperatures, electrical, compressor, bus counters.

Three sources:
  * the native Matter sensors (outdoor / coil temperature, power, voltage, current) are
    re-exposed on the unified device under the ESPHome names, so one device page shows
    everything. They mirror the native entity and need nothing else.
  * compressor frequency and the capability word come from the mfg cluster, read raw
    through HisenseDiagCoordinator (docs/14), so they need the matter-server URL + node id.
  * the bus counters and the device type come from the same cluster but only exist on
    newer firmware; an entity is created per attribute the node actually reports
    (const.py, BUS_COUNTER_ATTRS and ATTR_LINK_TOKEN).
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfFrequency,
    UnitOfPower,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    BUS_COUNTER_ATTRS,
    CONF_COIL_TEMP,
    CONF_CURRENT,
    CONF_OUTDOOR_TEMP,
    CONF_POWER,
    CONF_VOLTAGE,
    DOMAIN,
    KEY_LINK_TOKEN,
    format_link_token,
)
from .coordinator import HisenseDiagCoordinator
from .entity import MirrorEntity, device_info, remove_stale_entities
from .features import decode_features1

# config key -> (unique-id slug, name, device class, fallback unit, display decimals).
# Names, classes and decimals are the ESPHome component's (sensor.py + w41h1.yaml).
MIRRORED: dict[str, tuple[str, str, SensorDeviceClass, str, int]] = {
    CONF_OUTDOOR_TEMP: (
        "outdoor_temperature",
        "Outdoor temperature",
        SensorDeviceClass.TEMPERATURE,
        UnitOfTemperature.CELSIUS,
        0,
    ),
    CONF_COIL_TEMP: (
        "coil_temperature",
        "Coil temperature",
        SensorDeviceClass.TEMPERATURE,
        UnitOfTemperature.CELSIUS,
        0,
    ),
    CONF_POWER: ("power", "Power", SensorDeviceClass.POWER, UnitOfPower.WATT, 0),
    CONF_VOLTAGE: (
        "voltage",
        "Voltage",
        SensorDeviceClass.VOLTAGE,
        UnitOfElectricPotential.VOLT,
        0,
    ),
    CONF_CURRENT: (
        "current",
        "Current",
        SensorDeviceClass.CURRENT,
        UnitOfElectricCurrent.AMPERE,
        2,
    ),
}


# Coordinator keys that become a sensor only when the node reports the attribute.
OPTIONAL_SENSORS = (*BUS_COUNTER_ATTRS, KEY_LINK_TOKEN)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the mirrored sensors, plus the diagnostics ones if a coordinator exists."""
    store = hass.data[DOMAIN][entry.entry_id]
    config: dict[str, Any] = store["config"]
    coord: HisenseDiagCoordinator | None = store.get("diag")

    entities: list[SensorEntity] = [
        MirrorSensor(entry, key, config[key]) for key in MIRRORED if config.get(key)
    ]
    absent = [MIRRORED[key][0] for key in MIRRORED if not config.get(key)]
    if coord is not None:
        entities += [CompressorHzSensor(coord, entry), CapabilitiesSensor(coord, entry)]
        if coord.last_update_success:
            # Only a successful read can say an attribute is gone; a failed one says
            # nothing.
            absent += [k for k in OPTIONAL_SENSORS if k not in (coord.data or {})]
    remove_stale_entities(hass, entry, "sensor", absent)
    async_add_entities(entities)

    if coord is None:
        return
    known: set[str] = set()

    @callback
    def add_new_optional() -> None:
        """Create an entity for each optional attribute that has none yet.

        Runs now and on every poll, so a node that gains the attributes through a
        firmware update gets its sensors without the entry being reloaded.
        """
        new = [
            key
            for key in OPTIONAL_SENSORS
            if key in (coord.data or {}) and key not in known
        ]
        if new:
            known.update(new)
            async_add_entities(
                LinkTokenSensor(coord, entry)
                if key == KEY_LINK_TOKEN
                else BusCounterSensor(coord, entry, key)
                for key in new
            )

    add_new_optional()
    entry.async_on_unload(coord.async_add_listener(add_new_optional))


class MirrorSensor(MirrorEntity, SensorEntity):
    """One native Matter sensor, re-exposed under its ESPHome name."""

    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, entry: ConfigEntry, key: str, source: str) -> None:
        slug, name, device_class, unit, decimals = MIRRORED[key]
        super().__init__(entry, source, slug, name)
        self._attr_device_class = device_class
        self._fallback_unit = unit
        self._attr_suggested_display_precision = decimals

    @property
    def native_unit_of_measurement(self) -> str:
        """The source's unit, since its state is already converted to that unit."""
        return self._source_attr("unit_of_measurement") or self._fallback_unit

    @property
    def native_value(self) -> float | None:
        s = self._source_state()
        if not s or not self.available:
            return None
        try:
            return float(s.state)
        except (TypeError, ValueError):
            return None


class CompressorHzSensor(CoordinatorEntity[HisenseDiagCoordinator], SensorEntity):
    """Raw compressor frequency (Hz). 0 = compressor idle; higher = working harder."""

    _attr_has_entity_name = True
    _attr_name = "Compressor frequency"
    _attr_translation_key = "compressor_frequency"  # icon in icons.json
    _attr_native_unit_of_measurement = UnitOfFrequency.HERTZ
    _attr_device_class = SensorDeviceClass.FREQUENCY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 0

    def __init__(self, coord: HisenseDiagCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coord)
        self._attr_unique_id = f"{entry.entry_id}_compressor_hz"
        self._attr_device_info = device_info(entry)

    @property
    def native_value(self) -> int | None:
        return (self.coordinator.data or {}).get("compressor_hz")


class BusCounterSensor(CoordinatorEntity[HisenseDiagCoordinator], SensorEntity):
    """One RS-485 bus counter since boot. A climbing count means trouble on the bus.

    The count restarts at 0 when the node reboots. `total_increasing` is the state
    class meant for that: Home Assistant's statistics read a drop as a new cycle
    starting from zero, so a reboot does not show up as a negative step. It is also
    what the ESPHome component declares for the same counters.
    """

    _attr_has_entity_name = True
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_suggested_display_precision = 0

    def __init__(
        self, coord: HisenseDiagCoordinator, entry: ConfigEntry, key: str
    ) -> None:
        super().__init__(coord)
        self._key = key
        self._attr_name = BUS_COUNTER_ATTRS[key][1]
        self._attr_translation_key = key  # icon in icons.json
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = device_info(entry)

    @property
    def native_value(self) -> int | None:
        return (self.coordinator.data or {}).get(self._key)


class LinkTokenSensor(CoordinatorEntity[HisenseDiagCoordinator], SensorEntity):
    """The device type / sub type pair the A/C reports in its DevType reply ("HH LL").

    A static per-model identifier the node stamps on its outbound frames. Unknown
    until the node has learned it (the attribute reads 0 until then).
    """

    _attr_has_entity_name = True
    _attr_name = "AC device type"
    _attr_translation_key = KEY_LINK_TOKEN  # icon in icons.json
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coord: HisenseDiagCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coord)
        self._attr_unique_id = f"{entry.entry_id}_{KEY_LINK_TOKEN}"
        self._attr_device_info = device_info(entry)

    @property
    def native_value(self) -> str | None:
        return format_link_token((self.coordinator.data or {}).get(KEY_LINK_TOKEN))


class CapabilitiesSensor(CoordinatorEntity[HisenseDiagCoordinator], SensorEntity):
    """The whole capability word in one entity. State = count set; detail in attrs.

    The per-flag binary sensors are the ESPHome-shaped view. This one stays because it
    is the only place the two-bit fields (power_display, demand_resp) are readable, but
    it is disabled on a fresh install since the ESPHome device has no equivalent.
    """

    _attr_has_entity_name = True
    _attr_name = "Capabilities"
    _attr_translation_key = "capabilities"  # icon in icons.json
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coord: HisenseDiagCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coord)
        self._attr_unique_id = f"{entry.entry_id}_capabilities"
        self._attr_device_info = device_info(entry)

    def _decode(self) -> tuple[int | None, dict]:
        attrs = decode_features1((self.coordinator.data or {}).get("features1"))
        if attrs is None:
            return None, {}
        count = sum(1 for val in attrs.values() if val is True)
        return count, attrs

    @property
    def native_value(self) -> int | None:
        return self._decode()[0]

    @property
    def extra_state_attributes(self) -> dict:
        return self._decode()[1]
