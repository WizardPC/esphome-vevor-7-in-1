#!/usr/bin/env bash
# Capture les logs de l'ESP32 via l'API native ESPHome (port 6053) et écrit un fichier daté.
# Usage: tools/capture_logs.sh <IP> [secondes] [fichier_sortie]
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HOST="${1:?usage: capture_logs.sh <IP> [secondes] [sortie]}"
SECS="${2:-120}"
mkdir -p "$ROOT/logs"
OUT="${3:-$ROOT/logs/capture_$(date +%Y%m%d_%H%M%S).log}"
echo "[capture] $HOST pendant ${SECS}s -> $OUT"
"$ROOT/.venv/bin/python" "$ROOT/tools/capture_logs.py" \
  --host "$HOST" --seconds "$SECS" --out "$OUT" | tail -n 25
echo "$OUT"
