#!/usr/bin/env bash
# Deterministic state fingerprint for the autonomous loop.
#
# The scheduler compares this script's output from tick to tick: IDENTICAL output -> the agent
# is not launched at all (no cost, no message); DIFFERENT output -> the agent wakes with the
# diff and runs one iteration.
#
# This keeps the loop silent while there is nothing to do, and wakes it as soon as a serial
# port appears, an ESP32 becomes reachable, or the agent advanced state/PHASE.
#
# NEVER put a fine-grained timestamp here (it would change the fingerprint every tick) — hence
# the 6 h bucket, which only guarantees a control wake-up 4 times a day.
set -uo pipefail
DEV="$(cd "$(dirname "$0")/.." && pwd)"
ROOT="$(cd "$DEV/.." && pwd)"

SERIE="$(ls /dev/ttyUSB* /dev/ttyACM* 2>/dev/null | tr '\n' ',' || true)"
[ -n "$SERIE" ] || SERIE="aucun"
BYID="$(ls /dev/serial/by-id/ 2>/dev/null | tr '\n' ',' || true)"
[ -n "$BYID" ] || BYID="aucun"

PHASE="$( { [ -f "$DEV/state/PHASE" ] && tr -d '\n' < "$DEV/state/PHASE"; } 2>/dev/null || true)"
[ -n "$PHASE" ] || PHASE="phase=absent"

BUILD="$( { [ -f "$DEV/build/last_status.txt" ] && tr -d '\n' < "$DEV/build/last_status.txt"; } 2>/dev/null | cut -c1-24 || true)"
[ -n "$BUILD" ] || BUILD="aucun"
FLASH="$( { [ -f "$DEV/logs/last_flash_status.txt" ] && tr -d '\n' < "$DEV/logs/last_flash_status.txt"; } 2>/dev/null | cut -c1-28 || true)"
[ -n "$FLASH" ] || FLASH="aucun"

ESP32="$("$ROOT/.venv/bin/python" "$DEV/tools/find_esp32.py" 2>/dev/null | tail -1)"
[ -n "$ESP32" ] || ESP32="none"

BUCKET="$(date -u +%Y%m%d)-$(( $(date -u +%H) / 6 ))"

printf 'serie=[%s] byid=[%s] esp32=%s %s build=[%s] flash=[%s] bucket=%s\n' \
  "$SERIE" "$BYID" "$ESP32" "$PHASE" "$BUILD" "$FLASH" "$BUCKET"
