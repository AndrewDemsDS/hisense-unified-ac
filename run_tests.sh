#!/usr/bin/env bash
# QA for the Hisense W41H1 Unified AC integration. Non-zero exit on any failure.
#
#   ./run_tests.sh              run everything this machine can run
#   ./run_tests.sh --container  run the HA-dependent tests inside a running HA container
#
# Three tiers, cheapest first:
#   1. pure       capability decoding + metadata drift. No dependencies at all.
#   2. entity     climate + select behaviour against stub state. Needs `homeassistant`.
#   3. hardware   tests/hil/, opt-in, commands a real A/C. Never run from here.
#
# Tier 2 is skipped with a warning when homeassistant is missing, so the dev box does not
# need an HA install to get most of the value. CI installs it and runs everything.
set -uo pipefail
cd "$(dirname "$0")"

PURE_TESTS=(tests/test_features.py tests/test_metadata.py)
ENTITY_TESTS=(tests/test_climate.py tests/test_select.py)

# --container: copy the suite into a running HA container and run it there. That is the
# quickest way to test against the exact HA version the units are actually talking to.
if [[ "${1:-}" == "--container" ]]; then
  CONTAINER="${HA_CONTAINER:-homeassistant}"
  DOCKER="${DOCKER:-docker}"
  HOST="${HA_SSH:-}"   # e.g. HA_SSH="ssh -i ~/.ssh/id_ed25519 root@192.168.1.x"
  run() { if [[ -n "$HOST" ]]; then $HOST "$*"; else eval "$*"; fi; }
  echo "== copying suite into container '$CONTAINER' =="
  if [[ -n "$HOST" ]]; then
    tar cf - tests custom_components | $HOST "cat > /tmp/hu_suite.tar" || exit 1
    run "$DOCKER cp /tmp/hu_suite.tar $CONTAINER:/tmp/hu_suite.tar" || exit 1
  else
    tar cf /tmp/hu_suite.tar tests custom_components || exit 1
    $DOCKER cp /tmp/hu_suite.tar "$CONTAINER":/tmp/hu_suite.tar || exit 1
  fi
  run "$DOCKER exec $CONTAINER sh -c 'rm -rf /tmp/hu_suite && mkdir -p /tmp/hu_suite && tar xf /tmp/hu_suite.tar -C /tmp/hu_suite'" || exit 1
  status=0
  for t in "${PURE_TESTS[@]}" "${ENTITY_TESTS[@]}"; do
    echo "== $t (in container) =="
    run "$DOCKER exec $CONTAINER python /tmp/hu_suite/$t" || status=1
  done
  exit "$status"
fi

PY="${PYTHON:-python3}"
status=0

for t in "${PURE_TESTS[@]}"; do
  echo "== $t =="
  "$PY" "$t" || status=1
done

if "$PY" -c "import homeassistant" 2>/dev/null; then
  for t in "${ENTITY_TESTS[@]}"; do
    echo "== $t =="
    "$PY" "$t" || status=1
  done
else
  echo "== ${ENTITY_TESTS[*]}: SKIPPED (homeassistant not installed) =="
  echo "   install it, or use ./run_tests.sh --container to run against a live HA."
fi

if command -v ruff >/dev/null 2>&1; then
  echo "== ruff =="
  ruff check custom_components tests || status=1
  ruff format --check custom_components tests || status=1
else
  echo "== ruff: SKIPPED (not installed) =="
fi

[[ "$status" == 0 ]] && echo "ALL GREEN" || echo "FAILURES ABOVE"
exit "$status"
