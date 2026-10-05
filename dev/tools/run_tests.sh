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
  echo "Il manque le compilateur de développement (.venv-dev)."
  echo "Installation (n'affecte pas la toolchain ESPHome) :"
  echo "  PY=/home/\$USER/.local/share/uv/python/cpython-3.13.15-linux-x86_64-gnu/bin/python3.13"
  echo "  \$PY -m venv $ROOT/.venv-dev && $ROOT/.venv-dev/bin/pip install ziglang"
  exit 3
fi

mkdir -p "$DEV/build"
echo "=== 1. selfcheck de l'encodeur (reproduit-il la trame de rtl_433 ?) ==="
"$DEV_PY" "$DEV/tests/frames.py" --selfcheck || exit 1

echo "=== 2. génération des trames de test ==="
"$DEV_PY" "$DEV/tests/frames.py" --vectors || exit 1

echo "=== 2b. génération des scénarios d'impulsions (chaîne asynchrone) ==="
"$DEV_PY" "$DEV/tests/frames.py" --pulses || exit 1

echo "=== 2c. génération des rafales RÉELLES (vecteurs de régression du dump) ==="
"$DEV_PY" "$DEV/tests/frames.py" --captures || exit 1

echo "=== 3. compilation du test C++ ==="
"$DEV_PY" -m ziglang c++ -std=c++17 -w \
  -I "$ROOT/esphome/components/vevor_7in1" -I "$DEV/tests" \
  "$DEV/tests/test_decoder.cpp" -o "$DEV/build/test_decoder" || exit 2
echo "binaire : build/test_decoder"

echo "=== 4. exécution ==="
"$DEV/build/test_decoder" || exit 4

echo "=== 5. cohérence firmware / carte Home Assistant / relevé d'entités ==="
# This check used to live outside the suite: an entity rename or a file move could break it
# silently. It is now a step, and its failure fails the suite. It needs PyYAML and jinja2,
# present in the ESPHome environment.
if [ -x "$ROOT/.venv/bin/python" ]; then
  "$ROOT/.venv/bin/python" "$DEV/tools/check_ha_card.py" || exit 5
else
  echo "IGNORÉ : $ROOT/.venv/bin/python absent (environnement ESPHome) — étape non exécutée." >&2
  echo "  La cohérence des entités n'a PAS été vérifiée." >&2
fi
