#!/usr/bin/env python3
"""Offline check of docs/ha-card.yaml — the project's Lovelace card.

Without Home Assistant or hardware, it verifies:

  1. the YAML loads and has the shape of a Lovelace card;
  2. every `entity_id` cited by the card — including commented-out options, which will be
     uncommented one day — exists in `dev/docs/ha-entities.txt`, HA's listing (never
     reconstructed: the entity_id depends on the device name, which is renamed in HA);
  3. that listing holds exactly the entities `esphome/vevor-7in1.yaml` declares — the
     EXCEPTIONS below included, so a fresh divergence still fails;
  4. no identifier of the old project remains in an active line (`jardin_vevor_weather_station`,
     or `esp32_weather_*`);
  5. the three banner templates (state, icon, colour) run on numeric scenarios and match the
     verdict expected by `docs/forecast-rules.md`, including the honest "night", "not enough
     measurements" and "rain sensor unavailable" cases;
  6. the two « Réception » cards (age of the last frame, valid-frame ratio) run on scenarios:
     fresh frame, missed frame, silent radio, unavailable entity, counters too small for a
     percentage to mean anything, and duplicates unavailable.

Usage:   .venv/bin/python tools/check_ha_card.py
Exit:    0 if all conforms, 1 otherwise (each discrepancy is printed).
"""

from __future__ import annotations

import math
import re
import sys
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    import yaml
    from jinja2 import Environment, Undefined
except ImportError as exc:  # pragma: no cover - environment dependency
    sys.exit(f"dépendance manquante ({exc}) — lancer avec .venv/bin/python")

DEV = Path(__file__).resolve().parent.parent   # dev/
ROOT = DEV.parent                               # repo root
CARD = DEV / "docs" / "ha-card.yaml"
ENTITIES = DEV / "docs" / "ha-entities.txt"
FIRMWARE = ROOT / "esphome" / "vevor-7in1.yaml"
NOW = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)

echos: list[str] = []
failures: list[str] = []


def check(condition: bool, message: str) -> bool:
    (echos if condition else failures).append(message)
    print(("  OK   " if condition else "  ÉCHEC ") + message)
    return condition


def slugify(value: str) -> str:
    """HA/ESPHome transliteration ("Outdoor temperature" -> outdoor_temperature)."""
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


# --------------------------------------------------------------------------- 1
raw = CARD.read_text(encoding="utf-8")
try:
    card = yaml.safe_load(raw)
    assert isinstance(card, dict) and "cards" in card
    print(f"1. YAML : carte '{card['type']}' chargée, {len(card['cards'])} cartes de premier niveau")
    echos.append("yaml")
except Exception as exc:
    sys.exit(f"1. YAML invalide : {exc}")

# --------------------------------------------------------------------------- 2
reference = {
    line.split("#")[0].strip()
    for line in ENTITIES.read_text(encoding="utf-8").splitlines()
    if line.split("#")[0].strip()
}
# ANCHOR: entity-id suffix used to find the device-name prefix in the listing. One constant for
# both selecting and trimming the probe, so the two uses cannot diverge. Must match the YAML name.
ANCRAGE = "outdoor_temperature"
probe = next((entity for entity in sorted(reference) if entity.endswith("_" + ANCRAGE)), None)
if not probe:
    sys.exit(f"2. docs/ha-entities.txt : aucune entité en « _{ANCRAGE} » — impossible d'en déduire "
             "le préfixe d'appareil (mettre ANCRAGE à jour si le nom de l'entité a changé)")
prefix = probe.split(".", 1)[1][: -(len(ANCRAGE) + 1)]

# EXCEPTIONS: entity ids HA did NOT derive from the device name, measured on the listing.
# Keyed by the firmware entity name, slugified. An entry here is a measurement, not a workaround:
# the cross-check below stays an equality check, exception included, so a fresh divergence still
# fails. EMPTY since 05/10/2026 — the old ESPHome node was cleaned up in HA and Illuminance came
# back under the device prefix (see dev/docs/ha-entities.txt); the shape is kept so a future
# exception has a documented home.
#     EXCEPTIONS = {"illuminance": "sensor.esp32_weather_illuminance"}
EXCEPTIONS: dict[str, str] = {}

cited = sorted(set(re.findall(
    rf"\b(?:sensor|binary_sensor|text_sensor|number|button)\.{re.escape(prefix)}_[A-Za-z0-9_]+", raw))
    | {entity for entity in EXCEPTIONS.values() if entity in raw})
print(f"2. Entités : appareil « {prefix} », {len(reference)} entités relevées dans HA, "
      f"{len(cited)} citées par la carte")
unknown = [entity for entity in cited if entity not in reference]
check(not unknown, f"les entités citées existent toutes dans le relevé ({unknown or 'aucun écart'})")
unused = sorted(entity for entity in reference if entity not in cited)
print(f"     relevé non cité par la carte (attendu : diag. et commandes) : {len(unused)} → {unused}")

# --------------------------------------------------------------------------- 3
firmware = FIRMWARE.read_text(encoding="utf-8")
declared: set[str] = set()
domain = None
for line in firmware.splitlines():
    head = re.match(r"^(\w+):\s*$", line)
    if head and head.group(1) in ("sensor", "binary_sensor", "text_sensor", "number", "button"):
        domain = head.group(1)
    name = re.match(r'\s+name:\s+"([^"]+)"', line)
    if name and domain:
        # HA exposes ESPHome text_sensor in the `sensor` domain (seen in the listing).
        ha_domain = "sensor" if domain == "text_sensor" else domain
        slug = slugify(name.group(1))
        declared.add(EXCEPTIONS.get(slug, f"{ha_domain}.{prefix}_{slug}"))

only_firmware = sorted(declared - reference)
only_ha = sorted(reference - declared)
print(f"3. Accord firmware / HA : {len(declared)} entités déclarées par esphome/vevor-7in1.yaml, "
      f"{len(reference)} relevées dans HA")
check(not only_firmware and not only_ha,
      f"le relevé correspond au firmware (firmware seul : {only_firmware or 'aucune'} | "
      f"HA seul : {only_ha or 'aucune'})")

# --------------------------------------------------------------------------- 4
active = "\n".join(
    line for line in raw.splitlines()
    if line.strip() and not line.lstrip().startswith("#")
)
# The current prefix itself contains "jardin_vevor": match the OLD project's patterns whole.
# No `esp32_weather_*` id exists any more — the Illuminance exception went away on 05/10/2026
# (dev/docs/ha-entities.txt), so the lookahead that used to spare it is gone as well.
legacy = [line.strip() for line in active.splitlines()
          if re.search(r"jardin_vevor_weather_station|esp32_weather_", line)]
check(not legacy, f"aucun identifiant de l'ancien projet dans les lignes actives ({legacy or 'aucun'})")

# Option blocks live in comments and will be uncommented one day, so check they parse as YAML.
blocks: list[str] = []
cur: list[str] = []
base: int | None = None
for line in raw.splitlines():
    starter = re.match(r"^#(\s*)- ", line) or re.match(r"^#(\s*)[A-Za-z_][A-Za-z0-9_]*:\s*$", line)
    if starter and base is None:
        base = len(starter.group(1))
        cur = [line[1:]]
        continue
    if base is None:
        continue
    body = line[1:] if line.startswith("#") else None
    indent = len(body) - len(body.lstrip()) if body is not None else None
    if line.strip() == "":
        cur.append("")
    elif body is not None and indent is not None and indent >= base:
        cur.append(body)
    else:
        blocks.append("\n".join(cur).strip("\n"))
        cur, base = [], None
if base is not None:
    blocks.append("\n".join(cur).strip("\n"))

broken: list[str] = []
for block in blocks:
    try:
        yaml.safe_load(block)
    except Exception as exc:  # noqa: BLE001 - report the faulty text
        broken.append(f"{exc} → {block.splitlines()[0][:60]}")
check(not broken, f"les {len(blocks)} blocs d'options commentés se chargent comme du YAML "
                  f"({broken or 'aucun écart'})")


# --------------------------------------------------------------------------- 5
class State:
    def __init__(self, state: str, last_changed: datetime | None = None):
        self.state, self.last_changed = state, last_changed


class States:
    """`states('x.y')` AND `states.sensor.x` (state object, for last_changed)."""

    def __init__(self, data: dict):
        self._data = data

    def __call__(self, entity_id: str, default: str = "unknown") -> str:
        found = self._data.get(entity_id)
        return found.state if found else default

    def __getattr__(self, dom: str):
        if dom.startswith("_"):
            raise AttributeError(dom)

        data = object.__getattribute__(self, "_data")  # avoid recursion through __getattr__

        class Domain:
            def __getattr__(self, obj: str):
                if obj.startswith("_"):
                    raise AttributeError(obj)
                return data.get(f"{dom}.{obj}")

        return Domain()


def render(template: str, data: dict) -> str:
    """Render a template with the HA filters and functions the card uses."""
    states = States(data)
    env = Environment(undefined=Undefined)
    env.filters["sin"] = lambda v, default=0: math.sin(math.radians(float(v)))
    env.globals.update(
        states=states,
        state_attr=lambda entity, attr: {"elevation": data["_sun_elevation"]}.get(attr)
        if entity == "sun.sun" else None,
        is_state=lambda entity, value: states(entity) == value,
        now=lambda: NOW,
        relative_time=lambda when: f"{int((NOW - when).total_seconds() // 60)} minutes",
    )
    return str(env.from_string(template).render()).strip()


header = card["cards"][0]
TEMPLATES = {"état": header["secondary"], "icône": header["icon"], "couleur": header["icon_color"]}
clear_40 = 133800 * math.sin(math.radians(40)) ** 1.15  # clear-sky reference at 40 deg (sec. 6)
ENTITY = {
    "temp": f"sensor.{prefix}_outdoor_temperature",
    "rafale": f"sensor.{prefix}_wind_gust",
    "lux": EXCEPTIONS.get("illuminance", f"sensor.{prefix}_illuminance"),
    "pluie": f"sensor.{prefix}_rain_total",
}


def scenario(label, *, t, lux, elev, rafale, pluie, il_y_a, attendu, icone, couleur, horizon="above_horizon"):
    data = {
        ENTITY["temp"]: State(str(t)),
        ENTITY["rafale"]: State(str(rafale)),
        ENTITY["lux"]: State(str(lux)),
        ENTITY["pluie"]: State(str(pluie), NOW - timedelta(seconds=il_y_a)),
        "sun.sun": State(horizon),
        "_sun_elevation": elev,
    }
    got = {k: render(v, data) for k, v in TEMPLATES.items()}
    ok = (
        got["état"].startswith(attendu)
        and got["icône"] == icone
        and got["couleur"] == couleur
    )
    print(f"   {'OK  ' if ok else 'ÉCHEC'} {label}")
    print(f"        → {got['état']}  [{got['icône']} / {got['couleur']}]")
    if not ok:
        print(f"        attendu : {attendu} / {icone} / {couleur}")
        failures.append(label)
    else:
        echos.append(label)
    return ok


print("5. Modèles du bandeau exécutés sur des scénarios (verdicts de docs/forecast-rules.md)")
scenario("pluie en cours, 1,4 °C", t=1.4, lux=1000, elev=40, rafale=18, pluie=59.2, il_y_a=180,
         attendu="Pluvieux", icone="mdi:weather-rainy", couleur="blue")
scenario("pluie et gel — alerte verglas du manuel (< 1 °C)", t=0.4, lux=1000, elev=40, rafale=12,
         pluie=59.2, il_y_a=300, attendu="Neigeux", icone="mdi:weather-snowy", couleur="cyan")
scenario("pluie et rafales 52 km/h", t=8.0, lux=1000, elev=40, rafale=52, pluie=60.1, il_y_a=60,
         attendu="Orageux", icone="mdi:weather-lightning-rainy", couleur="deep-purple")
scenario("sec, 85 % de la référence ciel clair (≥ 0,70)", t=21.0, lux=round(0.85 * clear_40), elev=40,
         rafale=15, pluie=59.2, il_y_a=3600, attendu="Dégagé", icone="mdi:weather-sunny", couleur="amber")
scenario("sec, 50 % de la référence (≥ 0,35)", t=21.0, lux=round(0.50 * clear_40), elev=40,
         rafale=15, pluie=59.2, il_y_a=3600, attendu="Partiellement",
         icone="mdi:weather-partly-cloudy", couleur="orange")
scenario("sec, 10 % de la référence", t=21.0, lux=round(0.10 * clear_40), elev=40, rafale=15,
         pluie=59.2, il_y_a=3600, attendu="Nuageux", icone="mdi:weather-cloudy", couleur="blue-grey")
scenario("nuit, soleil à -12,3° — réponse honnête, pas d'estimation", t=14.0, lux=0, elev=-12.3,
         rafale=8, pluie=59.2, il_y_a=3600, attendu="Nuit", icone="mdi:weather-night",
         couleur="indigo", horizon="below_horizon")
scenario("capteur de pluie indisponible — pas de pluie annoncée", t=21.0, lux=round(0.85 * clear_40),
         elev=40, rafale=15, pluie="unavailable", il_y_a=60, attendu="Dégagé",
         icone="mdi:weather-sunny", couleur="amber")
scenario("dernière bascule il y a 25 min — la fenêtre de 20 min est close", t=21.0,
         lux=round(0.85 * clear_40), elev=40, rafale=15, pluie=59.2, il_y_a=1500, attendu="Dégagé",
         icone="mdi:weather-sunny", couleur="amber")
# Signalé le 03/10 : le bandeau annonçait « Pluvieux » sans pluie. Le compteur remis à zéro
# (démarrage, changement de piles, ré-ajout de l'entité dans HA) rendait last_changed récent.
scenario("compteur remis à zéro (0,0 mm) modifié il y a 1 min — pas de pluie", t=21.0,
         lux=round(0.85 * clear_40), elev=40, rafale=15, pluie=0.0, il_y_a=60, attendu="Dégagé",
         icone="mdi:weather-sunny", couleur="amber")
# Limite de RÉSOLUTION assumée du pluviomètre (0,233 mm par bascule), pas un défaut : avec ce
# compteur, une bascule isolée et une bruine réelle sont indistinguables. C'est ce que règle
# l'option B de la carte (seuil de débit), au prix d'un écart affiché au tableau §5.
scenario("UNE bascule isolée (0,233 mm) il y a 3 min — classée « Pluvieux » par la règle §4",
         t=21.0, lux=round(0.85 * clear_40), elev=40, rafale=15, pluie=0.233, il_y_a=180,
         attendu="Pluvieux", icone="mdi:weather-rainy", couleur="blue")
scenario("soleil rasant, référence < 1 000 lx — le rapport n'a plus de sens", t=21.0, lux=600,
         elev=0.5, rafale=15, pluie=59.2, il_y_a=3600, attendu="Indéterminé",
         icone="mdi:weather-cloudy-alert", couleur="grey")

# --------------------------------------------------------------------------- 6
# Les encarts « Réception » sont trouvés par leur ENTITÉ, jamais par leur position : réordonner
# la carte ne doit pas pouvoir rendre ce contrôle muet. Les modèles testés sont les chaînes
# exactes extraites du YAML, exécutées avec les mêmes filtres Jinja que HA (section 5).
print()
print("6. Encarts « Réception » exécutés sur des scénarios (fraîcheur, taux de trames valides)")


def encart(needle: str) -> dict:
    """Le mushroom-template-card dont `entity` contient `needle` — exactement un attendu."""
    found: list[dict] = []

    def walk(node) -> None:
        if isinstance(node, dict):
            if (isinstance(node.get("entity"), str) and needle in node["entity"]
                    and "primary" in node and "secondary" in node):
                found.append(node)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(card)
    if len(found) != 1:
        sys.exit(f"6. {len(found)} encart(s) citant « {needle} » — exactement 1 attendu")
    return found[0]


ENCART_AGE = encart("tx_counter")
ENCART_TAUX = encart("valid_frames")
ENTITY_AGE = f"sensor.{prefix}_tx_counter"
ENTITY_OK = f"sensor.{prefix}_valid_frames"
ENTITY_KO = f"sensor.{prefix}_rejected_frames"
ENTITY_DUP = f"sensor.{prefix}_duplicates_ignored"
CHAMPS = ("primary", "secondary", "icon", "icon_color")


def essai(label: str, entete: dict, data: dict, attendu: dict) -> None:
    got = {champ: render(entete[champ], data) for champ in CHAMPS}
    ok = all(got[champ] == attendu[champ] for champ in CHAMPS)
    print(f"   {'OK  ' if ok else 'ÉCHEC'} {label}")
    print(f"        → {got['primary']} | {got['secondary']}  "
          f"[{got['icon']} / {got['icon_color']}]")
    if ok:
        echos.append(label)
        return
    print(f"        écart (obtenu, attendu) : "
          f"{ {c: (got[c], attendu[c]) for c in CHAMPS if got[c] != attendu[c]} }")
    failures.append(label)


def age_data(secondes, etat: str = "1234.0") -> dict:
    """Jeu d'états pour l'encart de fraîcheur. `None` = entité absente (states.sensor.x → None)."""
    if secondes is None:
        return {ENTITY_AGE: None}
    return {ENTITY_AGE: State(etat, NOW - timedelta(seconds=secondes))}


print("   — âge de la dernière trame (référence « TX counter »)")
essai("trame il y a 2 s — réception normale", ENCART_AGE, age_data(2),
      {"primary": "il y a 2 s", "secondary": "Réception normale — 1 trame toutes les 20 s",
       "icon": "mdi:clock-check-outline", "icon_color": "green"})
essai("trame il y a 35 s — dernière valeur du vert", ENCART_AGE, age_data(35),
      {"primary": "il y a 35 s", "secondary": "Réception normale — 1 trame toutes les 20 s",
       "icon": "mdi:clock-check-outline", "icon_color": "green"})
essai("trame il y a 45 s — une trame manquée", ENCART_AGE, age_data(45),
      {"primary": "il y a 45 s", "secondary": "Une trame manquée",
       "icon": "mdi:clock-alert-outline", "icon_color": "amber"})
essai("trame il y a 61 s — le garde-fou ré-arme la radio", ENCART_AGE, age_data(61),
      {"primary": "il y a 1 min", "secondary": "Silence radio — ré-armement demandé à 60 s",
       "icon": "mdi:clock-alert-outline", "icon_color": "orange"})
essai("trame il y a 200 s — silence, la carte redémarre", ENCART_AGE, age_data(200),
      {"primary": "il y a 3 min", "secondary": "Silence radio — la carte redémarre à 180 s",
       "icon": "mdi:clock-remove-outline", "icon_color": "red"})
essai("trame il y a 2 h — l'âge passe en heures", ENCART_AGE, age_data(7200),
      {"primary": "il y a 2.0 h", "secondary": "Silence radio — la carte redémarre à 180 s",
       "icon": "mdi:clock-remove-outline", "icon_color": "red"})
essai("entité absente — « inconnu », jamais « il y a 0 s »", ENCART_AGE, age_data(None),
      {"primary": "inconnu", "secondary": "Carte injoignable, ou entité absente",
       "icon": "mdi:help-circle-outline", "icon_color": "grey"})
essai("entité indisponible — pas de fraîcheur affichée", ENCART_AGE,
      {ENTITY_AGE: State("unavailable", NOW - timedelta(seconds=5))},
      {"primary": "inconnu", "secondary": "Carte injoignable, ou entité absente",
       "icon": "mdi:help-circle-outline", "icon_color": "grey"})


def taux_data(ok: str, ko: str, doublons: str = "0") -> dict:
    return {ENTITY_OK: State(ok), ENTITY_KO: State(ko), ENTITY_DUP: State(doublons)}


print("   — taux de trames valides (« Valid frames » / « Rejected frames »)")
essai("37 valides / 21 rejetés — le relevé du 05/10/2026", ENCART_TAUX,
      taux_data("37", "21", "34"),
      {"primary": "63.8 %",
       "secondary": "OK 37 · KO 21 (36.2 %) · doublons 34 — depuis le démarrage de la carte",
       "icon": "mdi:check-circle-outline", "icon_color": "green"})
essai("30 % pile — limite basse du vert", ENCART_TAUX, taux_data("30", "70"),
      {"primary": "30.0 %",
       "secondary": "OK 30 · KO 70 (70.0 %) · doublons 0 — depuis le démarrage de la carte",
       "icon": "mdi:check-circle-outline", "icon_color": "green"})
essai("15 % pile — limite basse de l'ambre", ENCART_TAUX, taux_data("15", "85"),
      {"primary": "15.0 %",
       "secondary": "OK 15 · KO 85 (85.0 %) · doublons 0 — depuis le démarrage de la carte",
       "icon": "mdi:alert-circle-outline", "icon_color": "amber"})
essai("9,1 % — sous 15 %, le taux passe au rouge", ENCART_TAUX, taux_data("5", "50"),
      {"primary": "9.1 %",
       "secondary": "OK 5 · KO 50 (90.9 %) · doublons 0 — depuis le démarrage de la carte",
       "icon": "mdi:close-circle-outline", "icon_color": "red"})
essai("4 trames — le taux n'a pas encore de sens", ENCART_TAUX, taux_data("3", "1"),
      {"primary": "en attente",
       "secondary": "Moins de 20 trames depuis le démarrage — le taux n'a pas encore de sens",
       "icon": "mdi:help-circle-outline", "icon_color": "blue-grey"})
essai("compteurs indisponibles", ENCART_TAUX,
      taux_data("unavailable", "unavailable", "unavailable"),
      {"primary": "en attente", "secondary": "Compteurs indisponibles",
       "icon": "mdi:help-circle-outline", "icon_color": "blue-grey"})
essai("entités absentes de HA (states() rend « unknown »)", ENCART_TAUX, {},
      {"primary": "en attente", "secondary": "Compteurs indisponibles",
       "icon": "mdi:help-circle-outline", "icon_color": "blue-grey"})
essai("doublons indisponibles — affichés « ? » sans casser le taux", ENCART_TAUX,
      taux_data("100", "2", "unavailable"),
      {"primary": "98.0 %",
       "secondary": "OK 100 · KO 2 (2.0 %) · doublons ? — depuis le démarrage de la carte",
       "icon": "mdi:check-circle-outline", "icon_color": "green"})

print()
if failures:
    print(f"{len(failures)} ÉCHEC(S) : {failures}")
    sys.exit(1)
print(f"CONFORME — {len(echos)} contrôles, 0 échec")
