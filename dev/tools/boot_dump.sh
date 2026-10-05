#!/usr/bin/env bash
# Reads the boot dump of an ESPHome board: the native API has no history, so seeing a
# `dump_config()` requires being connected BEFORE boot. Chains short reconnecting captures,
# reflashes over OTA, then prints the configuration lines found.
#
# Usage: tools/boot_dump.sh [--host IP] [--rounds N] [--seconds S] [--no-flash]
set -uo pipefail
DEV="$(cd "$(dirname "$0")/.." && pwd)"   # dev/: tools, tests, docs, logs
ROOT="$(cd "$DEV/.." && pwd)"            # repo root: esphome/ lives here, and nothing else
HOST=<ip-de-la-carte>
ROUNDS=6
SEC=25
FLASH=1
while [ $# -gt 0 ]; do
  case "$1" in
    --host) HOST="$2"; shift 2 ;;
    --rounds) ROUNDS="$2"; shift 2 ;;
    --seconds) SEC="$2"; shift 2 ;;
    --no-flash) FLASH=0; shift ;;
    *) echo "option inconnue: $1" >&2; exit 2 ;;
  esac
done

rm -f "$ROOT"/logs/bootdump_*.log
(
  for i in $(seq 1 "$ROUNDS"); do
    "$ROOT/.venv/bin/python" "$DEV/tools/capture_logs.py" --host "$HOST" --seconds "$SEC" \
      --out "$DEV/logs/bootdump_$i.log" >/dev/null 2>&1 || true
  done
) &
LOOP=$!

if [ "$FLASH" -eq 1 ]; then
  sleep 6
  if "$DEV/tools/flash.sh" "$HOST" >/dev/null 2>&1; then
    echo "FLASH OK (OTA)"
  else
    echo "FLASH ECHEC (voir logs/last_flash.log)"
  fi
fi

wait "$LOOP"
echo "=== lignes de configuration trouvées ==="
grep -ah "CC1101:\|Chip ID\|Frequency:\|Channel:\|Modulation\|Symbol Rate\|Filter Bandwidth\|Output Power\|CS Pin\|SPI bus\|CLK Pin\|SDI Pin\|SDO Pin\|Pin: GPIO\|Filter out\|Signal is done\|Receive symbols\|RMT symbols\|Extracteur de trames\|période bit\|polarité\|Over-The-Air\|Encryption\|Failed to enter RX\|PLL\|calibrat\|V7IN1 BOOT\|Successfully" \
  "$ROOT"/logs/bootdump_*.log 2>/dev/null | sed 's/^\[[0-9:]*\] //' | sort -u
