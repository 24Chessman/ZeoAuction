#!/bin/sh
# Runs every test suite, each service in its own pytest process (all services use the
# package name "app", so they cannot share one interpreter). Owner: Ayush.
#
# Prerequisite (once, in a virtualenv):
#   pip install ./libs/zeo-common -r requirements-dev.txt
set -u

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="${PYTHON:-python}"
failed=""

run() {
  label="$1"; shift
  echo "==> $label"
  if ! "$@"; then
    failed="$failed $label"
  fi
}

run "zeo-common" "$PYTHON" -m pytest -q "$ROOT/libs/zeo-common"
run "contracts" "$PYTHON" -m pytest -q "$ROOT/tests/contracts"

for service_dir in "$ROOT"/services/*/; do
  name="$(basename "$service_dir")"
  run "$name" sh -c "cd '$service_dir' && '$PYTHON' -m pytest -q"
done

if [ -n "$failed" ]; then
  echo "FAILED:$failed"
  exit 1
fi
echo "All suites passed."
