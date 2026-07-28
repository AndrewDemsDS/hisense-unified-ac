"""Unified climate entity for a de-clouded Hisense W41H1.

Read-through wrapper: presents one climate entity whose state mirrors the native
Matter climate + fan, and whose commands fan out to them + the special-mode
switches. Setpoint is only meaningful in cool/heat, so it is gated there (a temp
change in dry/fan-only/auto/off is a no-op and reports no target).

What it advertises corresponds to what this unit can actually do, from two sources:
the native Matter climate's own mode list (the device's ground truth, already gated
per capability by the firmware) and the reported capability matrix (`features.py`).
A preset needs both its backing entity and its capability bit; an ungated feature is
never advertised, so HA rejects an impossible command instead of silently dropping it.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event

from .const import (
    COMBO_SETTLE_SECONDS,
    CONF_BASE_CLIMATE,
    CONF_ECO,
    CONF_FAN,
    CONF_NAME,
    CONF_QUIET,
    CONF_SLEEP,
    CONF_TURBO,
    DOMAIN,
    FAN_FORCING_PRESETS,
    FAN_PERCENT,
    PRESET_ECO,
    PRESET_NONE,
    PRESET_QUIET,
    PRESET_SLEEP,
    PRESET_TURBO,
    SLEEP_OFF_OPTION,
    SLEEP_PRESET_PREFIX,
    SLEEP_PROFILE_OPTIONS,
)
from .coordinator import HisenseDiagCoordinator
from .features import (
    HEAT_CAPABILITY,
    PRESET_CAPABILITY,
    PRESET_COMBOS,
    Capabilities,
    decode_features1,
    supports,
)

_LOGGER = logging.getLogger(__name__)

UNAVAILABLE_STATES = {"unavailable", "unknown", None}
# Modes where a target temperature is meaningful (setpoint gated to these).
SETPOINT_MODES = {HVACMode.COOL, HVACMode.HEAT}
# Every mode this wrapper can drive, in the order they should appear in the UI. The
# advertised list is this, filtered to what the unit supports.
ALL_HVAC_MODES = [
    HVACMode.OFF,
    HVACMode.COOL,
    HVACMode.HEAT,
    HVACMode.HEAT_COOL,
    HVACMode.DRY,
    HVACMode.FAN_ONLY,
]
# Modes that need a heat pump (capability cool_heat); a cooling-only unit gets neither.
HEAT_PUMP_MODES = {HVACMode.HEAT, HVACMode.HEAT_COOL}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the unified climate entity from a config entry."""
    store = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([UnifiedClimate(entry, store["config"], store.get("diag"))])


class UnifiedClimate(ClimateEntity):
    """A single climate entity wrapping the W41H1's native Matter entities."""

    _attr_should_poll = False
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_translation_key = "unified"  # preset icons in icons.json
    _attr_fan_modes = ["auto", "low", "medium", "high"]
    _attr_swing_modes = ["off", "vertical"]
    _attr_min_temp = 16
    _attr_max_temp = 32
    _attr_target_temperature_step = 1

    def __init__(
        self,
        entry: ConfigEntry,
        config: dict[str, Any],
        coord: HisenseDiagCoordinator | None = None,
    ) -> None:
        # `config` is the entry's data plus anything derived for it at setup, so a stale
        # entry that never stored its switches still gets working presets.
        d = config
        self._coord = coord
        self._base: str = d[CONF_BASE_CLIMATE]
        self._fan: str | None = d.get(CONF_FAN)
        self._eco: str | None = d.get(CONF_ECO)
        self._quiet: str | None = d.get(CONF_QUIET)
        self._turbo: str | None = d.get(CONF_TURBO)
        self._sleep: str | None = d.get(CONF_SLEEP)
        self._attr_name = d.get(CONF_NAME) or "Unified AC"
        self._attr_unique_id = f"{entry.entry_id}_unified"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=self._attr_name,
            manufacturer="Hisense (de-clouded W41H1)",
        )

    # ------------------------------------------------------------------ helpers
    @property
    def _tracked(self) -> list[str]:
        return [
            e
            for e in (
                self._base,
                self._fan,
                self._eco,
                self._quiet,
                self._turbo,
                self._sleep,
            )
            if e
        ]

    def _state(self, entity_id: str | None):
        return self.hass.states.get(entity_id) if entity_id else None

    def _is_on(self, entity_id: str | None) -> bool:
        s = self._state(entity_id)
        return bool(s and s.state == "on")

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_track_state_change_event(
                self.hass, self._tracked, self._handle_change
            )
        )
        if self._coord is not None:
            # Capabilities only land on the first diagnostics poll, after this entity
            # is already up -> re-advertise when they do.
            self.async_on_remove(self._coord.async_add_listener(self._handle_caps))

    @callback
    def _handle_change(self, _event: Event) -> None:
        self.async_write_ha_state()

    @callback
    def _handle_caps(self) -> None:
        self.async_write_ha_state()

    @property
    def _capabilities(self) -> Capabilities | None:
        """This unit's reported capability matrix; None = unknown -> gate nothing."""
        if self._coord is None or not self._coord.data:
            return None
        return decode_features1(self._coord.data.get("features1"))

    # --------------------------------------------------------------- properties
    @property
    def available(self) -> bool:
        s = self._state(self._base)
        return bool(s and s.state not in UNAVAILABLE_STATES)

    @property
    def hvac_modes(self) -> list[HVACMode]:
        """Mirror the native climate's modes; fall back to the capability matrix.

        The native Matter climate is the ground truth: the firmware gates its
        Thermostat FeatureMap per capability, and dry / fan-only appear only with the
        extra-hvac-modes unlock installed. While it is unavailable we cannot read that,
        so fall back to gating Heat/Auto on cool_heat (permissive when unknown).
        """
        s = self._state(self._base)
        base_modes = s.attributes.get("hvac_modes") if s else None
        if base_modes and (mirrored := [m for m in ALL_HVAC_MODES if m in base_modes]):
            return mirrored
        caps = self._capabilities
        if supports(caps, HEAT_CAPABILITY):
            return list(ALL_HVAC_MODES)
        return [m for m in ALL_HVAC_MODES if m not in HEAT_PUMP_MODES]

    @property
    def _preset_entities(self) -> dict[str, str | None]:
        """Backing switch per single preset (None when this unit has not got it).

        Sleep is not here on purpose: it is a five-profile ModeSelect owned by the sleep
        select entity, so no preset may write it. This entity still reads it, but only to
        know whether it is holding the fan (see _forced_fan_mode).
        """
        return {
            PRESET_ECO: self._eco,
            PRESET_QUIET: self._quiet,
            PRESET_TURBO: self._turbo,
        }

    def _sleep_active(self) -> bool:
        """Whether a sleep profile is running (any option other than Off)."""
        return self._sleep_option() is not None

    def _sleep_option(self) -> str | None:
        """The running sleep profile, or None for Off / unknown."""
        s = self._state(self._sleep)
        if not s or s.state in ({SLEEP_OFF_OPTION} | UNAVAILABLE_STATES):
            return None
        return s.state

    def _sleep_profiles(self) -> list[str]:
        """Selectable sleep profiles, mirrored from the select, minus Off.

        Mirrored rather than hardcoded for the same reason as the select entity: the
        firmware owns the ModeSelect option list.
        """
        s = self._state(self._sleep)
        options = (s.attributes.get("options") if s else None) or SLEEP_PROFILE_OPTIONS
        return [o for o in options if o != SLEEP_OFF_OPTION]

    def _preset_plan(self) -> dict[str, tuple[tuple[str, ...], str]]:
        """preset value -> (switches to hold on, sleep option to hold).

        The single definition of what every preset means, used to advertise the list, to
        recognise the current state, and to drive it. Built per unit, so a missing switch
        or a shorter ModeSelect option list simply yields fewer presets.

        Which pairings exist is hardware, measured on node 14:
        eco + a sleep profile WORKS (all four profiles), so each pair is offered.
        quiet + sleep does NOT: the second one commanded always drops the first, in both
        orders. Turbo combines with nothing.
        """
        caps = self._capabilities
        entities = self._preset_entities
        singles = [
            preset
            for preset, entity in entities.items()
            if entity
            and ((cap := PRESET_CAPABILITY.get(preset)) is None or supports(caps, cap))
        ]

        plan: dict[str, tuple[tuple[str, ...], str]] = {
            PRESET_NONE: ((), SLEEP_OFF_OPTION)
        }
        for preset in singles:
            plan[preset] = ((preset,), SLEEP_OFF_OPTION)
        for combo, members in PRESET_COMBOS.items():
            if all(m in singles for m in members):
                plan[combo] = (tuple(members), SLEEP_OFF_OPTION)
        if self._sleep:
            for option in self._sleep_profiles():
                plan[f"{SLEEP_PRESET_PREFIX}{option.lower()}"] = ((), option)
            if PRESET_ECO in singles:
                for option in self._sleep_profiles():
                    key = f"{PRESET_ECO}_{SLEEP_PRESET_PREFIX}{option.lower()}"
                    plan[key] = ((PRESET_ECO,), option)
        return plan

    @property
    def preset_modes(self) -> list[str]:
        """Every state this unit can actually hold, one preset value each.

        HA's preset is single-valued, so a state with two modes on needs its own value.
        That is why eco + each sleep profile appears as its own preset: those genuinely
        coexist on the hardware, and the thermostat card can only drive climate features.
        """
        return list(self._preset_plan())

    @property
    def supported_features(self) -> ClimateEntityFeature:
        """Advertise only what is wired up: no fan entity means no fan/swing control."""
        features = (
            ClimateEntityFeature.TARGET_TEMPERATURE
            | ClimateEntityFeature.TURN_ON
            | ClimateEntityFeature.TURN_OFF
        )
        if self._fan:
            features |= ClimateEntityFeature.FAN_MODE | ClimateEntityFeature.SWING_MODE
        # The sleep select no longer contributes here, so a unit whose only special-mode
        # entity is the sleep ModeSelect legitimately reports no preset support.
        if len(self.preset_modes) > 1:  # more than the bare "none"
            features |= ClimateEntityFeature.PRESET_MODE
        return features

    @property
    def hvac_mode(self) -> HVACMode | None:
        s = self._state(self._base)
        if not s or s.state in UNAVAILABLE_STATES:
            return None
        try:
            return HVACMode(s.state)
        except ValueError:
            return None

    @property
    def hvac_action(self) -> HVACAction | None:
        s = self._state(self._base)
        action = s.attributes.get("hvac_action") if s else None
        try:
            return HVACAction(action) if action else None
        except ValueError:
            return None

    @property
    def current_temperature(self) -> float | None:
        s = self._state(self._base)
        return s.attributes.get("current_temperature") if s else None

    @property
    def target_temperature(self) -> float | None:
        # Setpoint only meaningful in cool/heat -> hide it elsewhere.
        if self.hvac_mode not in SETPOINT_MODES:
            return None
        s = self._state(self._base)
        return s.attributes.get("temperature") if s else None

    @property
    def fan_mode(self) -> str | None:
        """Mirror the native fan's mode, or None while it is not reporting one.

        Never default to "auto" here. The underlying fan has no preset_mode only while it
        is unavailable or still being set up, and claiming "auto" then is a lie: right
        after a restart the A/C can be sitting at Low with quiet on, and reporting auto
        makes the card show a speed the unit is not running.
        """
        s = self._state(self._fan)
        if not s or s.state in UNAVAILABLE_STATES:
            return None
        return s.attributes.get("preset_mode")

    @property
    def swing_mode(self) -> str:
        s = self._state(self._fan)
        return "vertical" if (s and s.attributes.get("oscillating")) else "off"

    @property
    def preset_mode(self) -> str:
        # Never report a preset we do not advertise (HA rejects an out-of-list value).
        current = self._detect_preset()
        return current if current in self.preset_modes else PRESET_NONE

    def _active_presets(self) -> set[str]:
        """Which of the preset switches the A/C currently reports as on.

        Only eco/quiet/turbo: sleep is the select's business, so it never appears here
        and can never change what preset_mode reports.
        """
        return {
            preset
            for preset, entity in self._preset_entities.items()
            if self._is_on(entity)
        }

    def _detect_preset(self) -> str:
        """Name the state the unit is in, from the same table used to drive it."""
        active = self._active_presets()
        sleep = self._sleep_option() or SLEEP_OFF_OPTION
        for preset, (members, option) in self._preset_plan().items():
            if active == set(members) and sleep == option:
                return preset
        # No exact match: an arbitration is in flight (the A/C drops one of an illegal
        # pair a second or two after the command). Report the strongest thing that is
        # really on, so the preset still tracks reality rather than snapping to none.
        if PRESET_TURBO in active:
            return PRESET_TURBO
        for preset in (PRESET_ECO, PRESET_QUIET):
            if preset in active:
                return preset
        if sleep != SLEEP_OFF_OPTION:
            return f"{SLEEP_PRESET_PREFIX}{sleep.lower()}"
        return PRESET_NONE

    def _forced_fan_mode(self) -> tuple[str, str] | None:
        """The active special that owns the fan, and the mode it pins it to.

        None when the fan is free. Only quiet / sleep / turbo pin it; eco does not.

        This reads the backing entities, so a mode the A/C has but HA has not learned yet
        (the first minute or so after a restart, or an unavailable switch) reads as absent
        and the guard lets the command through. That is the permissive direction on
        purpose, matching the capability gating: unknown is not the same as set. The cost
        is the old one-second revert in that window, not a wrongly blocked command.
        """
        active = self._active_presets()
        for preset, mode in FAN_FORCING_PRESETS.items():
            if preset in active or (preset == PRESET_SLEEP and self._sleep_active()):
                return preset, mode
        return None

    # ----------------------------------------------------------------- commands
    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        await self.hass.services.async_call(
            "climate",
            "set_hvac_mode",
            {"entity_id": self._base, "hvac_mode": hvac_mode},
            blocking=True,
        )

    async def async_turn_on(self) -> None:
        await self.async_set_hvac_mode(HVACMode.COOL)

    async def async_turn_off(self) -> None:
        await self.async_set_hvac_mode(HVACMode.OFF)

    async def async_set_temperature(self, **kwargs: Any) -> None:
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return
        if self.hvac_mode not in SETPOINT_MODES:
            _LOGGER.debug(
                "%s: ignoring setpoint in mode %s", self.entity_id, self.hvac_mode
            )
            return
        await self.hass.services.async_call(
            "climate",
            "set_temperature",
            {"entity_id": self._base, "temperature": temperature},
            blocking=True,
        )

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        """Set the fan speed, refusing what an active special mode would overwrite.

        Quiet, sleep and turbo each own the A/C's fan profile (firmware/docs/05 "Special
        functions"). The write itself succeeds everywhere: Matter acks it and the fan
        entity shows it. But the A/C keeps reporting its forced speed, so the firmware's
        roughly 1 Hz status downlink writes that speed back over ours about a second
        later. Nothing rejects the command, so without this guard the service returns
        success for a change that visibly undoes itself. Refuse it and name the preset
        holding the fan instead. Clearing that preset here would throw away a mode the
        user deliberately set, and it could not be done in one frame anyway: the combined
        command frame does not carry the mute byte and the A/C needs a settle between
        frames. Note the asymmetry this leaves: turning a forcing preset ON still
        overrides an existing fan mode, because there the newer command is the intent.
        """
        if not self._fan:
            return
        if (forced := self._forced_fan_mode()) and forced[1] != fan_mode:
            preset, mode = forced
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="fan_mode_forced_by_preset",
                translation_placeholders={
                    "fan_mode": fan_mode,
                    "preset": preset,
                    "forced": mode,
                },
            )
        if fan_mode == "auto":
            await self.hass.services.async_call(
                "fan",
                "set_preset_mode",
                {"entity_id": self._fan, "preset_mode": "auto"},
                blocking=True,
            )
        else:
            await self.hass.services.async_call(
                "fan",
                "set_percentage",
                {
                    "entity_id": self._fan,
                    "percentage": FAN_PERCENT.get(fan_mode, 58),
                },
                blocking=True,
            )

    async def async_set_swing_mode(self, swing_mode: str) -> None:
        if not self._fan:
            return
        await self.hass.services.async_call(
            "fan",
            "oscillate",
            {"entity_id": self._fan, "oscillating": swing_mode == "vertical"},
            blocking=True,
        )

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Drive eco / quiet / turbo / sleep to exactly what this preset means.

        The preset fully determines all four, so a sleep preset clears the switches and a
        switch preset clears sleep. That is not us inventing an interlock: the A/C makes
        sleep exclusive with eco, quiet and turbo (measured), so writing it explicitly
        just makes the state deterministic instead of relying on the unit to cancel it.

        Only the frames that change something are sent, because each one after the first
        has to wait COMBO_SETTLE_SECONDS: this A/C's debounce swallows whatever arrives
        too soon after the previous command. Skipping no-op frames keeps the common case
        fast and leaves the wait only where a real change needs it.
        """
        members, target_sleep = self._preset_plan().get(
            preset_mode, ((), SLEEP_OFF_OPTION)
        )
        entities = self._preset_entities
        frames: list[tuple[str, str, dict[str, Any]]] = []

        # Clear the switches this preset does not want, in one frame.
        if stale := [
            e for p, e in entities.items() if e and p not in members and self._is_on(e)
        ]:
            frames.append(("switch", "turn_off", {"entity_id": stale}))
        # Enable the members that are not on yet.
        frames.extend(
            ("switch", "turn_on", {"entity_id": entities[p]})
            for p in members
            if entities.get(p) and not self._is_on(entities[p])
        )
        # Sleep goes LAST, and that ordering is load-bearing. Eco rides the combined
        # command frame, which re-asserts the fan from the command shadow, and a sleep
        # profile owns the fan: commanding eco after sleep makes the A/C drop the profile.
        # Measured on node 14: eco then sleep gives BOTH for all four profiles, sleep then
        # eco loses the profile.
        if self._sleep and (self._sleep_option() or SLEEP_OFF_OPTION) != target_sleep:
            frames.append(
                (
                    "select",
                    "select_option",
                    {"entity_id": self._sleep, "option": target_sleep},
                )
            )

        for index, (domain, service, data) in enumerate(frames):
            if index:
                await asyncio.sleep(COMBO_SETTLE_SECONDS)
            await self.hass.services.async_call(domain, service, data, blocking=True)
