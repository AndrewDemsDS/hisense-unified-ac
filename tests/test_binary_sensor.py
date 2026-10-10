"""Fault, capability, bus-link and aux-heat binary sensors. Needs `homeassistant`."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))

from stubs import (
    COOL_ONLY_FEATURES1,
    FULL_CONFIG,
    REAL_FEATURES1,
    FakeRegistry,
    attach,
    make_store,
    row,
    setup_platform,
    state,
)

from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.const import EntityCategory

from hisense_unified_ac import binary_sensor
from hisense_unified_ac.binary_sensor import (
    AuxHeatBinarySensor,
    BusLinkBinarySensor,
    CapabilityBinarySensor,
    MirrorFaultBinarySensor,
)
from hisense_unified_ac.const import FAULT1_BITS, FEAT1_BITS

ENTRY = SimpleNamespace(data=FULL_CONFIG, entry_id="e1")
VALID = 1 << 31
DIAG = {"compressor_hz": 0, "features1": REAL_FEATURES1, "faults1": VALID}


def by_name(entities: list) -> dict:
    return {e.name: e for e in entities}


def diag_entities(diag: dict = DIAG) -> dict:
    hass, entry, _ = make_store(FULL_CONFIG, diag)
    return by_name(setup_platform(binary_sensor, hass, entry))


def test_one_entity_per_fault_bit_and_per_capability_flag() -> None:
    entities = diag_entities()
    assert {name for _b, _k, name in FAULT1_BITS} <= set(entities)
    assert {name for _b, _k, name, _x in FEAT1_BITS} <= set(entities)
    assert (
        len(entities) == 1 + len(FAULT1_BITS) + len(FEAT1_BITS) + 1
    )  # Fault, bus link


def test_only_the_bits_the_esphome_yaml_declares_start_enabled() -> None:
    enabled = {
        name for name, e in diag_entities().items() if e.entity_registry_enabled_default
    }
    assert enabled == {
        "Fault",
        "AC bus link",
        "Fault indoor temp sensor",
        "Fault indoor to outdoor comms",
        "Fault condensate tray full",
        "Fault outdoor temp sensor",
        "Capability heat pump",
        "Capability eco",
        "Capability quiet",
    }


def test_categories_and_classes_match_the_esphome_entities() -> None:
    entities = diag_entities()
    # The headline fault is a primary entity; the per-bit detail is diagnostic.
    assert entities["Fault"].entity_category is None
    assert entities["Fault"].device_class is BinarySensorDeviceClass.PROBLEM
    fault_bit = entities["Fault condensate tray full"]
    assert fault_bit.entity_category is EntityCategory.DIAGNOSTIC
    assert fault_bit.device_class is BinarySensorDeviceClass.PROBLEM
    cap = entities["Capability eco"]
    assert cap.entity_category is EntityCategory.DIAGNOSTIC
    assert cap.device_class is None
    assert cap.translation_key == "capability_power_save"
    link = entities["AC bus link"]
    assert link.entity_category is EntityCategory.DIAGNOSTIC
    assert link.device_class is BinarySensorDeviceClass.CONNECTIVITY


def test_unique_ids_are_the_ones_releases_before_1_6_0_registered() -> None:
    # Renaming an entity is free; changing its unique id orphans the old one and its
    # history. These three existed before the ESPHome alignment.
    entities = diag_entities()
    assert entities["Fault"].unique_id == "e1_faults"
    assert entities["AC bus link"].unique_id == "e1_bus_link"
    assert entities["Fault condensate tray full"].unique_id == "e1_fault_water_full"


def test_fault_bits_follow_the_faults_word() -> None:
    word = VALID | (1 << 30) | (1 << 3)  # any + water_full
    entities = diag_entities(DIAG | {"faults1": word})
    assert entities["Fault"].is_on is True
    assert entities["Fault condensate tray full"].is_on is True
    assert entities["Fault indoor temp sensor"].is_on is False
    assert entities["Fault"].extra_state_attributes["active"] == [
        "Fault condensate tray full"
    ]
    # No valid read yet: unknown, never "no fault".
    entities = diag_entities(DIAG | {"faults1": 0})
    assert entities["Fault"].is_on is None
    assert entities["Fault condensate tray full"].is_on is None


def test_capability_flags_follow_the_capability_word() -> None:
    entities = diag_entities()
    assert entities["Capability heat pump"].is_on is True
    assert entities["Capability eco"].is_on is True
    assert entities["Capability AI mode"].is_on is False
    assert entities["Capability display control"].is_on is True  # ext tier, reported
    entities = diag_entities(DIAG | {"features1": COOL_ONLY_FEATURES1})
    assert entities["Capability heat pump"].is_on is False
    # Ext-tier flag with no ext reply, and no valid word at all: unknown, not off.
    assert entities["Capability display control"].is_on is None
    entities = diag_entities(DIAG | {"features1": None})
    assert entities["Capability heat pump"].is_on is None


def test_entities_survive_a_coordinator_that_never_read_anything() -> None:
    # A failed first poll leaves coordinator.data as None.
    coord = SimpleNamespace(data=None, last_update_success=False)
    cap = CapabilityBinarySensor(coord, ENTRY, "cool_heat", "Capability heat pump")
    assert cap.is_on is None
    hass, entry, coord = make_store(FULL_CONFIG, DIAG)
    coord.data = None
    for entity in setup_platform(binary_sensor, hass, entry):
        if hasattr(entity, "coordinator"):
            assert entity.is_on is None


def test_without_diagnostics_the_fault_comes_from_the_native_fault_endpoint() -> None:
    hass, entry, _ = make_store(FULL_CONFIG | {"fault_sensor": "binary_sensor.fl"})
    entities = by_name(setup_platform(binary_sensor, hass, entry))
    assert set(entities) == {"Fault", "AC bus link"}
    fault = entities["Fault"]
    assert isinstance(fault, MirrorFaultBinarySensor)
    # Same unique id as the diagnostics one: enabling diagnostics later upgrades this
    # entity instead of putting a second Fault on the device.
    assert fault.unique_id == "e1_faults"
    assert fault.device_class is BinarySensorDeviceClass.PROBLEM
    attach(fault, {"binary_sensor.fl": state("on")})
    assert fault.is_on is True
    attach(fault, {"binary_sensor.fl": state("off")})
    assert fault.is_on is False
    attach(fault, {"binary_sensor.fl": state("unavailable")})
    assert fault.is_on is None and not fault.available


def test_with_diagnostics_there_is_exactly_one_fault_entity() -> None:
    hass, entry, _ = make_store(
        FULL_CONFIG | {"fault_sensor": "binary_sensor.fl"}, DIAG
    )
    added = setup_platform(binary_sensor, hass, entry)
    assert [e.name for e in added].count("Fault") == 1


def test_aux_heat_mirrors_the_native_contact_sensor() -> None:
    hass, entry, _ = make_store(FULL_CONFIG | {"aux_heat_sensor": "binary_sensor.aux"})
    aux = by_name(setup_platform(binary_sensor, hass, entry))["Aux heat relay"]
    assert isinstance(aux, AuxHeatBinarySensor)
    assert aux.device_class is BinarySensorDeviceClass.HEAT
    assert aux.entity_category is None
    # The firmware writes the BooleanState inverted, so "on" already means relay on.
    attach(aux, {"binary_sensor.aux": state("on")})
    assert aux.is_on is True
    attach(aux, {"binary_sensor.aux": state("off")})
    assert aux.is_on is False
    attach(aux, {})
    assert not aux.available


def test_no_aux_heat_entity_without_the_endpoint_and_a_stale_one_is_removed() -> None:
    registry = FakeRegistry(
        [row("binary_sensor.ac_aux", "e1_aux_heat", platform="hisense_unified_ac")]
    )
    hass, entry, _ = make_store(FULL_CONFIG)
    added = setup_platform(binary_sensor, hass, entry, registry)
    assert [e.name for e in added] == ["AC bus link"]
    assert registry.removed == ["binary_sensor.ac_aux"]


def test_bus_link_follows_the_base_climates_availability() -> None:
    # Older firmware, or no diagnostics at all: inferred from the native climate.
    link = BusLinkBinarySensor(ENTRY)
    attach(link, {"climate.b": state("cool")})
    assert link.is_on is True
    attach(link, {"climate.b": state("unavailable")})
    assert link.is_on is False
    attach(link, {})
    assert link.is_on is False


def bus_link(diag: dict, climate: str = "cool") -> tuple[BusLinkBinarySensor, object]:
    hass, entry, coord = make_store(FULL_CONFIG, diag)
    link = by_name(setup_platform(binary_sensor, hass, entry))["AC bus link"]
    attach(link, {"climate.b": state(climate)})
    return link, coord


def test_bus_link_uses_the_firmwares_own_flag_when_the_node_reports_one() -> None:
    # The flag wins in both directions over what the climate entity suggests.
    link, _ = bus_link(DIAG | {"bus_link": False}, climate="cool")
    assert link.is_on is False
    link, _ = bus_link(DIAG | {"bus_link": True}, climate="unavailable")
    assert link.is_on is True
    assert link.unique_id == "e1_bus_link"  # the same entity either way


def test_bus_link_falls_back_to_the_inference_without_a_usable_flag() -> None:
    # Firmware without the attribute.
    link, _ = bus_link(DIAG, climate="unavailable")
    assert link.is_on is False
    link, _ = bus_link(DIAG, climate="cool")
    assert link.is_on is True
    # Attribute present but not filled in yet.
    link, _ = bus_link(DIAG | {"bus_link": None}, climate="cool")
    assert link.is_on is True
    # matter-server stopped answering: the last flag is stale, so it is not trusted.
    link, coord = bus_link(DIAG | {"bus_link": True}, climate="unavailable")
    coord.last_update_success = False
    assert link.is_on is False
    # A failed first poll leaves no data at all.
    coord.data = None
    coord.last_update_success = True
    assert link.is_on is False


if __name__ == "__main__":
    from _runner import run_module

    raise SystemExit(run_module(dict(globals())))
