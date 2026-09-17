# Hisense W41H1 Unified AC

A Home Assistant custom integration (HACS-compatible) that merges a de-clouded
Hisense **AEH-W41H1** A/C's native Matter entities into **one climate entity**:

- HVAC modes: off / cool / heat / auto / dry / fan-only
- Fan: auto / low / medium_low / medium / medium_high / high, the same names as the
  hisense-w41h1 ESPHome build (fixed speeds drive the percentage path)
- Swing: off / vertical (Matter fan oscillation)
- Presets: **eco / quiet / turbo**, the legal pairing **eco+quiet**, and one preset per
  **sleep profile** (General / Old / Young / Kids), all on the thermostat card
- Sleep also gets its own **Sleep profile** dropdown entity
- Setpoint gated to **cool/heat** — a temp change in dry/fan-only/auto/off is a no-op and shows no target

Each of those is advertised only if *this* unit has it (see
[Capability matrix](#capability-matrix)).

It replaces the hand-maintained `climate_template` YAML package: units are added
through the UI (config flow), one entry per A/C.

## Prerequisite: the module must run the custom firmware

This is only the Home Assistant side. It assumes your AEH-W41H1 already runs the
de-cloud Matter firmware, and a stock module does not work with it.

Out of the box the AEH-W41H1 is Wi-Fi + ConnectLife cloud, with no usable local
control. The stock firmware does still ship a Matter stack, but a broken, test-grade
one: it commissions only with attestation bypass, and a cloud-paired unit usually
wedges partway through commissioning. So a stock unit looks Wi-Fi only.

Flashing the custom firmware fixes that, over the air on many units (it commissions
the stock test-Matter and pushes a real image through its OTA Requestor) or with a
CH341A SPI clip as a fallback. The firmware, the flashing steps, and the RS-485
protocol work live in the firmware project:
[AndrewDemsDS/hisense-w41h1](https://github.com/AndrewDemsDS/hisense-w41h1).

Order: flash with the firmware project first, then add this integration.

## Why

HA's Matter integration exposes the W41H1 as a climate **plus** a separate fan, a
redundant device-mandated Power switch, and unnamed On/Off switches for the
special modes. This wraps them into a single thermostat card, so the redundant
tiles can be hidden and the special modes live inside the climate as presets.

## Requirements

- The A/C already commissioned into HA over Matter.
- Dry / fan-only / single-setpoint unlocked on the native climate (HA gates those on a
  vendor allow-list; the companion
  [`ha-matter-extra-hvac-modes`](https://github.com/AndrewDemsDS/ha-matter-extra-hvac-modes)
  integration, domain `matter_extra_hvac_modes`, lifts that gate for test-vendor `0xFFF1`
  devices).

## Install (HACS)

1. HACS → Integrations → ⋮ → **Custom repositories** → add this repo, category
   **Integration**.
2. Install **Hisense W41H1 Unified AC**, restart HA.
3. Settings → Devices & Services → **Add Integration** → *Hisense W41H1 Unified
   AC* → pick the A/C's native Matter **climate** entity. The fan / eco-quiet-turbo
   switches / sleep select are auto-detected from the same device (override any if
   needed). Repeat per A/C.

Then hide the now-redundant native entities (the Power switch and the raw
special-mode switches) if you like — the unified entity covers them.

## Capability matrix

W41H1 modules are not all the same unit, so the climate entity advertises only what
the one in front of it can do. A feature that is not there is not offered, which means
HA rejects the command outright instead of accepting it and dropping it silently.

| Advertised | Needs | Source |
| --- | --- | --- |
| Heat, Auto | heat pump (`cool_heat`) | native climate's mode list, else the capability word |
| Dry, Fan-only | the [extra-hvac-modes unlock](#requirements) | native climate's mode list |
| Eco preset | eco switch + `power_save` | config entry + capability word |
| Quiet preset | quiet switch + `fan_mute` | config entry + capability word |
| Turbo preset | turbo switch (no capability bit) | config entry |
| Sleep presets + dropdown | sleep select (no capability bit) | config entry, profiles from its option list |
| Fan + swing | a fan entity | config entry |

Two sources, in order. The **native Matter climate's own mode list** is the ground
truth for HVAC modes: the firmware already gates its Thermostat FeatureMap per
capability, so mirroring it also picks up the dry / fan-only unlock. The **capability
word** (the `Capabilities` diagnostic sensor, mfg cluster attr `0x0012`) gates the
presets, and covers HVAC modes while the native entity is unavailable.

Gating is permissive: **unknown is not unsupported**. A unit that never reported a
capability word, or reported an invalid one, gets everything offered. This mirrors the
firmware predicates (`matter_gate_eco` / `matter_gate_quiet` /
`matter_thermostat_featuremap`), and `features.py` is the one place the mapping lives.

### Combining special modes

HA's preset is single-valued, so the one legal combination is offered as its own preset
value: **Eco + Quiet**. Turbo combines with nothing, because it shares the byte33 feature
enum with eco (so Turbo XOR Eco is an exclusion in the encoding itself) and at the A/C it
also drops quiet and sleep, since it maxes power where they all reduce it.

Selecting a combination turns on its members one frame at a time with a settle gap,
because this A/C debounces rapid commands and swallows a mode that arrives too soon after
the previous one. That makes a combination take a few seconds to apply.

Interlock detail lives in `firmware/docs/05-ha-control-and-native-ui.md` ("Special
functions"), and `PRESET_COMBOS` in `features.py` is the table.

### Sleep: one preset per profile, plus its own dropdown

Sleep is a five-option ModeSelect (`Off / General / Old / Young / Kids`), and it is exposed
twice, because the thermostat card can only drive climate features:

- **As preset values**, one per profile: `sleep_general`, `sleep_old`, `sleep_young`,
  `sleep_kids`. So sleep is selectable from the card's preset control alongside
  eco/quiet/turbo. One preset per profile, never a single "sleep" that has to guess which
  profile you meant.
- **As a `Sleep profile` select entity**, for a direct profile picker with per-option icons.

Both are views of the same ModeSelect, so they always agree. `none` means no special mode
at all, sleep included.

A single-valued preset is the right shape here, because the A/C makes sleep exclusive with
the other specials: measured on a real unit, engaging eco, quiet or turbo cancels a running
sleep profile within a few seconds. Choosing a sleep preset therefore clears the switches,
and choosing a switch preset clears sleep, so the state is deterministic rather than
depending on the unit to cancel it. Only the frames that change something are sent, since
each one after the first costs a settle gap.

### Fan modes and the forcing interlock

Quiet, sleep and turbo each own the A/C's fan profile. While one is active the unified
climate **refuses** a conflicting fan change with a message naming the preset to clear,
instead of accepting it and letting it undo itself a second later. That revert is real and
it is not fixable here: the write succeeds, but the A/C keeps reporting its forced speed,
and the firmware's roughly 1 Hz status downlink writes that speed back over ours. The A/C's
quiet fan step has no Matter FanMode of its own, so it reads back as `low` regardless.

## Grouping several A/Cs

Since 1.4.0 the unified climate entity uses exactly the same fan and preset names as the
[hisense-w41h1 ESPHome build](https://github.com/AndrewDemsDS/hisense-w41h1/blob/main/docs/guide/ESPHome-Build.md):

- Fan: `auto`, `low`, `medium_low`, `medium`, `medium_high`, `high`
- Presets: `none`, `eco`, `quiet`, `turbo`, `eco_quiet`, `sleep_*`, `eco_sleep_*`

So several A/Cs, on Matter or ESPHome, can be driven as one thermostat with
[Climate Group Helper](https://github.com/bjrnptrsn/climate_group_helper) (HACS). Use its
`intersection` feature strategy and mirror sync on `hvac_mode`, `temperature` and `fan_mode`.

Add **this integration's** climate entity to the group, never the native Matter climate: the native one
has no fan, swing or presets, and reports a wider setpoint range that confuses the group's limits.
AmebaZ2 modules need firmware 1.3.38 or later for `medium_low` / `medium_high` to hold.

Full walkthrough, validated settings and behaviour notes:
[Climate Groups](https://github.com/AndrewDemsDS/hisense-w41h1/blob/main/docs/guide/Climate-Groups.md).

## Lovelace card

The unified entity renders in the built-in **Thermostat** card. A HA integration
can't inject a *native* Lovelace card (only JS cards can be backend-registered),
so add it to a dashboard yourself. Recommended layout — HVAC modes, fan/swing as
icons, and the special modes as a preset dropdown:

```yaml
type: vertical-stack
cards:
  - type: heading
    heading: Living Room A/C
    heading_style: title
    icon: mdi:air-conditioner
  - type: thermostat
    entity: climate.living_room_unified_ac
    features:
      - type: climate-hvac-modes
      - type: climate-fan-modes
        style: icons
      - type: climate-swing-modes
        style: icons
      - type: climate-preset-modes
        style: dropdown
```

Every preset carries its own icon (leaf / mute / rocket / bed / cane / child), so
`style: icons` works here too if you prefer a row of buttons. The sleep profiles are in
that preset control already; the separate select is only needed if you want a dedicated
profile picker:

```yaml
  - type: entities
    entities:
      - entity: select.your_ac_sleep_profile
        name: Sleep
```

Point `entity` at your unit (one card per A/C).

## AI assistance

Parts of this integration were developed with AI assistance.
