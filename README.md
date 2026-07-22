# Hisense W41H1 Unified AC

A Home Assistant custom integration (HACS-compatible) that merges a de-clouded
Hisense **AEH-W41H1** A/C's native Matter entities into **one climate entity**:

- HVAC modes: off / cool / heat / auto / dry / fan-only
- Fan: auto / low / medium / high (fixed speeds drive the percentage path)
- Swing: off / vertical (Matter fan oscillation)
- Presets: **eco / quiet / turbo / sleep** (folded in from the special-mode switches + sleep select)
- Setpoint gated to **cool/heat** — a temp change in dry/fan-only/auto/off is a no-op and shows no target

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
- Dry / fan-only / single-setpoint unlocked on the native climate (HA gates those
  on a vendor allow-list; the companion `matter_ac_unlock` component adds the
  W41H1's test IDs `0xFFF1/0x8001`).

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

Point `entity` at your unit (one card per A/C).

## AI assistance

Parts of this integration were developed with AI assistance.
