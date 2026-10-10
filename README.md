# Hisense W41H1 Unified AC

A Home Assistant custom integration (HACS-compatible) that merges a de-clouded
Hisense **AEH-W41H1** A/C's native Matter entities into **one climate entity**:

- HVAC modes: off / cool / heat / auto / dry / fan-only. `auto` is the unit's own auto mode,
  which Home Assistant's Matter integration calls `heat_cool`
- Fan: auto / low / medium_low / medium / medium_high / high, the same names as the
  hisense-w41h1 ESPHome build (fixed speeds drive the percentage path)
- Swing: off / vertical (Matter fan oscillation)
- Presets: **eco / quiet / turbo**, the legal pairing **eco+quiet**, and one preset per
  **sleep profile** (General / Old / Young / Kids), all on the thermostat card
- Sleep also gets its own **Sleep profile** dropdown entity
- Setpoint gated to **cool/heat** — a temp change in dry/fan-only/auto/off is a no-op and shows no target

Each of those is advertised only if *this* unit has it (see
[Capability matrix](#capability-matrix)).

Around that climate entity it builds one device with the same entities, names, icons and
grouping as the [hisense-w41h1 ESPHome build](https://github.com/AndrewDemsDS/hisense-w41h1/blob/main/docs/guide/ESPHome-Build.md),
so an A/C looks the same in Home Assistant whichever firmware it runs. See
[Entities](#entities).

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

The native device page is also hard to read: `Switch (Eco)`, `Temperature (Coil)`,
`Door (Aux Heat)`. The unified device re-exposes those under plain names (`Eco`,
`Coil temperature`, `Aux heat relay`) next to the diagnostics the Matter integration
cannot show at all.

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
   AC* → pick the A/C's native Matter **climate** entity. The fan, switches, sleep
   select and sensors are auto-detected from the same device (override any if
   needed). Repeat per A/C.

The form also asks for the Matter server WebSocket URL and the Matter node id, which the
diagnostics entities need. Both are filled in for you: the URL is the one Home
Assistant's own Matter integration uses, and the node id is read from the climate entity
when the field is left empty. Clear the URL to set the A/C up without diagnostics. Both
can be changed later under **Configure**.

The native Matter device keeps all of its own entities. Nothing is hidden or disabled
for you, so if you only want the unified device on your dashboards, disable or hide the
native ones yourself.

## Entities

The unified device carries these. Names, icons, device classes and categories are the
ESPHome build's, so the two device pages line up row for row.

| Entity | Platform | Group | From |
| --- | --- | --- | --- |
| (device name) | climate | Controls | native climate + fan + special modes |
| Sleep profile | select | Controls | native sleep select |
| Eco, Turbo, Quiet | switch | Configuration | native switches, also offered as presets |
| Panel display | switch | Configuration | native `Display` switch |
| Beeper | switch | Configuration | native `Beeper` switch (newer firmware) |
| Outdoor temperature, Coil temperature | sensor | Sensors | native temperature sensors |
| Power, Voltage, Current | sensor | Sensors | native electrical sensors |
| Compressor frequency | sensor | Sensors | diagnostics |
| Aux heat relay | binary sensor | Sensors | native contact sensor |
| Fault | binary sensor | Sensors | diagnostics, else the native fault contact sensor |
| AC bus link | binary sensor | Diagnostic | diagnostics (newer firmware), else native climate availability |
| Fault ... (18, one per fault bit) | binary sensor | Diagnostic | diagnostics |
| Capability ... (13, one per flag) | binary sensor | Diagnostic | diagnostics |
| Bus checksum errors, Bus reply timeouts, Unanswered commands, Bus link losses | sensor | Diagnostic | diagnostics (newer firmware) |
| AC device type | sensor | Diagnostic | diagnostics (newer firmware) |

"Diagnostics" means the manufacturer cluster, read straight from the Matter server, so
those rows need the URL and node id. Everything else works without them.

An entity exists only if the A/C has what backs it. On firmware without the beeper
endpoint, the bus counters or the device type, the Beeper switch and those sensors are
left out, so nothing sits on the device page as unavailable. After a firmware update adds
them, they appear without touching the integration.

The bus counters count since the node booted and restart at 0 when it reboots. `AC device
type` is the type and sub type the A/C reports about itself, shown as two hex bytes
(`01 02`), and stays unknown until the node has learned it. If a later firmware
removes an endpoint, its entity is removed at the next reload.

Four of the fault entities and three of the capability entities start enabled, the same
ones the ESPHome YAML declares (indoor temp sensor, indoor to outdoor comms, condensate
tray full, outdoor temp sensor; heat pump, eco, quiet). The rest are created disabled:
enable any you want under the device's entity list.

One thing the ESPHome device has is not here, because the Matter firmware does not
report it: `Energy today`. Feed the Power sensor to Home Assistant's Riemann sum helper
to get it.

### How the native entities are found

The endpoint label is tried first. The firmware labels every endpoint (`Eco`, `Quiet`, `Turbo`,
`Display`, `Beeper`, `Outdoor`, `Coil`, `Aux Heat`, `Fault`), and Home Assistant puts the
label in the entity name: `Switch (Beeper)`. If your Home Assistant shows `Switch (3)`
instead, the endpoint number in the entity's Matter unique id is used (3 eco, 4 quiet,
5 turbo, 9 display, 11 beeper, 2 outdoor, 8 coil, 7 aux heat, 10 fault). Power, voltage
and current are found by their cluster and attribute.

If a switch is not picked up, choose it by hand under **Configure**.

### Upgrading from 1.5.0 or earlier

Nothing has to be re-added and no entity id changes. An existing entry gets the new
switches and sensors at the next start. Three existing entities are renamed to match the
ESPHome build (`Faults` to `Fault`, `Bus link` to `AC bus link`, and the per-fault
entities to `Fault ...`), which changes their displayed name only. Entities you already
have stay enabled, including the `Capabilities` summary sensor, which is off by default
on new installs now that each flag has its own entity.

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
word** (the `Capability ...` diagnostic entities, mfg cluster attr `0x0012`) gates the
presets and the Eco and Quiet switches, and covers HVAC modes while the native entity is
unavailable.

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
