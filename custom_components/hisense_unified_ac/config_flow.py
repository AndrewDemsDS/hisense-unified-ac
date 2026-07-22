"""Config flow for the Hisense W41H1 Unified AC integration.

Pick the de-clouded A/C's native Matter *climate* entity; the flow auto-derives
the sibling fan / eco-quiet-turbo switches / sleep select from the same device
(matched by their firmware original names "Switch (3/4/5)" and "Sleep"). Each can
be overridden manually if auto-detection misses.
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
from homeassistant.core import callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    TextSelector,
)

from .const import (
    CONF_BASE_CLIMATE,
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


def _derive_siblings(hass, base_climate: str) -> dict[str, str]:
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
            if "(3)" in original:
                out[CONF_ECO] = e.entity_id
            elif "(4)" in original:
                out[CONF_QUIET] = e.entity_id
            elif "(5)" in original:
                out[CONF_TURBO] = e.entity_id
        elif domain == "select" and "sleep" in original.lower():
            out[CONF_SLEEP] = e.entity_id
    return out


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
            data.update(_derive_siblings(self.hass, base))
            # explicit selections override auto-derivation
            for key in (CONF_FAN, CONF_ECO, CONF_QUIET, CONF_TURBO, CONF_SLEEP):
                if user_input.get(key):
                    data[key] = user_input[key]

            # Optional: a matter-server WS URL + Matter node id enable the diagnostics
            # entities (compressor Hz, faults, capabilities) read from the mfg cluster.
            if user_input.get(CONF_MATTER_URL):
                data[CONF_MATTER_URL] = user_input[CONF_MATTER_URL]
            if user_input.get(CONF_NODE_ID) is not None:
                data[CONF_NODE_ID] = int(user_input[CONF_NODE_ID])

            return self.async_create_entry(title=data[CONF_NAME], data=data)

        schema = vol.Schema(
            {
                vol.Required(CONF_BASE_CLIMATE): EntitySelector(
                    EntitySelectorConfig(domain="climate")
                ),
                vol.Optional(CONF_NAME): TextSelector(),
                vol.Optional(CONF_FAN): EntitySelector(
                    EntitySelectorConfig(domain="fan")
                ),
                vol.Optional(CONF_ECO): EntitySelector(
                    EntitySelectorConfig(domain="switch")
                ),
                vol.Optional(CONF_QUIET): EntitySelector(
                    EntitySelectorConfig(domain="switch")
                ),
                vol.Optional(CONF_TURBO): EntitySelector(
                    EntitySelectorConfig(domain="switch")
                ),
                vol.Optional(CONF_SLEEP): EntitySelector(
                    EntitySelectorConfig(domain="select")
                ),
                vol.Optional(
                    CONF_MATTER_URL, default=DEFAULT_MATTER_URL
                ): TextSelector(),
                vol.Optional(CONF_NODE_ID): NumberSelector(
                    NumberSelectorConfig(mode="box", min=1, step=1)
                ),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)


class HisenseUnifiedACOptionsFlow(OptionsFlow):
    """Options: set the matter-server WS URL + Matter node id to enable the diagnostics.

    This is how an existing entry gets `node_id` (and `matter_url`) after initial setup,
    without deleting it -- both are needed for the compressor Hz / faults / capabilities
    entities to appear. Changing them reloads the entry (see __init__ update listener).
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
            return self.async_create_entry(data=opts)

        cur = {**self.config_entry.data, **self.config_entry.options}
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_MATTER_URL,
                    default=cur.get(CONF_MATTER_URL) or DEFAULT_MATTER_URL,
                ): TextSelector(),
                vol.Optional(
                    CONF_NODE_ID,
                    description={"suggested_value": cur.get(CONF_NODE_ID)},
                ): NumberSelector(NumberSelectorConfig(mode="box", min=1, step=1)),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
