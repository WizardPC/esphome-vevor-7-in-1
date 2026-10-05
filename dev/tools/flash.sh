#!/usr/bin/env bash
# Flashes the firmware, over USB (--device /dev/ttyUSB0) or OTA (--device IP).
# Usage: tools/flash.sh [target] [yaml_name]
#   tools/flash.sh /dev/ttyUSB0
#   tools/flash.sh <board-ip>
#
# The return code is always ESPHome's; a FLASH OK / FLASH FAIL marker is written to
# logs/last_flash_status.txt (the output can go through a pipe without losing it).
set -uo pipefail
DEV="$(cd "$(dirname "$0")/.." && pwd)"   # dev/: tools, tests, docs, logs
ROOT="$(cd "$DEV/.." && pwd)"            # repo root: esphome/ lives here, and nothing else
TARGET="${1:?usage: flash.sh <port_serie|IP> [yaml]}"
YAML="${2:-vevor-7in1}"
mkdir -p "$DEV/logs"
# Same lock as build.sh: prevents a flash concurrent with another run's build.
exec 9>"$DEV/build/.build_flash.lock"
flock -w 1500 9 || {
  printf 'FLASH ABANDONNE code=3 verrou occupe (un autre build/flash tourne)\n' | tee "$DEV/logs/last_flash_status.txt"
  exit 3
}
cd "$ROOT/esphome"
echo "[flash] $YAML -> $TARGET"

# Same override as build.sh: otherwise ESPHome would download the published version.
"$ROOT/.venv/bin/esphome" -s vevor_components components run "$YAML.yaml" --device "$TARGET" --no-logs > "$DEV/logs/last_flash.log" 2>&1
CODE=$?
tail -25 "$DEV/logs/last_flash.log"

if [ "$CODE" -eq 0 ]; then
  printf 'FLASH OK code=0 cible=%s\n' "$TARGET" | tee "$DEV/logs/last_flash_status.txt"
  exit 0
fi
printf 'FLASH FAIL code=%s cible=%s (voir logs/last_flash.log)\n' "$CODE" "$TARGET" | tee "$DEV/logs/last_flash_status.txt"
exit "$CODE"
