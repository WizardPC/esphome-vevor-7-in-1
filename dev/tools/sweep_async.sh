#!/usr/bin/env bash
# Frequency sweep in ASYNCHRONOUS mode.
#
# In packet mode a step was judged by the number of received "packets"; that counter no longer
# exists here, so frames REALLY EXTRACTED from the demodulated stream (preamble + syncword +
# 21 bytes) are counted — a stronger criterion: a checksum-validated frame cannot come from noise.
#
# Usage: tools/sweep_async.sh [host] [seconds_per_step] [start_MHz] [stop_MHz] [step_MHz]
set -uo pipefail
DEV="$(cd "$(dirname "$0")/.." && pwd)"   # dev/: tools, tests, docs, logs
ROOT="$(cd "$DEV/.." && pwd)"            # repo root: esphome/ lives here, and nothing else
HOST="${1:-${VEVOR_HOST:-}}"
if [ -z "$HOST" ]; then
  echo "usage: $(basename "$0") <board-ip> [seconds/step] [start] [stop] [step]" >&2
  echo "  the address may also come from the VEVOR_HOST variable, or dev/tools/find_esp32.py" >&2
  exit 3
fi
DWELL="${2:-25}"
START="${3:-867.80}"
STOP="${4:-868.60}"
STEP="${5:-0.05}"
mkdir -p "$DEV/logs"

echo "# asynchronous sweep from $START to $STOP MHz in steps of $STEP, $DWELL s per step"
f="$START"
while awk "BEGIN{exit !($f <= $STOP + 1e-9)}"; do
  "$ROOT/.venv/bin/python" "$DEV/tools/scan_freq.py" --host "$HOST" --set "$f" >/dev/null 2>&1
  sleep 1
  LOG="$DEV/logs/sweepas_${f}.log"
  timeout $((DWELL + 12)) "$ROOT/.venv/bin/python" "$DEV/tools/capture_logs.py" \
      --host "$HOST" --seconds "$DWELL" --out "$LOG" >/dev/null 2>&1
  EXT=$(grep -c "trame extraite" "$LOG" 2>/dev/null || echo 0)
  RAW=$(grep -c "V7IN1 RAW" "$LOG" 2>/dev/null || echo 0)
  OK=$(grep -c "V7IN1 OK" "$LOG" 2>/dev/null || echo 0)
  printf '%9s MHz   extracted=%-4s RAW=%-4s VALID=%-4s\n' "$f" "$EXT" "$RAW" "$OK"
  f=$(awk "BEGIN{printf \"%.2f\", $f + $STEP}")
done
echo "# end of sweep — a step with VALID > 0 is the right one"
