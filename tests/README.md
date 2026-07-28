# QA

`./run_tests.sh` from the repo root. Non-zero exit on any failure, `ALL GREEN` otherwise.

Three tiers, cheapest first, because the expensive one needs a real A/C.

## 1. Pure logic and metadata (no dependencies)

`test_features.py` and `test_metadata.py` run under a bare `python3` with nothing
installed. They cover capability decoding and gating, and they catch metadata drift:
icons or labels for a preset that can no longer occur, a preset with no icon, an exception
message whose placeholders no longer match what the code passes, `strings.json` and
`translations/en.json` disagreeing.

They also encode hardware measurements as assertions, so a later "tidy-up" cannot quietly
undo them: `COMBO_SETTLE_SECONDS` must stay at or above 8 (at 6 the A/C swallowed the
second command every time), and the fan-forcing table must keep all three modes that pin
the fan. Both of those were real bugs.

## 2. Entity behaviour (needs `homeassistant`)

`test_climate.py` and `test_select.py` drive the entities against stub state: what they
advertise, what they report, and the exact service calls and settle gaps they emit. No
`pytest-homeassistant-custom-component`, no real `hass`, because these entities only ever
touch `hass.states.get()` and `hass.services.async_call()` (see `stubs.py`).

`run_tests.sh` skips this tier with a warning when `homeassistant` is not importable, so
the dev box still gets tier 1. To run it against the exact HA version the units talk to:

```bash
HA_SSH="ssh -i ~/.ssh/your_key root@YOUR_PI" ./run_tests.sh --container
```

That copies the suite into the running HA container and runs it there. Without `HA_SSH` it
uses the local docker daemon. Override the container name with `HA_CONTAINER`.

Both tiers also run under pytest (`pytest tests/`) if you prefer, and that is what CI does
via `run_tests.sh`.

## 3. Hardware, opt-in

`hil/ha_selftest.yaml` is an end-to-end run through HA's own service calls on a real unit:
the fan guard refusing a conflicting change, a sleep profile engaging, the combination
preset applying, and the A/C's own arbitration cancelling sleep. Copy it into
`<config>/packages/`, restart HA, then read the results:

```bash
grep -E 'hu_selftest|Cannot set fan mode' <config>/home-assistant.log
```

**Delete it afterwards**: it runs on every HA start and it commands a real A/C. It targets
the kitchen entity ids, so edit those first, and note that it leaves the unit on
`eco_quiet` with sleep `Off`. It found two real bugs on its first run that the stub tests
could not have: an entity that reported a fan mode the unit was not running, and a guard
that silently allowed a command while its backing state was still unpopulated after a
restart.

## Adding tests

Keep tier 1 free of Home Assistant imports; `_pkg.install()` is what lets those modules
import `const.py` and `features.py` without executing the package `__init__.py` (which
imports HA). Each file ends with a `run_module(globals())` block so it stays runnable with
plain `python3`.

When fixing a bug, prove the test catches it: revert the fix, watch the test fail, restore
it. Four faults were injected this way while writing this suite, and the fourth found a
hole in the test rather than in the code.
