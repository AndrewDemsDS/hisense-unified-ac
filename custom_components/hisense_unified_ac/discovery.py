"""Find the native Matter entities of an A/C: fan, switches, select and sensors.

Used by the config flow when an entry is created, and again on every setup to fill in
anything a stored entry is missing. That second use matters: an entry created before
the firmware relabelled its switches kept empty keys forever, which left the presets
advertised but dead. Derivation at load heals such an entry without re-adding it, and
it is also how an existing entry picks up an endpoint a firmware update adds (the
beeper switch), with no change to what is stored.

The matching rules themselves are pure and live in siblings.py.
"""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN, SIBLING_KEYS
from .siblings import Candidate, match_siblings, node_id_from_unique_id


def derive_siblings(hass: HomeAssistant, base_climate: str) -> dict[str, str]:
    """Find the entities that share the base climate's device, by role."""
    reg = er.async_get(hass)
    ent = reg.async_get(base_climate)
    if ent is None or ent.device_id is None:
        return {}
    candidates = [
        Candidate(e.entity_id, e.original_name or e.name or "", e.unique_id or "")
        for e in reg.entities.values()
        # Never our own entities (a wrapper pointed at itself), and never a disabled
        # one: a proxy for an entity that has no state would be dead on arrival.
        if e.device_id == ent.device_id
        and e.platform != DOMAIN
        and e.disabled_by is None
    ]
    return match_siblings(candidates)


def derive_node_id(hass: HomeAssistant, base_climate: str) -> int | None:
    """The Matter node id of the base climate, read from its unique id."""
    ent = er.async_get(hass).async_get(base_climate)
    if ent is None or ent.platform != "matter":
        return None
    return node_id_from_unique_id(ent.unique_id or "")


def resolve_config(
    hass: HomeAssistant, data: dict[str, Any], options: dict[str, Any], base: str
) -> dict[str, Any]:
    """The effective config: derived siblings, then stored data, then options.

    Stored values win, so a manual override is never overwritten. The one exception is
    a stored entity id that no longer exists anywhere (not in the registry, no state)
    while discovery has a live replacement: Home Assistant drops and recreates a Matter
    entity when its endpoint is re-interviewed under a new description, and an entry
    pinned to the old id would otherwise keep a dead preset for good.
    """
    derived = derive_siblings(hass, base)
    cfg = {**derived, **data, **options}
    reg = er.async_get(hass)
    for key in SIBLING_KEYS:
        stored = cfg.get(key)
        live = derived.get(key)
        if (
            stored
            and live
            and stored != live
            and reg.async_get(stored) is None
            and hass.states.get(stored) is None
        ):
            cfg[key] = live
    return cfg
