"""Matching native Matter entities to roles. No Home Assistant needed: siblings.py is pure.

The rows below are what Home Assistant's Matter integration registers for the firmware's
endpoints. Names come in two generations: with the endpoint label ("Switch (Eco)", what a
current Home Assistant shows for these test-vendor devices) and with the bare endpoint
number ("Switch (3)", what one that ignores the label shows).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _pkg

_pkg.install()

from hisense_unified_ac.const import SIBLING_KEYS, SIBLING_RULES
from hisense_unified_ac.siblings import (
    Candidate,
    match_siblings,
    node_id_from_unique_id,
    position,
)

NODE = "00000000000004D2-000000000000002A-MatterNodeDevice"


def uid(endpoint: int, key: str, cluster: int, attribute: int) -> str:
    return f"{NODE}-{endpoint}-{key}-{cluster}-{attribute}"


# entity id, label-era name, number-era name, unique id
ENDPOINTS = [
    (
        "climate.ac",
        "Thermostat (Climate)",
        "Thermostat",
        uid(1, "MatterThermostat", 513, 0),
    ),
    ("fan.ac", "Fan (Climate)", "Fan", uid(1, "MatterFan", 514, 0)),
    ("switch.ac_power", "Switch (Climate)", "Switch (1)", uid(1, "MatterPlug", 6, 0)),
    ("switch.ac_3", "Switch (Eco)", "Switch (3)", uid(3, "MatterPlug", 6, 0)),
    ("switch.ac_4", "Switch (Quiet)", "Switch (4)", uid(4, "MatterPlug", 6, 0)),
    ("switch.ac_5", "Switch (Turbo)", "Switch (5)", uid(5, "MatterPlug", 6, 0)),
    ("switch.ac_9", "Switch (Display)", "Switch (9)", uid(9, "MatterPlug", 6, 0)),
    ("select.ac_6", "Mode (Sleep)", "Mode", uid(6, "MatterModeSelect", 80, 3)),
    (
        "sensor.ac_t2",
        "Temperature (Outdoor)",
        "Temperature (2)",
        uid(2, "TemperatureSensor", 1026, 0),
    ),
    (
        "sensor.ac_t8",
        "Temperature (Coil)",
        "Temperature (8)",
        uid(8, "TemperatureSensor", 1026, 0),
    ),
    ("sensor.ac_w", "Power", "Power", uid(1, "ElectricalPowerMeasurementWatt", 144, 8)),
    (
        "sensor.ac_v",
        "Voltage",
        "Voltage",
        uid(1, "ElectricalPowerMeasurementVoltage", 144, 4),
    ),
    (
        "sensor.ac_a",
        "Current",
        "Current",
        uid(1, "ElectricalPowerMeasurementActiveCurrent", 144, 5),
    ),
    (
        "binary_sensor.ac_7",
        "Door (Aux Heat)",
        "Door (7)",
        uid(7, "ContactSensor", 69, 0),
    ),
    (
        "binary_sensor.ac_10",
        "Door (Fault)",
        "Door (10)",
        uid(10, "ContactSensor", 69, 0),
    ),
]
BEEPER = ("switch.ac_11", "Switch (Beeper)", "Switch (11)", uid(11, "MatterPlug", 6, 0))

EXPECTED = {
    "fan": "fan.ac",
    "eco_switch": "switch.ac_3",
    "quiet_switch": "switch.ac_4",
    "turbo_switch": "switch.ac_5",
    "display_switch": "switch.ac_9",
    "outdoor_temperature_sensor": "sensor.ac_t2",
    "coil_temperature_sensor": "sensor.ac_t8",
    "power_sensor": "sensor.ac_w",
    "voltage_sensor": "sensor.ac_v",
    "current_sensor": "sensor.ac_a",
    "aux_heat_sensor": "binary_sensor.ac_7",
    "fault_sensor": "binary_sensor.ac_10",
}


def labelled(rows=ENDPOINTS) -> list[Candidate]:
    return [Candidate(eid, name, unique) for eid, name, _old, unique in rows]


def numbered(rows=ENDPOINTS) -> list[Candidate]:
    return [Candidate(eid, old, unique) for eid, _name, old, unique in rows]


def test_finds_every_role_by_its_endpoint_label() -> None:
    assert match_siblings(labelled()) == EXPECTED | {"sleep_select": "select.ac_6"}


def test_finds_every_positional_role_when_the_label_is_not_applied() -> None:
    # A Home Assistant that ignores "ha_entitylabel" names the switches by endpoint
    # number. Everything with a fixed endpoint is still found, from the unique id, and
    # the sleep select from being the node's only ModeSelect.
    assert match_siblings(numbered()) == EXPECTED | {"sleep_select": "select.ac_6"}


def test_registry_order_does_not_change_the_answer() -> None:
    assert match_siblings(list(reversed(labelled()))) == match_siblings(labelled())


def test_the_beeper_is_found_by_label_or_by_its_endpoint() -> None:
    found = match_siblings(labelled([*ENDPOINTS, BEEPER]))
    assert found["beeper_switch"] == "switch.ac_11"
    # "Buzzer" is the word the owner uses for it, so it is accepted too.
    buzzer = (BEEPER[0], "Switch (Buzzer)", BEEPER[2], BEEPER[3])
    assert match_siblings(labelled([*ENDPOINTS, buzzer]))["beeper_switch"] == BEEPER[0]
    # A Home Assistant that ignores the label calls it "Switch (11)". The beeper is
    # endpoint 11 on both firmwares, so the unique id still finds it.
    assert match_siblings(numbered([*ENDPOINTS, BEEPER]))["beeper_switch"] == BEEPER[0]


def test_an_unlabelled_switch_on_an_unknown_endpoint_fills_no_role() -> None:
    stray = ("switch.ac_12", "Switch (12)", "Switch (12)", uid(12, "MatterPlug", 6, 0))
    found = match_siblings(numbered([*ENDPOINTS, stray]))
    assert "switch.ac_12" not in found.values()
    assert "beeper_switch" not in found


def test_firmware_without_a_beeper_or_display_yields_no_such_role() -> None:
    rows = [r for r in ENDPOINTS if r[0] != "switch.ac_9"]
    for found in (match_siblings(labelled(rows)), match_siblings(numbered(rows))):
        assert "beeper_switch" not in found
        assert "display_switch" not in found
        assert found["eco_switch"] == "switch.ac_3"


def test_the_units_own_power_switch_is_never_taken_for_a_special_mode() -> None:
    for found in (match_siblings(labelled()), match_siblings(numbered())):
        assert "switch.ac_power" not in found.values()


def test_a_label_only_matches_a_whole_word_on_the_right_cluster() -> None:
    rows = [
        # "eco" inside another word is not the eco switch.
        Candidate("switch.x", "Switch (Second)", uid(12, "MatterPlug", 6, 0)),
        # The right word on the wrong cluster is not the outdoor temperature.
        Candidate("sensor.h", "Humidity (Outdoor)", uid(2, "HumiditySensor", 1029, 0)),
    ]
    assert match_siblings(rows) == {}


def test_two_roles_never_share_one_entity() -> None:
    # A label that names two roles at once must not put one switch behind both.
    rows = [Candidate("switch.x", "Switch (Eco Quiet)", uid(3, "MatterPlug", 6, 0))]
    found = match_siblings(rows)
    assert list(found.values()) == ["switch.x"]


def test_names_still_work_when_the_unique_id_cannot_be_read() -> None:
    # Not a Matter unique id at all (an override pointed at a template, or a future
    # format change): fall back to the name alone, as releases before 1.6.0 did.
    rows = [
        Candidate("switch.a", "Switch (Eco)", "x"),
        Candidate("switch.b", "Switch (4)", "x"),
        Candidate("switch.c", "Switch (Display)", "x"),
        Candidate("sensor.p", "Power", "x"),
        Candidate("sensor.q", "Apparent power", "x"),
    ]
    assert match_siblings(rows) == {
        "eco_switch": "switch.a",
        "quiet_switch": "switch.b",
        "display_switch": "switch.c",
        "power_sensor": "sensor.p",
    }


def test_reads_position_and_node_id_out_of_a_matter_unique_id() -> None:
    assert position(uid(9, "MatterPlug", 6, 0)) == (9, 6, 0)
    assert position("not-a-matter-id") is None
    assert position("") is None
    assert node_id_from_unique_id(uid(1, "MatterThermostat", 513, 0)) == 42
    assert node_id_from_unique_id("e1_unified") is None
    assert node_id_from_unique_id("") is None


def test_every_rule_names_a_known_sibling_key() -> None:
    assert set(SIBLING_RULES) <= set(SIBLING_KEYS)
    assert len(set(SIBLING_KEYS)) == len(SIBLING_KEYS)
    # A rule with no label words and no endpoint must be unique by cluster + attribute,
    # or two roles would race for the same entity.
    open_rules = [
        where
        for _d, words, where, ep in SIBLING_RULES.values()
        if not words and ep is None
    ]
    assert len(open_rules) == len(set(open_rules))


if __name__ == "__main__":
    from _runner import run_module

    raise SystemExit(run_module(dict(globals())))
