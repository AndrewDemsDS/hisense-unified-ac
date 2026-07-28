"""Find the sibling entities (fan / eco-quiet-turbo switches / sleep select) of an A/C.

Used by the config flow when an entry is created, and again on every setup to fill in
anything a stored entry is missing. That second use matters: an entry created before
the firmware relabelled its switches kept empty keys forever, which left the presets
advertised but dead. Derivation at load heals such an entry without re-adding it.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import CONF_ECO, CONF_FAN, CONF_QUIET, CONF_SLEEP, CONF_TURBO


def derive_siblings(hass: HomeAssistant, base_climate: str) -> dict[str, str]:
    """Find the fan/switches/select that share the base climate's device."""
    reg = er.async_get(hass)
    ent = reg.async_get(base_climate)
    out: dict[str, str] = {}
    if ent is None or ent.device_id is None:
        return out
    for e in reg.entities.values():
        if e.device_id != ent.device_id:
            continue
        domain = e.entity_id.split(".", 1)[0]
        original = e.original_name or ""
        if domain == "fan" and CONF_FAN not in out:
            out[CONF_FAN] = e.entity_id
        elif domain == "switch":
            low = original.lower()
            # Firmware labels these "Switch (Eco)" / "(Quiet)" / "(Turbo)"; the old
            # "(3)/(4)/(5)" form has no digit to match, so it never fired. Keep it as
            # a fallback for older builds.
            if "eco" in low or "(3)" in original:
                out[CONF_ECO] = e.entity_id
            elif "quiet" in low or "mute" in low or "(4)" in original:
                out[CONF_QUIET] = e.entity_id
            elif "turbo" in low or "(5)" in original:
                out[CONF_TURBO] = e.entity_id
        elif domain == "select" and "sleep" in original.lower():
            # First match wins, like the fan above: this integration now publishes a
            # "Sleep profile" select of its own, and a last-match-wins scan over an
            # unordered registry could point the wrapper at itself.
            out.setdefault(CONF_SLEEP, e.entity_id)
    return out
