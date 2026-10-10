"""Mirrored sensors, compressor frequency and the optional bus counters. Needs `homeassistant`."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))

from stubs import (
    FULL_CONFIG,
    REAL_FEATURES1,
    FakeRegistry,
    attach,
    make_store,
    row,
    setup_platform,
    state,
)

import aiohttp
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import EntityCategory

from hisense_unified_ac import sensor
from hisense_unified_ac.const import (
    BUS_COUNTER_ATTRS,
    MFG_CLUSTER,
    OPTIONAL_ATTRS,
    format_link_token,
)
from hisense_unified_ac.coordinator import (
    HisenseDiagCoordinator,
    attribute_path,
    optional_from_node,
)
from hisense_unified_ac.sensor import MirrorSensor

ENTRY = SimpleNamespace(data=FULL_CONFIG, entry_id="e1")
SENSORS = {
    "outdoor_temperature_sensor": "sensor.out",
    "coil_temperature_sensor": "sensor.coil",
    "power_sensor": "sensor.w",
    "voltage_sensor": "sensor.v",
    "current_sensor": "sensor.a",
}
DIAG = {"compressor_hz": 42, "features1": REAL_FEATURES1, "faults1": 1 << 31}


def names(entities: list) -> list[str]:
    return [e.name for e in entities]


# ------------------------------------------------------------------ mirrored sensors
def test_native_sensors_are_re_exposed_under_the_esphome_names() -> None:
    hass, entry, _ = make_store(FULL_CONFIG | SENSORS)
    assert names(setup_platform(sensor, hass, entry)) == [
        "Outdoor temperature",
        "Coil temperature",
        "Power",
        "Voltage",
        "Current",
    ]


def test_no_mirror_for_a_sensor_the_node_does_not_have() -> None:
    hass, entry, _ = make_store(FULL_CONFIG | {"power_sensor": "sensor.w"})
    assert names(setup_platform(sensor, hass, entry)) == ["Power"]
    hass, entry, _ = make_store(FULL_CONFIG)
    assert setup_platform(sensor, hass, entry) == []


def test_mirror_reports_the_source_value_in_the_source_unit() -> None:
    entity = MirrorSensor(ENTRY, "power_sensor", "sensor.w")
    attach(entity, {"sensor.w": state("512.3", unit_of_measurement="W")})
    assert entity.native_value == 512.3
    assert entity.native_unit_of_measurement == "W"
    assert entity.device_class is SensorDeviceClass.POWER
    assert entity.state_class is SensorStateClass.MEASUREMENT
    assert entity.entity_category is None
    # A source already converted by Home Assistant (a Fahrenheit install) keeps its unit,
    # so the value is not converted a second time.
    entity = MirrorSensor(ENTRY, "coil_temperature_sensor", "sensor.coil")
    attach(entity, {"sensor.coil": state("104", unit_of_measurement="°F")})
    assert (entity.native_value, entity.native_unit_of_measurement) == (104.0, "°F")


def test_mirror_is_unavailable_when_the_source_is_and_never_guesses() -> None:
    entity = MirrorSensor(ENTRY, "voltage_sensor", "sensor.v")
    for states in (
        {},
        {"sensor.v": state("unavailable")},
        {"sensor.v": state("unknown")},
    ):
        attach(entity, states)
        assert not entity.available
        assert entity.native_value is None
    attach(entity, {"sensor.v": state("n/a")})
    assert entity.native_value is None
    assert entity.native_unit_of_measurement == "V"  # the fallback, never unit-less


# ----------------------------------------------------------------------- diagnostics
def test_no_diagnostics_connection_means_no_diagnostic_sensors() -> None:
    hass, entry, _ = make_store(FULL_CONFIG)
    assert setup_platform(sensor, hass, entry) == []


def test_firmware_without_the_counter_attributes_gets_no_counter_entities() -> None:
    hass, entry, _ = make_store(FULL_CONFIG, DIAG)
    assert names(setup_platform(sensor, hass, entry)) == [
        "Compressor frequency",
        "Capabilities",
    ]


def test_each_reported_counter_gets_an_entity_like_the_esphome_one() -> None:
    hass, entry, _ = make_store(
        FULL_CONFIG, DIAG | {"reply_timeouts": 3, "link_losses": 0}
    )
    added = setup_platform(sensor, hass, entry)
    assert names(added) == [
        "Compressor frequency",
        "Capabilities",
        "Bus reply timeouts",
        "Bus link losses",
    ]
    timeouts = added[2]
    assert timeouts.native_value == 3
    assert timeouts.state_class is SensorStateClass.TOTAL_INCREASING
    assert timeouts.entity_category is EntityCategory.DIAGNOSTIC
    assert timeouts.native_unit_of_measurement is None
    assert timeouts.unique_id == "e1_reply_timeouts"
    assert added[3].native_value == 0  # zero is a reading, not "unknown"


def test_counters_appear_by_themselves_once_an_updated_node_reports_them() -> None:
    # The entry is set up against old firmware, then the node is updated over the air.
    # The next poll must add the entities; nobody should have to reload the entry.
    hass, entry, coord = make_store(FULL_CONFIG, DIAG)
    added = setup_platform(sensor, hass, entry)
    assert len(added) == 2
    coord.data = DIAG | {"checksum_errors": 1}
    for listener in list(coord.listeners):
        listener()
    assert names(added)[2:] == ["Bus checksum errors"]
    # A later poll with the same counters adds nothing twice.
    for listener in list(coord.listeners):
        listener()
    assert len(added) == 3


def test_a_counter_the_node_stopped_reporting_is_removed_but_only_on_a_good_read() -> (
    None
):
    stale = row(
        "sensor.ac_link_losses", "e1_link_losses", platform="hisense_unified_ac"
    )
    registry = FakeRegistry([stale])
    hass, entry, coord = make_store(FULL_CONFIG, DIAG)
    coord.last_update_success = False  # matter-server down: proves nothing
    setup_platform(sensor, hass, entry, registry)
    assert registry.removed == []
    coord.last_update_success = True
    setup_platform(sensor, hass, entry, registry)
    assert registry.removed == ["sensor.ac_link_losses"]


def test_the_capabilities_summary_is_off_by_default_for_new_installs() -> None:
    hass, entry, _ = make_store(FULL_CONFIG, DIAG)
    caps = setup_platform(sensor, hass, entry)[1]
    assert caps.entity_registry_enabled_default is False
    assert caps.native_value == 5 and caps.extra_state_attributes["power_display"] == 1


# ------------------------------------------------------------- reading the counters
def node_with(**counters: object) -> dict:
    return {
        "node_id": 1,
        "attributes": {
            f"1/{MFG_CLUSTER}/16": 40,
            **{attribute_path(OPTIONAL_ATTRS[k]): v for k, v in counters.items()},
        },
    }


def test_only_counters_present_in_the_node_data_are_reported() -> None:
    assert optional_from_node(node_with()) == {}
    assert optional_from_node(node_with(link_losses=2)) == {"link_losses": 2}
    assert set(
        optional_from_node(node_with(**{k: 0 for k in BUS_COUNTER_ATTRS}))
    ) == set(BUS_COUNTER_ATTRS)


def test_a_present_but_unfilled_counter_exists_with_no_value() -> None:
    # Null (not yet reported) and junk both mean "the attribute is there, value unknown".
    assert optional_from_node(node_with(reply_timeouts=None)) == {
        "reply_timeouts": None
    }
    assert optional_from_node(node_with(reply_timeouts="x")) == {"reply_timeouts": None}
    assert optional_from_node(node_with(reply_timeouts=True)) == {
        "reply_timeouts": None
    }


def test_link_token_and_bus_link_are_read_from_the_same_snapshot() -> None:
    found = optional_from_node(node_with(link_token=0x0102, bus_link=True))
    assert found == {"link_token": 0x0102, "bus_link": True}
    assert optional_from_node(node_with(bus_link=False)) == {"bus_link": False}
    # The flag is a boolean on the wire; a number there is not a link state.
    assert optional_from_node(node_with(bus_link=1)) == {"bus_link": None}
    assert optional_from_node(node_with(link_token=True)) == {"link_token": None}


def test_a_malformed_node_reply_reports_no_counters() -> None:
    for junk in (None, [], "node", {}, {"attributes": None}, {"attributes": []}):
        assert optional_from_node(junk) == {}


def test_counter_ids_do_not_collide_with_each_other_or_the_fixed_attributes() -> None:
    ids = list(OPTIONAL_ATTRS.values())
    assert len(ids) == len(set(ids))
    assert not set(ids) & {0, 1, 2, 3, 16, 17, 18, 19}


def test_optional_attribute_ids_are_the_firmware_contract() -> None:
    # Fixed by the firmware (cluster 0xFFF1FC00, endpoint 1). A change here without the
    # same change in the firmware reads the wrong attribute and raises nothing.
    assert OPTIONAL_ATTRS == {
        "checksum_errors": 0x0014,
        "reply_timeouts": 0x0015,
        "unanswered_commands": 0x0016,
        "link_losses": 0x0017,
        "link_token": 0x0018,
        "bus_link": 0x0019,
    }
    assert attribute_path(0x0018) == "1/4294048768/24"


def test_counters_use_the_state_class_that_survives_a_node_reboot() -> None:
    # The counts are since boot, so they drop to 0 when the node restarts.
    # total_increasing treats a drop as a new cycle; total would record it as a
    # negative step. The ESPHome component declares the same class.
    hass, entry, coord = make_store(FULL_CONFIG, DIAG | {"reply_timeouts": 250})
    counter = setup_platform(sensor, hass, entry)[2]
    assert counter.state_class is SensorStateClass.TOTAL_INCREASING
    assert counter.last_reset is None
    coord.data = DIAG | {"reply_timeouts": 0}  # the node rebooted
    assert counter.native_value == 0


# ------------------------------------------------------------------ AC device type
def test_the_device_type_reads_like_the_esphome_text_sensor() -> None:
    assert format_link_token(0x0102) == "01 02"
    assert format_link_token(0xA00F) == "A0 0F"
    assert format_link_token(0x00FF) == "00 FF"
    # 0 is "not learned yet"; anything that is not a 16-bit number is not a token.
    for unknown in (0, None, "0102", True, -1, 0x10000, 1.0):
        assert format_link_token(unknown) is None


def test_the_device_type_entity_exists_only_when_the_node_reports_it() -> None:
    hass, entry, coord = make_store(FULL_CONFIG, DIAG)
    added = setup_platform(sensor, hass, entry)
    assert "AC device type" not in names(added)
    # Old firmware at setup, updated node on a later poll.
    coord.data = DIAG | {"link_token": 0x0102}
    for listener in list(coord.listeners):
        listener()
    token = added[-1]
    assert token.name == "AC device type"
    assert token.native_value == "01 02"
    assert token.entity_category is EntityCategory.DIAGNOSTIC
    assert token.translation_key == "link_token"
    assert token.unique_id == "e1_link_token"
    assert token.state_class is None and token.native_unit_of_measurement is None


def test_the_device_type_is_unknown_until_the_node_has_learned_it() -> None:
    hass, entry, coord = make_store(FULL_CONFIG, DIAG | {"link_token": 0})
    token = setup_platform(sensor, hass, entry)[-1]
    assert token.name == "AC device type" and token.native_value is None
    coord.data = DIAG | {"link_token": None}
    assert token.native_value is None
    coord.data = None
    assert token.native_value is None


class FakeSocket:
    """A matter-server socket that answers each command from a canned table."""

    def __init__(self, replies: dict[str, object]) -> None:
        self.replies = replies
        self.sent: list[dict] = []

    async def send_json(self, message: dict) -> None:
        self.sent.append(message)

    async def receive(self, timeout: float | None = None) -> SimpleNamespace:
        message = self.sent[-1]
        reply = self.replies[message["command"]]
        if reply == "closed":
            return SimpleNamespace(type=aiohttp.WSMsgType.CLOSED)
        body = {"message_id": message["message_id"], **reply}
        return SimpleNamespace(
            type=aiohttp.WSMsgType.TEXT, json=lambda: json.loads(json.dumps(body))
        )


def read_counters(replies: dict[str, object]) -> tuple[dict, FakeSocket]:
    # Built without __init__: only the node id and the name are touched on this path.
    coord = object.__new__(HisenseDiagCoordinator)
    coord._node_id = 42
    coord.name = "AC diagnostics"
    socket = FakeSocket(replies)
    return asyncio.run(coord._read_optional(socket)), socket


def test_counters_are_read_from_one_node_snapshot() -> None:
    found, socket = read_counters({"get_node": {"result": node_with(link_losses=4)}})
    assert found == {"link_losses": 4}
    assert [m["command"] for m in socket.sent] == ["get_node"]
    assert socket.sent[0]["args"] == {"node_id": 42}


def test_a_failed_snapshot_costs_the_counters_but_never_the_update() -> None:
    # An error reply (unknown node, older server) and a socket that closes mid-read
    # both leave the three fixed diagnostics untouched.
    assert read_counters({"get_node": {"error_code": 5}})[0] == {}
    assert read_counters({"get_node": "closed"})[0] == {}


if __name__ == "__main__":
    from _runner import run_module

    raise SystemExit(run_module(dict(globals())))
