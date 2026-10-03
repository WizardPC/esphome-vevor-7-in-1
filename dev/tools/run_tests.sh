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
DEV="$(cd "$(dirname "$0")/.." && pwd)"   # dev/ : outils, tests, docs, journaux
ROOT="$(cd "$DEV/.." && pwd)"            # racine du dépôt : esphome/ y vit, et rien d'autre
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
"$DEV/build/test_decoder"
