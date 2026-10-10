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
        # The full service data of each call, for tests that check a field `calls` drops.
        self.data: list[dict[str, Any]] = []

    async def async_call(
        self, domain: str, service: str, data: dict, blocking: bool = False
    ) -> None:
        self.calls.append((domain, service, data.get("entity_id"), data.get("option")))
        self.data.append(dict(data))


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


class FakeRegistry:
    """Just enough entity registry for discovery and the stale-entity cleanup.

    `rows` are SimpleNamespace(entity_id, device_id, platform, unique_id, original_name,
    name, disabled_by). Removals are recorded, not applied, so a test can assert on them.
    """

    def __init__(self, rows: list[SimpleNamespace] | None = None) -> None:
        self.entities = {row.entity_id: row for row in rows or []}
        self.removed: list[str] = []

    def async_get(self, entity_id: str) -> SimpleNamespace | None:
        return self.entities.get(entity_id)

    def async_get_entity_id(self, domain: str, platform: str, unique_id: str):
        for row in self.entities.values():
            if (
                row.entity_id.split(".", 1)[0] == domain
                and row.platform == platform
                and row.unique_id == unique_id
            ):
                return row.entity_id
        return None

    def async_remove(self, entity_id: str) -> None:
        self.removed.append(entity_id)


def row(
    entity_id: str,
    unique_id: str = "",
    original_name: str | None = None,
    *,
    device_id: str | None = "dev1",
    platform: str = "matter",
    disabled_by: str | None = None,
) -> SimpleNamespace:
    """One entity registry row."""
    return SimpleNamespace(
        entity_id=entity_id,
        device_id=device_id,
        platform=platform,
        unique_id=unique_id,
        original_name=original_name,
        name=None,
        disabled_by=disabled_by,
    )


class use_registry:
    """Context manager: make er.async_get(hass) return `registry` for the duration."""

    def __init__(self, registry: FakeRegistry) -> None:
        self.registry = registry

    def __enter__(self) -> FakeRegistry:
        from homeassistant.helpers import entity_registry as er

        self._er, self._real = er, er.async_get
        er.async_get = lambda _hass: self.registry
        return self.registry

    def __exit__(self, *_exc: object) -> None:
        self._er.async_get = self._real


def make_store(
    config: dict[str, Any] | None = None, diag: dict[str, Any] | None = None
) -> tuple[SimpleNamespace, SimpleNamespace, SimpleNamespace | None]:
    """(hass, entry, coordinator) for a platform's async_setup_entry.

    `diag` is the coordinator's last poll; None means no diagnostics were configured.
    The coordinator stub records its listeners so a test can fire the next poll.
    """
    from hisense_unified_ac.const import DOMAIN

    cfg = dict(FULL_CONFIG if config is None else config)
    coord = None
    if diag is not None:
        listeners: list = []

        def add_listener(callback, _context=None):
            listeners.append(callback)
            return lambda: listeners.remove(callback)

        coord = SimpleNamespace(
            data=dict(diag),
            last_update_success=True,
            listeners=listeners,
            async_add_listener=add_listener,
        )
    unloads: list = []
    entry = SimpleNamespace(
        data=cfg, options={}, entry_id="e1", async_on_unload=unloads.append
    )
    store = {"config": cfg}
    if coord is not None:
        store["diag"] = coord
    hass = SimpleNamespace(data={DOMAIN: {"e1": store}})
    return hass, entry, coord


def setup_platform(module, hass, entry, registry: FakeRegistry | None = None) -> list:
    """Run a platform's async_setup_entry; returns the list entities are added to."""
    added: list = []
    with use_registry(registry or FakeRegistry()):
        asyncio.run(module.async_setup_entry(hass, entry, added.extend))
    return added


def attach(entity, states: dict[str, Any]) -> Recorder:
    """Give a bare entity a stub hass; returns the service-call recorder."""
    entity.hass, recorder = make_hass(states)
    return recorder


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
