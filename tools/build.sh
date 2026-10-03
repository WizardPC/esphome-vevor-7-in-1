#!/usr/bin/env bash
# Compile le firmware. Usage: tools/build.sh [nom_yaml_sans_extension]
#
# Le code retour est TOUJOURS celui d'ESPHome (jamais celui de tee/tail) et un marqueur
# explicite est écrit dans build/last_status.txt : la boucle autonome ne peut donc pas
# confondre un échec avec un succès quand la sortie passe par un pipe.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
YAML="${1:-vevor-7in1}"
mkdir -p "$ROOT/build" "$ROOT/logs"
# Verrou partagé avec flash.sh : la boucle autonome et une session interactive peuvent lancer
# un build/flash en même temps sur le même dossier de build. Ça s'est produit le 30/09 et ça a
# fait réécrire le YAML sous les pieds de l'autre exécution. Le verrou rend la collision
# impossible : le second attend, puis abandonne proprement avec un statut explicite.
exec 9>"$ROOT/build/.build_flash.lock"
flock -w 1500 9 || {
  printf 'BUILD ABANDONNE code=3 verrou occupe (un autre build/flash tourne)\n' | tee "$ROOT/build/last_status.txt"
  exit 3
}
cd "$ROOT/esphome"
echo "[build] $YAML"

# Le YAML pointe par défaut sur le dépôt public (github://) : ici on compile l'arbre LOCAL.
"$ROOT/.venv/bin/esphome" -s vevor_components components compile "$YAML.yaml" > "$ROOT/build/last_compile.log" 2>&1
CODE=$?
tail -20 "$ROOT/build/last_compile.log"

BIN="$ROOT/esphome/.esphome/build/$YAML/build/firmware.ota.bin"
if [ "$CODE" -eq 0 ] && [ -f "$BIN" ]; then
  printf 'BUILD OK code=0 binaire=%s taille=%s octets\n' "$BIN" "$(stat -c %s "$BIN")" | tee "$ROOT/build/last_status.txt"
  exit 0
fi
printf 'BUILD FAIL code=%s (voir build/last_compile.log)\n' "$CODE" | tee "$ROOT/build/last_status.txt"
exit "$CODE"
