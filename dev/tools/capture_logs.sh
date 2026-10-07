#!/usr/bin/env bash
# Captures the ESP32 logs via the ESPHome native API (port 6053) and writes a dated file.
# Usage: tools/capture_logs.sh <IP> [seconds] [output_file]
set -euo pipefail
DEV="$(cd "$(dirname "$0")/.." && pwd)"   # dev/: tools, tests, docs, logs
ROOT="$(cd "$DEV/.." && pwd)"            # repo root: esphome/ lives here, and nothing else
HOST="${1:?usage: capture_logs.sh <IP> [seconds] [output]}"
SECS="${2:-120}"
mkdir -p "$DEV/logs"
OUT="${3:-$DEV/logs/capture_$(date +%Y%m%d_%H%M%S).log}"
echo "[capture] $HOST for ${SECS}s -> $OUT"
"$ROOT/.venv/bin/python" "$DEV/tools/capture_logs.py" \
  --host "$HOST" --seconds "$SECS" --out "$OUT" | tail -n 25
echo "$OUT"
