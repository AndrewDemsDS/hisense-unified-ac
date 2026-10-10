"""Config flow for the Hisense W41H1 Unified AC integration.

Pick the de-clouded A/C's native Matter *climate* entity; the flow auto-derives
the sibling fan / switches / sleep select / sensors from the same device (see
`discovery.py`). The ones a preset or a switch depends on can be overridden manually if
auto-detection misses.

Diagnostics need the matter-server WebSocket URL and the Matter node id. Neither has to
be typed in the usual case: the URL defaults to the one Home Assistant's own Matter
integration is using, and the node id is read from the climate entity's unique id.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    TextSelector,
)

from .const import (
    CONF_BASE_CLIMATE,
    CONF_BEEPER,
    CONF_DISPLAY,
    CONF_ECO,
    CONF_FAN,
    CONF_MATTER_URL,
    CONF_NAME,
    CONF_NODE_ID,
    CONF_QUIET,
    CONF_SLEEP,
    CONF_TURBO,
    DEFAULT_MATTER_URL,
    DOMAIN,
)
from .discovery import derive_node_id, derive_siblings

# Siblings the user may point at by hand. The mirrored sensors are not here: they are
# found by cluster and attribute id, which leaves nothing to get wrong.
OVERRIDABLE = (
    CONF_FAN,
    CONF_ECO,
    CONF_QUIET,
    CONF_TURBO,
    CONF_SLEEP,
    CONF_DISPLAY,
    CONF_BEEPER,
)
_OVERRIDE_DOMAIN = {CONF_FAN: "fan", CONF_SLEEP: "select"}


def default_matter_url(hass: HomeAssistant) -> str:
    """The URL Home Assistant's own Matter integration uses, else the stock default.

    That URL is by construction reachable from Home Assistant, which the stock default
    is not on every install (an add-on that only listens inside the supervisor network).
    """
    for matter in hass.config_entries.async_entries("matter"):
        if url := matter.data.get("url"):
            return url
    return DEFAULT_MATTER_URL


def _override_fields(suggested: dict[str, Any]) -> dict[Any, Any]:
    return {
        vol.Optional(
            key, description={"suggested_value": suggested.get(key)}
        ): EntitySelector(
            EntitySelectorConfig(domain=_OVERRIDE_DOMAIN.get(key, "switch"))
        )
        for key in OVERRIDABLE
    }


class HisenseUnifiedACConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for a unified A/C."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> HisenseUnifiedACOptionsFlow:
        """Enable editing the matter-server URL + node id after setup (for diagnostics)."""
        return HisenseUnifiedACOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            base = user_input[CONF_BASE_CLIMATE]
            await self.async_set_unique_id(base)
            self._abort_if_unique_id_configured()

            data: dict[str, Any] = {
                CONF_BASE_CLIMATE: base,
                CONF_NAME: user_input.get(CONF_NAME) or "Unified AC",
            }
            data.update(derive_siblings(self.hass, base))
            # explicit selections override auto-derivation
            for key in OVERRIDABLE:
                if user_input.get(key):
                    data[key] = user_input[key]

            # A matter-server WS URL + Matter node id enable the diagnostics entities
            # (compressor Hz, faults, capabilities, bus counters) read from the mfg
            # cluster. The node id is read off the climate entity when left blank, so
            # diagnostics are on unless the URL is cleared.
            if user_input.get(CONF_MATTER_URL):
                data[CONF_MATTER_URL] = user_input[CONF_MATTER_URL]
                node_id = user_input.get(CONF_NODE_ID)
                if node_id is None:
                    node_id = derive_node_id(self.hass, base)
                if node_id is not None:
                    data[CONF_NODE_ID] = int(node_id)

            return self.async_create_entry(title=data[CONF_NAME], data=data)

        schema = vol.Schema(
            {
                # Only the native Matter climate: the list would otherwise also offer
                # this integration's own climate entities, and wrapping one of those
                # finds no siblings at all.
                vol.Required(CONF_BASE_CLIMATE): EntitySelector(
                    EntitySelectorConfig(domain="climate", integration="matter")
                ),
                vol.Optional(CONF_NAME): TextSelector(),
                **_override_fields({}),
                vol.Optional(
                    CONF_MATTER_URL,
                    description={"suggested_value": default_matter_url(self.hass)},
                ): TextSelector(),
                vol.Optional(CONF_NODE_ID): NumberSelector(
                    NumberSelectorConfig(mode="box", min=1, step=1)
                ),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)


class HisenseUnifiedACOptionsFlow(OptionsFlow):
    """Options: the matter-server WS URL + Matter node id, and entity overrides.

    This is how an existing entry gets `node_id` (and `matter_url`) after initial setup,
    without deleting it -- both are needed for the compressor Hz / faults / capabilities
    entities to appear. An entry that has no node id yet is offered the one read from its
    climate entity. The overrides are for a switch auto-detection missed; an empty one
    falls back to auto-detection. Changing anything reloads the entry (see the __init__
    update listener).
    """

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            opts: dict[str, Any] = {}
            if user_input.get(CONF_MATTER_URL):
                opts[CONF_MATTER_URL] = user_input[CONF_MATTER_URL]
            if user_input.get(CONF_NODE_ID) is not None:
                opts[CONF_NODE_ID] = int(user_input[CONF_NODE_ID])
            for key in OVERRIDABLE:
                if user_input.get(key):
                    opts[key] = user_input[key]
            return self.async_create_entry(data=opts)

        entry = self.config_entry
        cur = {**entry.data, **entry.options}
        node_id = cur.get(CONF_NODE_ID)
        if node_id is None:
            node_id = derive_node_id(self.hass, entry.data[CONF_BASE_CLIMATE])
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_MATTER_URL,
                    description={
                        "suggested_value": cur.get(CONF_MATTER_URL)
                        or default_matter_url(self.hass)
                    },
                ): TextSelector(),
                vol.Optional(
                    CONF_NODE_ID,
                    description={"suggested_value": node_id},
                ): NumberSelector(NumberSelectorConfig(mode="box", min=1, step=1)),
                # Only what was set here before is suggested, never the auto-detected
                # entity: submitting the form must not pin a detection result.
                **_override_fields(dict(entry.options)),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
