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

## AI assistance

Parts of this integration were developed with AI assistance.
