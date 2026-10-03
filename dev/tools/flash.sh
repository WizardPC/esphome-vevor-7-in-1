#!/usr/bin/env bash
# Flash le firmware, en USB (--device /dev/ttyUSB0) ou en OTA (--device IP).
# Usage: tools/flash.sh [cible] [nom_yaml]
#   tools/flash.sh /dev/ttyUSB0
#   tools/flash.sh <ip-de-la-carte>
#
# Le code retour est toujours celui d'ESPHome ; un marqueur FLASH OK / FLASH FAIL est écrit
# dans logs/last_flash_status.txt (la sortie peut passer par un pipe sans le perdre).
set -uo pipefail
DEV="$(cd "$(dirname "$0")/.." && pwd)"   # dev/ : outils, tests, docs, journaux
ROOT="$(cd "$DEV/.." && pwd)"            # racine du dépôt : esphome/ y vit, et rien d'autre
TARGET="${1:?usage: flash.sh <port_serie|IP> [yaml]}"
YAML="${2:-vevor-7in1}"
mkdir -p "$DEV/logs"
# Même verrou que build.sh : empêche un flash concurrent du build d'une autre exécution.
exec 9>"$DEV/build/.build_flash.lock"
flock -w 1500 9 || {
  printf 'FLASH ABANDONNE code=3 verrou occupe (un autre build/flash tourne)\n' | tee "$DEV/logs/last_flash_status.txt"
  exit 3
}
cd "$ROOT/esphome"
echo "[flash] $YAML -> $TARGET"

# Même surcharge que build.sh : sinon ESPHome téléchargerait la version publiée.
"$ROOT/.venv/bin/esphome" -s vevor_components components run "$YAML.yaml" --device "$TARGET" --no-logs > "$DEV/logs/last_flash.log" 2>&1
CODE=$?
tail -25 "$DEV/logs/last_flash.log"

if [ "$CODE" -eq 0 ]; then
  printf 'FLASH OK code=0 cible=%s\n' "$TARGET" | tee "$DEV/logs/last_flash_status.txt"
  exit 0
fi
printf 'FLASH FAIL code=%s cible=%s (voir logs/last_flash.log)\n' "$CODE" "$TARGET" | tee "$DEV/logs/last_flash_status.txt"
exit "$CODE"
