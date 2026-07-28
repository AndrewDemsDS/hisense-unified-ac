"""Minimal fakes for the bits of Home Assistant these entities actually touch.

The entities here are read-through wrappers: they call hass.states.get() and
hass.services.async_call() and nothing else. So a dict-backed state machine and a call
recorder are enough to test every property and command path, without pulling in
pytest-homeassistant-custom-component or standing up a real hass. `homeassistant` itself
still has to be importable, since the entity classes subclass its base classes.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _pkg

_pkg.install()

# A capability word read live from node 14: valid + ext_valid, cool_heat + power_save +
# fan_mute + heat_8c + q_display set, power_display 1. Use this as "a real unit".
REAL_FEATURES1 = 3221292313
# Valid, every single-bit flag absent, ext tier unknown: a cooling-only, no-specials unit.
COOL_ONLY_FEATURES1 = 1 << 31

FULL_CONFIG = {
    "base_climate": "climate.b",
    "name": "AC",
    "fan": "fan.f",
    "eco_switch": "switch.e",
    "quiet_switch": "switch.q",
    "turbo_switch": "switch.t",
    "sleep_select": "select.s",
}

ALL_HVAC = ["off", "cool", "heat", "heat_cool", "dry", "fan_only"]
SLEEP_OPTIONS = ["Off", "General", "Old", "Young", "Kids"]


def state(value: str, **attributes: Any) -> SimpleNamespace:
    """One entity state, shaped like hass State for our purposes."""
    return SimpleNamespace(state=value, attributes=attributes)


def base_states(**overrides: Any) -> dict[str, Any]:
    """A healthy set of backing entities: climate + fan + sleep select, nothing engaged."""
    states = {
        "climate.b": state("cool", hvac_modes=list(ALL_HVAC), temperature=22),
        "fan.f": state("on", preset_mode="auto", oscillating=False),
        "select.s": state("Off", options=list(SLEEP_OPTIONS)),
    }
    states.update(overrides)
    return states


class Recorder:
    """Records service calls as (domain, service, entity_id, option) tuples."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, Any, Any]] = []

    async def async_call(
        self, domain: str, service: str, data: dict, blocking: bool = False
    ) -> None:
        self.calls.append((domain, service, data.get("entity_id"), data.get("option")))


class _States:
    def __init__(self, mapping: dict[str, Any]) -> None:
        self._mapping = mapping

    def get(self, entity_id: str | None) -> Any:
        return self._mapping.get(entity_id) if entity_id else None


def make_hass(states: dict[str, Any]) -> tuple[SimpleNamespace, Recorder]:
    recorder = Recorder()
    return SimpleNamespace(states=_States(states), services=recorder), recorder


def make_climate(
    states: dict[str, Any] | None = None,
    config: dict[str, Any] | None = None,
    features1: int | None = REAL_FEATURES1,
):
    """A UnifiedClimate wired to stub state. features1=None means no diagnostics."""
    from hisense_unified_ac.climate import UnifiedClimate

    cfg = FULL_CONFIG if config is None else config
    coord = (
        SimpleNamespace(data={"features1": features1})
        if features1 is not None
        else None
    )
    entity = UnifiedClimate(SimpleNamespace(data=cfg, entry_id="e1"), cfg, coord)
    entity.hass, recorder = make_hass(states if states is not None else base_states())
    return entity, recorder


def make_select(states: dict[str, Any] | None = None, sleep_entity: str = "select.s"):
    from hisense_unified_ac.select import SleepProfileSelect

    entity = SleepProfileSelect(
        SimpleNamespace(data=FULL_CONFIG, entry_id="e1"), sleep_entity
    )
    entity.hass, recorder = make_hass(states if states is not None else base_states())
    return entity, recorder


def run(coro) -> Any:
    """Run one coroutine to completion."""
    return asyncio.run(coro)


def run_no_wait(coro) -> tuple[Any, list[float]]:
    """Run a coroutine with asyncio.sleep stubbed out, returning the waits it asked for.

    Command paths deliberately space frames by COMBO_SETTLE_SECONDS, so a test that
    actually slept would take half a minute. The waits are asserted on instead.
    """
    waits: list[float] = []
    real_sleep = asyncio.sleep

    async def fake_sleep(delay: float) -> None:
        waits.append(delay)

    asyncio.sleep = fake_sleep
    try:
        result = asyncio.run(coro)
    finally:
        asyncio.sleep = real_sleep
    return result, waits
