"""Keep icons.json / strings.json / en.json in step with what the code can actually produce.

This is the cheap drift catcher. Stale metadata does not raise at runtime: HA silently
ignores an icon or label for a state that no longer exists, and silently shows a raw slug
for one that was never added. Both have happened in this integration, so assert it.

Deliberately does not import Home Assistant. The two translation_key values live on entity
classes in modules that do import it, so they are read out of the source text instead,
which is enough to catch a rename on one side only.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _pkg

_pkg.install()
COMPONENT = _pkg.COMPONENT

from hisense_unified_ac.const import (
    BUS_COUNTER_ATTRS,
    CAPABILITIES_ENABLED_BY_DEFAULT,
    CAPABILITY_ICONS,
    FAN_MODES,
    FAULT1_BITS,
    FAULTS_ENABLED_BY_DEFAULT,
    FEAT1_BITS,
    PRESET_ECO,
    PRESET_NONE,
    PRESET_QUIET,
    PRESET_TURBO,
    SLEEP_OFF_OPTION,
    SLEEP_PRESET_PREFIX,
    SLEEP_PROFILE_OPTIONS,
    SWITCHES,
)
from hisense_unified_ac.features import PRESET_COMBOS

# --- What the hisense-w41h1 ESPHome build shows, copied from its sources -----------------
# firmware/esphome/w41h1.yaml (entity names) and firmware/esphome/components/hisense_ac/
# {switch,sensor,select,binary_sensor}.py (icons, and the default names of the per-bit
# entities). This is the reference the integration is aligned to, written out here on
# purpose: the two live in different repos, so a rename on this side has to fail a test.
ESPHOME_SWITCHES = {
    "Eco": "mdi:leaf",
    "Turbo": "mdi:fan-plus",
    "Quiet": "mdi:volume-off",
    "Panel display": "mdi:television-ambient-light",
    "Beeper": "mdi:volume-high",
}
ESPHOME_COUNTERS = {
    "Bus checksum errors": "mdi:alert-circle-outline",
    "Bus reply timeouts": "mdi:timer-alert-outline",
    "Unanswered commands": "mdi:message-alert-outline",
    "Bus link losses": "mdi:lan-disconnect",
}
ESPHOME_FAULTS = [
    "Fault indoor temp sensor",
    "Fault indoor coil sensor",
    "Fault indoor humidity sensor",
    "Fault condensate tray full",
    "Fault indoor fan motor",
    "Fault grille",
    "Fault zero-cross detect",
    "Fault indoor to outdoor comms",
    "Fault indoor display",
    "Fault indoor keypad",
    "Fault indoor wifi module",
    "Fault indoor electrical",
    "Fault indoor EEPROM",
    "Fault outdoor EEPROM",
    "Fault outdoor coil sensor",
    "Fault outdoor gas sensor",
    "Fault outdoor temp sensor",
    "Fault over temperature",
]
ESPHOME_CAPABILITIES = {
    "Capability heat pump": "mdi:heat-pump",
    "Capability AI mode": "mdi:brain",
    "Capability infinite fan": "mdi:fan",
    "Capability eco": "mdi:leaf",
    "Capability quiet": "mdi:volume-off",
    "Capability 8-position louvre": "mdi:arrow-up-down",
    "Capability swing follow": "mdi:arrow-oscillating",
    "Capability humidity": "mdi:water-percent",
    "Capability 8C frost guard": "mdi:snowflake-thermometer",
    "Capability purify": "mdi:air-purifier",
    "Capability display control": "mdi:television-ambient-light",
    "Capability enable 8C heat": "mdi:snowflake-thermometer",
    "Capability trans 102-64": "mdi:swap-horizontal",
}
# The per-bit entities w41h1.yaml declares, so the ones that start enabled here.
ESPHOME_YAML_FAULTS = {
    "Fault indoor temp sensor",
    "Fault indoor to outdoor comms",
    "Fault condensate tray full",
    "Fault outdoor temp sensor",
}
ESPHOME_YAML_CAPABILITIES = {
    "Capability heat pump",
    "Capability eco",
    "Capability quiet",
}


COMPONENT_FILES = {
    "icons": COMPONENT / "icons.json",
    "strings": COMPONENT / "strings.json",
    "en": COMPONENT / "translations" / "en.json",
    "manifest": COMPONENT / "manifest.json",
}


def _json(name: str) -> dict:
    return json.loads(COMPONENT_FILES[name].read_text())


def _source(name: str) -> str:
    return (COMPONENT / name).read_text()


def _translation_key(module: str) -> str:
    match = re.search(r'_attr_translation_key\s*=\s*"([^"]+)"', _source(module))
    assert match, f"no _attr_translation_key in {module}"
    return match.group(1)


def _every_preset_value() -> set[str]:
    """Every preset value the climate entity can advertise or report."""
    singles = {PRESET_NONE, PRESET_ECO, PRESET_QUIET, PRESET_TURBO}
    profiles = [o for o in SLEEP_PROFILE_OPTIONS if o != SLEEP_OFF_OPTION]
    sleeps = {f"{SLEEP_PRESET_PREFIX}{o.lower()}" for o in profiles}
    # eco coexists with every sleep profile on the hardware, so each pair is its own preset.
    eco_sleeps = {f"{PRESET_ECO}_{SLEEP_PRESET_PREFIX}{o.lower()}" for o in profiles}
    return singles | set(PRESET_COMBOS) | sleeps | eco_sleeps


def test_preset_icons_cover_exactly_the_possible_presets() -> None:
    icons = _json("icons")
    key = _translation_key("climate.py")
    block = icons["entity"]["climate"][key]["state_attributes"]["preset_mode"]["state"]
    assert set(block) == _every_preset_value(), (
        f"preset icons drifted: missing {_every_preset_value() - set(block)}, "
        f"stale {set(block) - _every_preset_value()}"
    )


def test_fan_mode_icons_cover_exactly_the_fan_ladder() -> None:
    # medium_low and medium_high are not Home Assistant built-ins, so without an entry here
    # those two steps render with no icon while the other four get the core defaults.
    icons = _json("icons")
    key = _translation_key("climate.py")
    block = icons["entity"]["climate"][key]["state_attributes"]["fan_mode"]["state"]
    assert set(block) == set(FAN_MODES), (
        f"fan icons drifted: missing {set(FAN_MODES) - set(block)}, "
        f"stale {set(block) - set(FAN_MODES)}"
    )
    assert all(v.startswith("mdi:") for v in block.values())


def test_the_sleep_select_has_an_icon() -> None:
    # Only a default, no per-state map: this select's states are the raw ModeSelect option
    # strings ("Off", "General", ...) and hassfest requires translation keys to be slugs,
    # so per-option icons would need the options slugified first. See the slug test below.
    icons = _json("icons")
    block = icons["entity"]["select"][_translation_key("select.py")]
    assert block.get("default", "").startswith("mdi:")
    assert "state" not in block, (
        "per-state icons here need slug keys; hassfest rejects the raw option strings"
    )


def test_every_icons_translation_key_is_a_slug() -> None:
    # hassfest's rule, enforced locally so it does not have to fail in CI:
    # keys must match [a-z0-9-_]+ and not start or end with a hyphen or underscore.
    # Entity ids and mdi values are not keys, so only walk the key positions.
    slug = re.compile(r"[a-z0-9][a-z0-9_-]*[a-z0-9]|[a-z0-9]")

    def walk(node, path: str) -> None:
        if not isinstance(node, dict):
            return
        for key, value in node.items():
            # "default" and the domain/entity-name levels are structural, but they are all
            # slugs anyway, so validating every key costs nothing and catches more.
            assert slug.fullmatch(key), f"invalid translation key {key!r} at {path}"
            walk(value, f"{path}.{key}")

    walk(_json("icons")["entity"], "entity")


def test_every_icon_is_an_mdi_name() -> None:
    def walk(node) -> list[str]:
        if isinstance(node, str):
            return [node]
        if isinstance(node, dict):
            return [v for child in node.values() for v in walk(child)]
        return []

    for value in walk(_json("icons")):
        assert re.fullmatch(r"mdi:[a-z0-9-]+", value), f"not an mdi icon name: {value}"


def test_strings_and_translations_are_identical() -> None:
    # en.json is what HA actually serves; strings.json is what hassfest checks. A change
    # to one only means the UI and the validator disagree.
    assert _json("strings") == _json("en"), (
        "strings.json and translations/en.json diverged"
    )


def test_slug_presets_have_labels_and_real_words_do_not_need_them() -> None:
    labels = _json("strings")["entity"]["climate"][_translation_key("climate.py")][
        "state_attributes"
    ]["preset_mode"]["state"]
    # A value with an underscore renders as a raw slug without a label, so it needs one.
    needs_label = {p for p in _every_preset_value() if "_" in p}
    assert needs_label <= set(labels), (
        f"unlabelled slug presets: {needs_label - set(labels)}"
    )
    assert set(labels) <= _every_preset_value(), (
        f"labels for presets that cannot occur: {set(labels) - _every_preset_value()}"
    )


def test_raised_exception_keys_exist_with_matching_placeholders() -> None:
    source = _source("climate.py")
    raised = set(re.findall(r'translation_key="([^"]+)"', source))
    assert raised, "no ServiceValidationError translation_key found in climate.py"
    for name in ("strings", "en"):
        exceptions = _json(name).get("exceptions", {})
        missing = raised - set(exceptions)
        assert not missing, f"{name}.json is missing exception messages: {missing}"
    exceptions = _json("strings")["exceptions"]
    for key in raised:
        message = exceptions[key]["message"]
        used = set(re.findall(r"\{(\w+)\}", message))
        # The placeholders the code passes must be exactly the ones the message consumes.
        block = re.search(
            r"translation_key=\"%s\".*?translation_placeholders=\{(.*?)\n\s*\},"
            % re.escape(key),
            source,
            re.S,
        )
        assert block, f"could not find placeholders passed for {key}"
        passed = set(re.findall(r'"(\w+)":', block.group(1)))
        assert used == passed, f"{key}: message uses {used}, code passes {passed}"


def test_switches_carry_the_esphome_names_and_icons() -> None:
    assert {name: icon for _slug, name, icon in SWITCHES.values()} == ESPHOME_SWITCHES
    block = _json("icons")["entity"]["switch"]
    assert {slug: block[slug]["default"] for slug in block} == {
        slug: icon for slug, _name, icon in SWITCHES.values()
    }, "icons.json switch block drifted from SWITCHES"


def test_bus_counters_carry_the_esphome_names_and_icons() -> None:
    assert {
        name: icon for _attr, name, icon in BUS_COUNTER_ATTRS.values()
    } == ESPHOME_COUNTERS
    block = _json("icons")["entity"]["sensor"]
    for key, (_attr, _name, icon) in BUS_COUNTER_ATTRS.items():
        assert block[key]["default"] == icon, f"icons.json sensor.{key} drifted"
    assert block["compressor_frequency"]["default"] == "mdi:sine-wave"
    assert set(block) == set(BUS_COUNTER_ATTRS) | {
        "compressor_frequency",
        "capabilities",
        "link_token",
    }


def test_the_device_type_sensor_carries_the_esphome_name_and_icon() -> None:
    # w41h1.yaml names the link_token text sensor "AC device type"; text_sensor.py gives
    # it mdi:identifier and the diagnostic category (the category is checked in tier 2).
    assert '_attr_name = "AC device type"' in _source("sensor.py")
    assert _json("icons")["entity"]["sensor"]["link_token"] == {
        "default": "mdi:identifier"
    }


def test_fault_bits_carry_the_esphome_names_in_bit_order() -> None:
    assert [name for _bit, _key, name in FAULT1_BITS] == ESPHOME_FAULTS
    assert [bit for bit, _key, _name in FAULT1_BITS] == list(range(18))
    enabled = {
        name for _b, key, name in FAULT1_BITS if key in FAULTS_ENABLED_BY_DEFAULT
    }
    assert enabled == ESPHOME_YAML_FAULTS
    assert FAULTS_ENABLED_BY_DEFAULT <= {key for _b, key, _n in FAULT1_BITS}


def test_capability_flags_carry_the_esphome_names_and_icons() -> None:
    assert {
        name: CAPABILITY_ICONS[key] for _bit, key, name, _ext in FEAT1_BITS
    } == ESPHOME_CAPABILITIES
    block = _json("icons")["entity"]["binary_sensor"]
    # Exactly the capability flags: the fault and link sensors take their icon from
    # their device class, as the ESPHome ones do, so a leftover entry here is drift.
    assert {key: value["default"] for key, value in block.items()} == {
        f"capability_{key}": icon for key, icon in CAPABILITY_ICONS.items()
    }
    enabled = {
        name
        for _b, key, name, _x in FEAT1_BITS
        if key in CAPABILITIES_ENABLED_BY_DEFAULT
    }
    assert enabled == ESPHOME_YAML_CAPABILITIES


def test_the_sleep_select_uses_the_esphome_icon() -> None:
    icons = _json("icons")
    assert icons["entity"]["select"][_translation_key("select.py")] == {
        "default": "mdi:sleep"
    }


def test_every_flow_field_has_a_label() -> None:
    # A field with no entry under "data" renders as its raw key ("matter_url"). The
    # options flow shipped with no strings at all before 1.6.0, which is how that looks.
    source = _source("config_flow.py")
    block = re.search(r"OVERRIDABLE = \((.*?)\)", source, re.S)
    assert block, "OVERRIDABLE not found in config_flow.py"
    const = {
        name: value
        for name, value in vars(sys.modules["hisense_unified_ac.const"]).items()
        if name.startswith("CONF_")
    }
    overridable = {const[name] for name in re.findall(r"CONF_\w+", block.group(1))}
    assert len(overridable) == 7
    diagnostics = {const["CONF_MATTER_URL"], const["CONF_NODE_ID"]}
    wanted = {
        ("config", "user"): overridable
        | diagnostics
        | {const["CONF_BASE_CLIMATE"], const["CONF_NAME"]},
        ("options", "init"): overridable | diagnostics,
    }
    for name in ("strings", "en"):
        doc = _json(name)
        for (section, step), fields in wanted.items():
            form = doc[section]["step"][step]
            assert set(form["data"]) == fields, (
                f"{name}.json {section}.{step}: unlabelled {fields - set(form['data'])}, "
                f"stale {set(form['data']) - fields}"
            )
            assert set(form.get("data_description", {})) <= fields


def test_every_platform_file_is_loaded_and_every_loaded_platform_exists() -> None:
    # A platform module that __init__ never forwards to is dead code that looks alive:
    # the switches would never appear, with nothing in the log.
    listed = set(re.findall(r"Platform\.([A-Z_]+)", _source("__init__.py")))
    platforms = {"climate", "switch", "select", "sensor", "binary_sensor"}
    assert listed == {p.upper() for p in platforms}
    for platform in platforms:
        assert (COMPONENT / f"{platform}.py").exists(), f"{platform}.py missing"
        assert "async def async_setup_entry" in _source(f"{platform}.py")


def test_manifest_loads_after_the_matter_integration() -> None:
    # The native entities this wraps come from Matter; setting up after it means their
    # states exist on the first write instead of every proxy starting unavailable.
    assert "matter" in _json("manifest").get("after_dependencies", [])


def test_manifest_version_is_semver() -> None:
    version = _json("manifest")["version"]
    assert re.fullmatch(r"\d+\.\d+\.\d+", version), version


def test_every_module_imports_cleanly_without_dead_names() -> None:
    # Catches the dead-import class of bug (a constant removed from const.py but still
    # imported), which otherwise only shows up as "Error setting up entry" in the HA log.
    # Skipped where homeassistant is absent, since most modules import it.
    try:
        import homeassistant  # noqa: F401
    except ImportError:
        print("    (skipped: homeassistant not installed)")
        return
    import importlib

    for module in sorted(p.stem for p in COMPONENT.glob("*.py")):
        importlib.import_module(f"hisense_unified_ac.{module}")


if __name__ == "__main__":
    from _runner import run_module

    raise SystemExit(run_module(dict(globals())))
