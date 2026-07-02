#!/bin/sh
# Runs the same validation steps as CI: byte-compile, unit tests, and the
# examples/sample-output round-trip (regenerate, check, idempotency, diff).
set -eu
cd "$(dirname "$0")/.."

PYTHON="${PYTHON:-python3}"

echo "==> byte-compile"
"$PYTHON" -m py_compile scripts/agent_context.py

echo "==> unit tests"
"$PYTHON" -m unittest discover -s tests

echo "==> sample-output round-trip"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
mkdir "$tmp/sample-output"
cp examples/sample-output/README.md examples/sample-output/package.json "$tmp/sample-output/"
# The first run's generated files become part of the inventory, so scaffold
# converges on the second run (see examples/HOWTO.md).
"$PYTHON" scripts/agent_context.py scaffold "$tmp/sample-output" --agent generic > /dev/null
"$PYTHON" scripts/agent_context.py scaffold "$tmp/sample-output" --agent generic > /dev/null
"$PYTHON" scripts/agent_context.py check "$tmp/sample-output"
third_run="$("$PYTHON" scripts/agent_context.py scaffold "$tmp/sample-output" --agent generic)"
case "$third_run" in
  "no changes") ;;
  *)
    echo "scaffold did not reach a fixed point after two runs:" >&2
    echo "$third_run" >&2
    exit 1
    ;;
esac
# The second scaffold run snapshots the core.md update in the (non-git) tmp
# tree; snapshots are tool byproducts and stay out of the committed example.
diff -r -x .gitkeep -x snapshots examples/sample-output "$tmp/sample-output"

echo "OK"
