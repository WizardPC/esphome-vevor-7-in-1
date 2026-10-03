#!/usr/bin/env bash
# Construit un binaire de comparaison depuis les sources ACTUELLES du dépôt.
#
#   tools/build_variant.sh prod      -> notre pilote (esphome/components/cc1101)
#   tools/build_variant.sh origine   -> pilote d'origine ESPHome, YAML identique
#
# Pourquoi un script : le binaire figé dans build/variants/ doit correspondre aux sources
# du moment, sinon l'A/B compare autre chose que ce qu'on croit. La seule différence entre
# les deux binaires est le CONTENU du pilote : le YAML, le composant de décodage, le
# garde-fou et les réglages radio sont identiques.
#
# Usage : tools/build_variant.sh <prod|origine> [sortie.ota.bin]
set -euo pipefail

RACINE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$RACINE"

VARIANTE="${1:-}"
case "$VARIANTE" in
  prod|origine) ;;
  *) echo "usage : tools/build_variant.sh <prod|origine> [sortie.ota.bin]" >&2; exit 2 ;;
esac

PILOTE="$RACINE/esphome/components/cc1101"
SAUVEGARDE="$RACINE/build/.cc1101_notre"
SORTIE="${2:-$RACINE/build/variants/nous_$([ "$VARIANTE" = prod ] && echo prod || echo pilote_origine).ota.bin}"
OFFICIEL="${VEVOR_CC1101_OFFICIEL:-/home/hermes/projets/_temoins/venv-090/lib/python3.13/site-packages/esphome/components/cc1101}"

remettre_notre_pilote() {
  if [ -d "$SAUVEGARDE" ]; then
    rm -rf "$PILOTE"
    mv "$SAUVEGARDE" "$PILOTE"
    echo "pilote local rétabli"
  fi
}
trap remettre_notre_pilote EXIT

if [ "$VARIANTE" = origine ]; then
  [ -d "$OFFICIEL" ] || { echo "pilote officiel introuvable : $OFFICIEL" >&2; exit 2; }
  rm -rf "$SAUVEGARDE"
  cp -r "$PILOTE" "$SAUVEGARDE"
  # Copie du pilote officiel SANS le dossier __pycache__ (sinon l'ancien bytecode traîne).
  rm -rf "$PILOTE"
  mkdir -p "$PILOTE"
  cp -r "$OFFICIEL"/. "$PILOTE"/
  rm -rf "$PILOTE/__pycache__"
  echo "pilote d'origine ESPHome installé (depuis $OFFICIEL)"
else
  echo "pilote local (esphome/components/cc1101) conservé"
fi

echo "=== compilation ($VARIANTE) ==="
tools/build.sh > "build/last_build_$VARIANTE.log" 2>&1
grep -aE "BUILD OK|BUILD FAIL" "build/last_build_$VARIANTE.log" | tail -1

BIN="esphome/.esphome/build/vevor-7in1/build/firmware.ota.bin"
mkdir -p "$(dirname "$SORTIE")"
cp -f "$BIN" "$SORTIE"
echo "binaire figé : $SORTIE"
echo "taille       : $(stat -c%s "$SORTIE") octets"
echo "md5          : $(md5sum "$SORTIE" | cut -c1-8)"
