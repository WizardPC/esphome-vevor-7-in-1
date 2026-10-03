#!/usr/bin/env bash
# Flash le firmware, en USB (--device /dev/ttyUSB0) ou en OTA (--device IP).
# Usage: tools/flash.sh [cible] [nom_yaml]
#   tools/flash.sh /dev/ttyUSB0
#   tools/flash.sh 192.168.2.50
#
# Le code retour est toujours celui d'ESPHome ; un marqueur FLASH OK / FLASH FAIL est écrit
# dans logs/last_flash_status.txt (la sortie peut passer par un pipe sans le perdre).
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TARGET="${1:?usage: flash.sh <port_serie|IP> [yaml]}"
YAML="${2:-vevor-7in1}"
mkdir -p "$ROOT/logs"
# Même verrou que build.sh : empêche un flash concurrent du build d'une autre exécution.
exec 9>"$ROOT/build/.build_flash.lock"
flock -w 1500 9 || {
  printf 'FLASH ABANDONNE code=3 verrou occupe (un autre build/flash tourne)\n' | tee "$ROOT/logs/last_flash_status.txt"
  exit 3
}
cd "$ROOT/esphome"
echo "[flash] $YAML -> $TARGET"

# Même surcharge que build.sh : sinon ESPHome téléchargerait la version publiée.
"$ROOT/.venv/bin/esphome" -s vevor_components components run "$YAML.yaml" --device "$TARGET" --no-logs > "$ROOT/logs/last_flash.log" 2>&1
CODE=$?
tail -25 "$ROOT/logs/last_flash.log"

if [ "$CODE" -eq 0 ]; then
  printf 'FLASH OK code=0 cible=%s\n' "$TARGET" | tee "$ROOT/logs/last_flash_status.txt"
  exit 0
fi
printf 'FLASH FAIL code=%s cible=%s (voir logs/last_flash.log)\n' "$CODE" "$TARGET" | tee "$ROOT/logs/last_flash_status.txt"
exit "$CODE"
