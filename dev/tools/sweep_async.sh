#!/usr/bin/env bash
# Balayage de fréquence en mode ASYNCHRONE.
#
# En mode packet, on jugeait un palier au nombre de « paquets » reçus. Ce compteur n'existe plus
# ici : on compte donc les trames réellement EXTRAITES du flux démodulé (préambule + syncword +
# 21 octets), ce qui est un critère bien plus fort — une trame extraite et validée par le
# checksum ne peut pas venir du bruit.
#
# Usage: tools/sweep_async.sh [hôte] [secondes_par_palier] [début_MHz] [fin_MHz] [pas_MHz]
set -uo pipefail
DEV="$(cd "$(dirname "$0")/.." && pwd)"   # dev/ : outils, tests, docs, journaux
ROOT="$(cd "$DEV/.." && pwd)"            # racine du dépôt : esphome/ y vit, et rien d'autre
HOST="${1:-172.16.0.205}"
DWELL="${2:-25}"
START="${3:-867.80}"
STOP="${4:-868.60}"
STEP="${5:-0.05}"
mkdir -p "$DEV/logs"

echo "# balayage asynchrone de $START à $STOP MHz par pas de $STEP, $DWELL s par palier"
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
  printf '%9s MHz   extraites=%-4s RAW=%-4s VALIDES=%-4s\n' "$f" "$EXT" "$RAW" "$OK"
  f=$(awk "BEGIN{printf \"%.2f\", $f + $STEP}")
done
echo "# fin du balayage — un palier avec des VALIDES > 0 est le bon"
