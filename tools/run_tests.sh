#!/usr/bin/env bash
# Tests hors matériel du décodeur Vevor 7-en-1.
#
#   tools/run_tests.sh
#
# Étapes : selfcheck de l'encodeur Python (doit reproduire la trame de rtl_433 octet pour octet)
#          → génération des trames de test → compilation du test C++ → exécution.
# Aucun accès à la carte n'est nécessaire : c'est ce qui permet à n'importe qui de vérifier le
# décodeur, et à la boucle de ne pas casser une logique déjà validée.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEV_PY="$ROOT/.venv-dev/bin/python"

if [ ! -x "$DEV_PY" ]; then
  echo "Il manque le compilateur de développement (.venv-dev)."
  echo "Installation (n'affecte pas la toolchain ESPHome) :"
  echo "  PY=/home/\$USER/.local/share/uv/python/cpython-3.13.15-linux-x86_64-gnu/bin/python3.13"
  echo "  \$PY -m venv $ROOT/.venv-dev && $ROOT/.venv-dev/bin/pip install ziglang"
  exit 3
fi

mkdir -p "$ROOT/build"
echo "=== 1. selfcheck de l'encodeur (reproduit-il la trame de rtl_433 ?) ==="
"$DEV_PY" "$ROOT/tests/frames.py" --selfcheck || exit 1

echo "=== 2. génération des trames de test ==="
"$DEV_PY" "$ROOT/tests/frames.py" --vectors || exit 1

echo "=== 2b. génération des scénarios d'impulsions (chaîne asynchrone) ==="
"$DEV_PY" "$ROOT/tests/frames.py" --pulses || exit 1

echo "=== 3. compilation du test C++ ==="
"$DEV_PY" -m ziglang c++ -std=c++17 -w \
  -I "$ROOT/esphome/includes" -I "$ROOT/tests" \
  "$ROOT/tests/test_decoder.cpp" -o "$ROOT/build/test_decoder" || exit 2
echo "binaire : build/test_decoder"

echo "=== 4. exécution ==="
"$ROOT/build/test_decoder"
