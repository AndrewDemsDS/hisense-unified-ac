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

import _pkg  # noqa: E402

_pkg.install()
COMPONENT = _pkg.COMPONENT

from hisense_unified_ac.const import (  # noqa: E402
    PRESET_ECO,
    PRESET_NONE,
    PRESET_QUIET,
    PRESET_TURBO,
    SLEEP_OFF_OPTION,
    SLEEP_PRESET_PREFIX,
    SLEEP_PROFILE_OPTIONS,
)
from hisense_unified_ac.features import PRESET_COMBOS  # noqa: E402


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


def test_sleep_select_icons_cover_every_profile() -> None:
    icons = _json("icons")
    key = _translation_key("select.py")
    block = icons["entity"]["select"][key]["state"]
    assert set(block) == set(SLEEP_PROFILE_OPTIONS), (
        f"sleep option icons drifted: {set(block) ^ set(SLEEP_PROFILE_OPTIONS)}"
    )


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
