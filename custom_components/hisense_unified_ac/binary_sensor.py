"""Binary sensors, matching the ESPHome build's: fault, per-fault bits, capability bits,
bus link and the aux heat relay.

Faults and capabilities come from the packed Faults1 / Features1 mfg attributes, read
through HisenseDiagCoordinator. Each named fault bit and each capability flag is its own
entity, as on the ESPHome device, so an automation can act on "condensate tray full"
without parsing attributes. The ones the ESPHome YAML declares are enabled; the rest are
created disabled.

Bus link is the firmware's own BusLink attribute where the node has it, and otherwise
mirrors the firmware's #56 liveness (the base climate entity goes unavailable on bus
silence), which needs no firmware/matter-server support (docs/14 Phase 1b). Aux heat
mirrors the native contact sensor on the aux-heat endpoint.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CAPABILITIES_ENABLED_BY_DEFAULT,
    CONF_AUX_HEAT,
    CONF_BASE_CLIMATE,
    CONF_FAULT,
    DOMAIN,
    FAULT1_BITS,
    FAULTS1_ANY_BIT,
    FAULTS1_VALID_BIT,
    FAULTS_ENABLED_BY_DEFAULT,
    FEAT1_BITS,
    KEY_BUS_LINK,
)
from .coordinator import HisenseDiagCoordinator
from .entity import (
    UNAVAILABLE_STATES,
    MirrorEntity,
    device_info,
    remove_stale_entities,
)
from .features import decode_features1

FAULT_NAME = "Fault"
AUX_HEAT_SLUG = "aux_heat"


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the fault, capability, bus-link and aux-heat binary sensors."""
    store = hass.data[DOMAIN][entry.entry_id]
    config: dict[str, Any] = store["config"]
    entities: list[BinarySensorEntity] = []
    coord: HisenseDiagCoordinator | None = store.get("diag")
    if coord is not None:
        entities.append(FaultsBinarySensor(coord, entry))
        entities.extend(
            FaultBitBinarySensor(coord, entry, bit, key, name)
            for bit, key, name in FAULT1_BITS
        )
        entities.extend(
            CapabilityBinarySensor(coord, entry, key, name)
            for _bit, key, name, _ext in FEAT1_BITS
        )
    elif fault := config.get(CONF_FAULT):
        # No diagnostics connection: the firmware's aggregate fault endpoint still gives
        # the headline Fault entity. Same unique id as the diagnostics one, so adding
        # the matter-server URL later upgrades this entity instead of adding a second.
        entities.append(MirrorFaultBinarySensor(entry, fault))
    if entry.data.get(CONF_BASE_CLIMATE):
        entities.append(BusLinkBinarySensor(entry, coord))
    if aux := config.get(CONF_AUX_HEAT):
        entities.append(AuxHeatBinarySensor(entry, aux))
    else:
        remove_stale_entities(hass, entry, "binary_sensor", [AUX_HEAT_SLUG])
    async_add_entities(entities)


def _data(coord: HisenseDiagCoordinator) -> dict:
    """The last poll, or nothing if there has never been a successful one."""
    return coord.data or {}


class FaultsBinarySensor(CoordinatorEntity[HisenseDiagCoordinator], BinarySensorEntity):
    """PROBLEM sensor: on when any f_e_* fault is set. Per-fault detail in attributes.

    `any` matches the firmware aggregate (ep10) exactly: the frost-guard mode flag is
    already excluded, so this never cries wolf on a healthy unit in 8 C heat.
    """

    _attr_has_entity_name = True
    _attr_name = FAULT_NAME
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coord: HisenseDiagCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coord)
        self._attr_unique_id = f"{entry.entry_id}_faults"
        self._attr_device_info = device_info(entry)

    def _valid_value(self) -> int | None:
        v = _data(self.coordinator).get("faults1")
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


class MirrorFaultBinarySensor(MirrorEntity, BinarySensorEntity):
    """The aggregate fault, from the native contact sensor on the fault endpoint.

    The firmware reports it as a normally-closed loop (closed = healthy), which Home
    Assistant shows as a contact sensor that is on (open) while a fault is present.
    """

    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, entry: ConfigEntry, source: str) -> None:
        super().__init__(entry, source, "faults", FAULT_NAME)

    @property
    def is_on(self) -> bool | None:
        s = self._source_state()
        return s.state == "on" if s and self.available else None


class AuxHeatBinarySensor(MirrorEntity, BinarySensorEntity):
    """The aux / PTC electric-heat relay, from its native contact sensor.

    Same polarity trick as the fault endpoint: the firmware writes the BooleanState
    inverted, so the native contact sensor reads on while the relay is energised.
    """

    _attr_device_class = BinarySensorDeviceClass.HEAT

    def __init__(self, entry: ConfigEntry, source: str) -> None:
        super().__init__(entry, source, AUX_HEAT_SLUG, "Aux heat relay")

    @property
    def is_on(self) -> bool | None:
        s = self._source_state()
        return s.state == "on" if s and self.available else None


class FaultBitBinarySensor(
    CoordinatorEntity[HisenseDiagCoordinator], BinarySensorEntity
):
    """PROBLEM sensor for one named f_e_* fault bit (#86).

    Gates on the same Faults1 VALID bit as the aggregate: unknown whenever the
    firmware hasn't reported a valid Faults1 read, otherwise reflects just this bit.
    """

    _attr_has_entity_name = True
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coord: HisenseDiagCoordinator,
        entry: ConfigEntry,
        bit: int,
        key: str,
        name: str,
    ) -> None:
        super().__init__(coord)
        self._bit = bit
        self._attr_name = name
        self._attr_entity_registry_enabled_default = key in FAULTS_ENABLED_BY_DEFAULT
        self._attr_unique_id = f"{entry.entry_id}_fault_{key}"
        self._attr_device_info = device_info(entry)

    def _valid_value(self) -> int | None:
        v = _data(self.coordinator).get("faults1")
        if isinstance(v, int) and (v >> FAULTS1_VALID_BIT) & 1:
            return v
        return None

    @property
    def is_on(self) -> bool | None:
        v = self._valid_value()
        if v is None:
            return None
        return bool((v >> self._bit) & 1)


class CapabilityBinarySensor(
    CoordinatorEntity[HisenseDiagCoordinator], BinarySensorEntity
):
    """One capability flag the A/C reports in its ProductType reply.

    On = the unit has it. Unknown (not off) while no valid capability word has been
    read, and for an ext-tier flag whose reply was too short to carry it, which is the
    same "unknown is not unsupported" rule the climate entity gates on.
    """

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self, coord: HisenseDiagCoordinator, entry: ConfigEntry, key: str, name: str
    ) -> None:
        super().__init__(coord)
        self._key = key
        self._attr_name = name
        self._attr_translation_key = f"capability_{key}"  # icon in icons.json
        self._attr_entity_registry_enabled_default = (
            key in CAPABILITIES_ENABLED_BY_DEFAULT
        )
        self._attr_unique_id = f"{entry.entry_id}_capability_{key}"
        self._attr_device_info = device_info(entry)

    @property
    def is_on(self) -> bool | None:
        caps = decode_features1(_data(self.coordinator).get("features1"))
        value = caps.get(self._key) if caps else None
        return value if isinstance(value, bool) else None


class BusLinkBinarySensor(BinarySensorEntity):
    """CONNECTIVITY sensor: on while the RS-485 bus is alive.

    Newer firmware reports this itself (the BusLink attribute), and that is used
    whenever the last diagnostics poll carried it. Otherwise it is inferred: the
    firmware nulls the standard liveness attributes on bus silence (#56), so the base
    climate entity goes unavailable, and this mirrors that. The inference needs no
    firmware or matter-server support, so it is also what covers a node on older
    firmware, an entry with no diagnostics, and a matter-server that is not answering.
    """

    _attr_has_entity_name = True
    _attr_name = "AC bus link"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_should_poll = False

    def __init__(
        self, entry: ConfigEntry, coord: HisenseDiagCoordinator | None = None
    ) -> None:
        self._base = entry.data[CONF_BASE_CLIMATE]
        self._coord = coord
        self._attr_unique_id = f"{entry.entry_id}_bus_link"
        self._attr_device_info = device_info(entry)

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_track_state_change_event(self.hass, [self._base], self._changed)
        )
        if self._coord is not None:
            self.async_on_remove(self._coord.async_add_listener(self._polled))

    @callback
    def _changed(self, _event: Event) -> None:
        self.async_write_ha_state()

    @callback
    def _polled(self) -> None:
        self.async_write_ha_state()

    def _reported(self) -> bool | None:
        """What the firmware says, or None when it has not said anything usable."""
        coord = self._coord
        if coord is None or not coord.last_update_success:
            return None
        value = _data(coord).get(KEY_BUS_LINK)
        return value if isinstance(value, bool) else None

    @property
    def is_on(self) -> bool:
        if (reported := self._reported()) is not None:
            return reported
        state = self.hass.states.get(self._base)
        return bool(state and state.state not in UNAVAILABLE_STATES)
