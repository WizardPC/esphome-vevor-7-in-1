#!/usr/bin/env bash
# Off-hardware tests of the Vevor 7-in-1 decoder.
#
#   tools/run_tests.sh
#
# Steps: Python encoder selfcheck (must reproduce the rtl_433 frame byte for byte)
#        -> generate test frames -> compile the C++ test -> run.
#
# No board access needed, so anyone can verify the decoder and the loop cannot break
# already-validated logic.
set -uo pipefail
DEV="$(cd "$(dirname "$0")/.." && pwd)"   # dev/: tools, tests, docs, logs
ROOT="$(cd "$DEV/.." && pwd)"            # repo root: esphome/ lives here, and nothing else
DEV_PY="$ROOT/.venv-dev/bin/python"

if [ ! -x "$DEV_PY" ]; then
  echo "The development compiler (.venv-dev) is missing."
  echo "Install (does not affect the ESPHome toolchain):"
  echo "  PY=/home/\$USER/.local/share/uv/python/cpython-3.13.15-linux-x86_64-gnu/bin/python3.13"
  echo "  \$PY -m venv $ROOT/.venv-dev && $ROOT/.venv-dev/bin/pip install ziglang"
  exit 3
fi

mkdir -p "$DEV/build"
echo "=== 1. encoder selfcheck (does it reproduce the rtl_433 frame?) ==="
"$DEV_PY" "$DEV/tests/frames.py" --selfcheck || exit 1

echo "=== 2. generating the test frames ==="
"$DEV_PY" "$DEV/tests/frames.py" --vectors || exit 1

echo "=== 2b. generating the pulse scenarios (asynchronous path) ==="
"$DEV_PY" "$DEV/tests/frames.py" --pulses || exit 1

echo "=== 2c. generating the REAL bursts (dump regression vectors) ==="
"$DEV_PY" "$DEV/tests/frames.py" --captures || exit 1

echo "=== 3. compiling the C++ test ==="
"$DEV_PY" -m ziglang c++ -std=c++17 -w \
  -I "$ROOT/esphome/components/vevor_7in1" -I "$DEV/tests" \
  "$DEV/tests/test_decoder.cpp" -o "$DEV/build/test_decoder" || exit 2
echo "binary: build/test_decoder"

echo "=== 4. run ==="
"$DEV/build/test_decoder" || exit 4

echo "=== 5. firmware / Home Assistant card / entity listing consistency ==="
# This check used to live outside the suite: an entity rename or a file move could break it
# silently. It is now a step, and its failure fails the suite. It needs PyYAML and jinja2,
# present in the ESPHome environment.
if [ -x "$ROOT/.venv/bin/python" ]; then
  "$ROOT/.venv/bin/python" "$DEV/tools/check_ha_card.py" || exit 5
else
  echo "SKIPPED: $ROOT/.venv/bin/python missing (ESPHome environment) — step not run." >&2
  echo "  Entity consistency was NOT checked." >&2
fi

echo "=== 6. every template in the card is ACCEPTED by Home Assistant ==="
# The card's sky icon once used `(elevation | sin)` on a value in DEGREES: HA's `sin` takes radians,
# the power of a negative number is complex, HA refused the template and the icon vanished from the
# card. The offline simulation could not see it — it defined `sin` itself. This step simulates
# nothing: it posts the real templates to HA and fails on any refusal (skipped if HA is unreachable).
if [ -x "$ROOT/.venv/bin/python" ]; then
  "$ROOT/.venv/bin/python" "$DEV/tools/check_ha_templates.py" || exit 6
else
  echo "SKIPPED: $ROOT/.venv/bin/python missing — card templates NOT verified." >&2
fi
