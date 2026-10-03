#!/usr/bin/env bash
# Empreinte d'état déterministe pour la boucle autonome.
#
# Le planificateur compare la sortie de ce script d'un tick à l'autre :
#   - sortie IDENTIQUE  -> l'agent n'est pas lancé du tout (aucun coût, aucun message) ;
#   - sortie DIFFÉRENTE -> l'agent est réveillé avec le diff et fait une itération.
#
# C'est ce qui rend la boucle silencieuse tant qu'il n'y a rien à faire, tout en la réveillant
# dès qu'un port série apparaît, qu'un ESP32 devient joignable, ou que l'agent a fait avancer
# la phase du projet (fichier state/PHASE).
#
# Ne JAMAIS mettre d'horodatage fin ici (sinon l'empreinte change à chaque tick) — d'où le
# « bucket » de 6 h qui ne sert qu'à garantir un réveil de contrôle 4 fois par jour.
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
