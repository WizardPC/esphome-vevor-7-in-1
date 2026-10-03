#!/usr/bin/env bash
# Répare le problème d'ensurepip : ESPHome doit créer un venv pour ESP-IDF, mais le
# Python de Debian 13 livré dans ce conteneur est sans ensurepip (paquet python3-venv,
# non installable sans sudo). On installe donc un Python autonome (python-build-standalone
# via uv) qui embarque ensurepip, et on reconstruit le venv du projet dessus.
set -euo pipefail
cd "$(dirname "$0")/.."
DEV="$(cd "$(dirname "$0")/.." && pwd)"
ROOT="$(cd "$DEV/.." && pwd)"

echo "== 1. uv dans le venv actuel =="
if [ ! -x .venv/bin/uv ]; then .venv/bin/pip install -q uv; fi
.venv/bin/uv --version

echo "== 2. Python autonome =="
UVP="$(.venv/bin/uv python dir)"
# On cible explicitement le Python géré par uv (et non le python du venv courant).
SYS_PY="$(ls -d "$UVP"/cpython-3.13.*/bin/python3.13 2>/dev/null | head -1)"
if [ -z "$SYS_PY" ]; then
  .venv/bin/uv python install 3.13
  SYS_PY="$(ls -d "$UVP"/cpython-3.13.*/bin/python3.13 | head -1)"
fi
echo "python autonome: $SYS_PY"
"$SYS_PY" -c "import ensurepip, sys; print('ensurepip OK ->', ensurepip.__file__); print(sys.version)"

echo "== 3. reconstruction du venv du projet =="
rm -rf "$ROOT/.venv"
"$SYS_PY" -m venv "$ROOT/.venv"
"$ROOT/.venv/bin/python" -m pip --version

echo "== 4. réinstallation d'ESPHome =="
"$ROOT/.venv/bin/pip" install -q --upgrade pip wheel
"$ROOT/.venv/bin/pip" install -q esphome aioesphomeapi
"$ROOT/.venv/bin/esphome" version

echo "== 5. test : le python du venv sait-il créer un venv avec pip ? =="
rm -rf /tmp/venvtest
"$ROOT/.venv/bin/python" -m venv /tmp/venvtest
/tmp/venvtest/bin/pip --version && echo "TEST VENV: OK"
rm -rf /tmp/venvtest
echo "== réparation terminée =="
