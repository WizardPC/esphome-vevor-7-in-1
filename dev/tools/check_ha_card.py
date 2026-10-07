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
HA_URL = "http://192.168.2.104"
# ANCHOR: entity-id suffix used to find the device-name prefix in the listing. One constant for
# both selecting and trimming the probe, so the two uses cannot diverge. Must match the YAML name.
ANCRAGE = "outdoor_temperature"
# Entity ids Home Assistant did NOT derive from the device name: the owner's utility_meter helpers
# on rain_total. Helpers, not firmware entities — kept OUT of the listing, because the firmware <-> HA
# comparison (step 3) must stay an equality.
EXCEPTIONS_HA = ("rain_hour", "rain_day", "rain_week", "rain_month", "rain_year")

# --------------------------------------------------------------------------- refresh
# The listing is a MEASUREMENT: never derive it, always re-read it. This rewrites it from the live
# instance and is the only thing a device rename needs (then re-run without --refresh).
if "--refresh" in sys.argv:
    import json
    import urllib.request
    from datetime import datetime

    token = (DEV.parent / ".ha_token").read_text(encoding="utf-8").strip()
    request = urllib.request.Request(HA_URL + "/api/states",
                                     headers={"Authorization": "Bearer " + token})
    states = json.load(urllib.request.urlopen(request, timeout=30))
    anchor = next((state["entity_id"] for state in sorted(states, key=lambda s: s["entity_id"])
                   if state["entity_id"].endswith("_" + ANCRAGE)), None)
    if not anchor:
        sys.exit(f"--refresh : aucune entité en « _{ANCRAGE} » dans HA — ancrage à revoir")
    prefix = anchor.split(".", 1)[1][: -(len(ANCRAGE) + 1)]
    ids = sorted(
        state["entity_id"] for state in states
        if state["entity_id"].split(".", 1)[0] in ("sensor", "binary_sensor", "number", "button")
        and state["entity_id"].split(".", 1)[1].startswith(prefix + "_")
        and state["entity_id"].split(".", 1)[1][len(prefix) + 1:] not in EXCEPTIONS_HA
    )
    head = [
        "# Entités réellement exposées par Home Assistant — relevé, pas déduction.",
        "#",
        f"# Source     = API REST de Home Assistant, {HA_URL}/api/states",
        f"# Relevé le  = {datetime.now().strftime('%d/%m/%Y %H:%M')} (heure locale)",
        f"# Préfixe    = {prefix}   (lu, jamais dérivé)",
        "# Rafraîchir = .venv/bin/python dev/tools/check_ha_card.py --refresh",
        "# Vérifier   = .venv/bin/python dev/tools/check_ha_card.py  (étape 5 de run_tests.sh)",
        "#",
        "# Ne figurent PAS ci-dessous, bien qu'attachées au même appareil : les compteurs d'utilité",
        f"# créés par le propriétaire sur rain_total ({', '.join(EXCEPTIONS_HA)} — plateforme mesurée :",
        "# utility_meter). Ce sont des helpers HA, pas des entités du firmware : les inclure ferait",
        "# échouer l'égalité firmware <-> HA de l'étape 3.",
        "#",
        "# L'entity_id n'est pas déductible du firmware : le nom d'appareil se renomme dans Home",
        "# Assistant et renomme tous les entity_id d'un coup. D'où cette liste MESURÉE, et la règle :",
        "# la relire avant de toucher la carte.",
        "#",
        "## Appareil",
        f"# device_prefix: {prefix}",
        "",
        "## Entités",
    ]
    ENTITIES.write_text("\n".join(head + ids) + "\n", encoding="utf-8")
    print(f"--refresh : {len(ids)} entités relevées dans HA, préfixe {prefix} -> {ENTITIES}")
    sys.exit(0)
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
# ANCHOR: entity-id suffix used to find the device-name prefix in the listing. Its value lives at
# the top of this file (the --refresh path needs it before the listing is read). Must match the
# YAML name.
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
# HELPERS: ids the CARD cites that are neither firmware entities nor HA-listing entries — the
# owner's utility_meter counters on rain_total (kept out of the listing for the very same reason,
# see EXCEPTIONS_HA). Declared, never worked around: the two checks below stay equality checks.
HELPERS = sorted(entity for entity in cited
                 if entity.split(".", 1)[1][len(prefix) + 1:] in EXCEPTIONS_HA)
cited = [entity for entity in cited if entity not in HELPERS]
print(f"2. Entités : appareil « {prefix} », {len(reference)} entités relevées dans HA, "
      f"{len(cited)} citées par la carte, {len(HELPERS)} helpers HA déclarés → {HELPERS}")
unknown = [entity for entity in cited if entity not in reference]
check(not unknown, f"les entités citées existent toutes dans le relevé ({unknown or 'aucun écart'})")
unused = sorted(entity for entity in reference if entity not in cited)
print(f"     relevé non cité par la carte (attendu : diag. et commandes) : {len(unused)} → {unused}")

# Negative control of THAT check, before trusting its green: the same extraction, on a copy with
# one deliberately broken id, must fail — and it must fail ON THAT ID, not on the declared HA
# helpers (they are legitimately outside the listing, so they are removed first). A check whose
# failure mode was never exercised is an untested claim.
casse = raw.replace("tx_counter", "tx_couner")
cites_casse = sorted(set(re.findall(
    rf"\b(?:sensor|binary_sensor|text_sensor|number|button)\.{re.escape(prefix)}_[A-Za-z0-9_]+",
    casse)))
inconnus_casse = [entity for entity in cites_casse
                  if entity not in reference and entity not in HELPERS]
check(any("tx_couner" in entity for entity in inconnus_casse),
      f"controle négatif : l'identifiant cassé est bien détecté ({inconnus_casse[:1] or 'NON DÉTECTÉ'})")

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
        # `as_timestamp` : HA l'expose comme fonction ET comme filtre. La vignette « Dernière
        # trame » s'en sert pour afficher l'heure exacte du dernier passage — un horodatage absolu
        # ne dérive pas, contrairement à l'âge, qui est un instantané pris au rendu.
        as_timestamp=lambda when: when.timestamp() if hasattr(when, "timestamp") else 0.0,
    )
    env.filters["timestamp_custom"] = lambda value, fmt="%H:%M:%S", local=True: (
        datetime.fromtimestamp(float(value)).strftime(fmt))
    return str(env.from_string(template).render()).strip()


def trouve_bandeau(racine):
    """Le bandeau de prévision — repéré à son TEXTE, jamais à une position dans la carte."""
    a_voir = list(racine) if isinstance(racine, list) else [racine]
    while a_voir:
        noeud = a_voir.pop(0)
        if isinstance(noeud, dict):
            if "clair" in str(noeud.get("secondary", "")):
                return noeud
            a_voir.extend(noeud.values())
        elif isinstance(noeud, list):
            a_voir.extend(noeud)
    return None


# La carte en service n'affiche pas le bandeau : il vit en option commentée (option G). Les
# scénarios de prévision doivent continuer de tenir cette version-là, et le contrôle doit le dire
# s'il ne trouve plus rien — un scénario qui disparaît en silence ne vaut rien.
bandeau, origine = trouve_bandeau(card), "carte active"
if bandeau is None:
    for bloc in blocks:
        try:
            charge = yaml.safe_load(bloc)
        except Exception:  # noqa: BLE001 - un bloc illisible est déjà signalé par l'étape 4
            continue
        bandeau = trouve_bandeau(charge)
        if bandeau is not None:
            origine = "option commentée (G)"
            break
if bandeau is None:
    sys.exit("5. Bandeau de prévision introuvable — ni dans la carte active, ni dans les options "
             "commentées. Le remettre, ou retirer les scénarios et le dire ici.")
print(f"   (bandeau de prévision testé depuis la version : {origine})")
TEMPLATES = {"état": bandeau["secondary"], "icône": bandeau["icon"], "couleur": bandeau["icon_color"]}
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
print("6. Encarts « Réception » exécutés sur des scénarios (fraîcheur, taux de réception conforme)")


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
# Le taux est trouvé par SON entité, jamais par sa position ni par un ancien nom : la carte a
# changé de mesure le 07/10/2026 (rapport OK/(OK+KO) -> reception_rate, la part des ÉMISSIONS de
# la station réellement décodées).
ENCART_TAUX = encart("reception_rate")
ENTITY_AGE = f"sensor.{prefix}_tx_counter"
ENTITY_TAUX = f"sensor.{prefix}_reception_rate"
ENTITY_RD = f"sensor.{prefix}_reception_window_decoded"
ENTITY_RE = f"sensor.{prefix}_reception_window_emitted"
ENTITY_OK = f"sensor.{prefix}_valid_frames"
ENTITY_KO = f"sensor.{prefix}_rejected_frames"
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


def heure_de(secondes) -> str:
    """L'heure que la carte affiche pour une trame arrivée il y a `secondes` — calculée avec la
    même conversion que le filtre timestamp_custom, donc sans supposer le fuseau du poste."""
    return datetime.fromtimestamp((NOW - timedelta(seconds=secondes)).timestamp()).strftime("%H:%M:%S")


def verdict_fraicheur(secondes, texte: str) -> str:
    """« Trame 1234 à 11:59:58 — Réception normale » : l'horodatage précède le verdict."""
    return f"Trame 1234 à {heure_de(secondes)} — {texte}"


print("   — âge de la dernière trame (référence « TX counter »)")
essai("trame il y a 2 s — réception normale", ENCART_AGE, age_data(2),
      {"primary": "il y a 2 s", "secondary": verdict_fraicheur(2, "Réception normale"),
       "icon": "mdi:clock-check-outline", "icon_color": "green"})
essai("trame il y a 35 s — dernière valeur du vert", ENCART_AGE, age_data(35),
      {"primary": "il y a 35 s", "secondary": verdict_fraicheur(35, "Réception normale"),
       "icon": "mdi:clock-check-outline", "icon_color": "green"})
essai("trame il y a 45 s — une trame manquée", ENCART_AGE, age_data(45),
      {"primary": "il y a 45 s", "secondary": verdict_fraicheur(45, "Trame manquée"),
       "icon": "mdi:clock-alert-outline", "icon_color": "amber"})
essai("trame il y a 61 s — le garde-fou ré-arme la radio", ENCART_AGE, age_data(61),
      {"primary": "il y a 1 min", "secondary": verdict_fraicheur(61, "Silence (ré-armement)"),
       "icon": "mdi:clock-alert-outline", "icon_color": "orange"})
essai("trame il y a 200 s — silence, la carte redémarre", ENCART_AGE, age_data(200),
      {"primary": "il y a 3 min", "secondary": verdict_fraicheur(200, "Silence (reboot)"),
       "icon": "mdi:clock-remove-outline", "icon_color": "red"})
essai("trame il y a 2 h — l'âge passe en heures", ENCART_AGE, age_data(7200),
      {"primary": "il y a 2.0 h", "secondary": verdict_fraicheur(7200, "Silence (reboot)"),
       "icon": "mdi:clock-remove-outline", "icon_color": "red"})
essai("entité absente — « inconnu », jamais « il y a 0 s »", ENCART_AGE, age_data(None),
      {"primary": "inconnu", "secondary": "Carte injoignable, ou entité absente",
       "icon": "mdi:help-circle-outline", "icon_color": "grey"})
essai("entité indisponible — pas de fraîcheur affichée", ENCART_AGE,
      {ENTITY_AGE: State("unavailable", NOW - timedelta(seconds=5))},
      {"primary": "inconnu", "secondary": "Carte injoignable, ou entité absente",
       "icon": "mdi:help-circle-outline", "icon_color": "grey"})


def taux_data(taux: str, rd: str, re_: str, ok: str = "149", ko: str = "50") -> dict:
    """États des cinq entités que la vignette de taux lit."""
    return {ENTITY_TAUX: State(taux), ENTITY_RD: State(rd), ENTITY_RE: State(re_),
            ENTITY_OK: State(ok), ENTITY_KO: State(ko)}


# La vignette est celle du propriétaire : son icône est FIXE (mdi:access-point), et ses mots sont
# les siens — « trames produites par la station », « Indisponibilité », « Analyse... ». Les
# attendus ci-dessous sont donc recopiés de la carte, pas d'une version idéale.
ICONE = "mdi:access-point"
CUMUL = " · cumul 149 / 199"


print("   — taux de réception conforme (« Reception rate » et ses deux termes)")
essai("100 % — aucune émission manquée, 30/30 (relevé du 07/10)", ENCART_TAUX,
      taux_data("100.0", "30", "30"),
      {"primary": "100.0 %",
       "secondary": "30 / 30 trames produites par la station, 30 dernières" + CUMUL,
       "icon": ICONE, "icon_color": "green"})
essai("96,666… % — UNE émission manquée sur 30 (mesuré à 08:53 ce jour-là)", ENCART_TAUX,
      taux_data("96.6666641235352", "29", "30"),
      {"primary": "96.7 %",
       "secondary": "29 / 30 trames produites par la station, 30 dernières" + CUMUL,
       "icon": ICONE, "icon_color": "green"})
essai("75 % — limite basse du vert", ENCART_TAUX, taux_data("75.0", "30", "40"),
      {"primary": "75.0 %",
       "secondary": "30 / 40 trames produites par la station, 30 dernières" + CUMUL,
       "icon": ICONE, "icon_color": "amber"})
essai("69,9 % — sous 70 %, le taux passe au rouge", ENCART_TAUX, taux_data("69.9", "16", "23"),
      {"primary": "69.9 %",
       "secondary": "16 / 23 trames produites par la station, 30 dernières" + CUMUL,
       "icon": ICONE, "icon_color": "red"})
essai("64 % — la nuit du 06-07/10, émetteur tiers actif (mesuré)", ENCART_TAUX,
      taux_data("64.0", "16", "25"),
      {"primary": "64.0 %",
       "secondary": "16 / 25 trames produites par la station, 30 dernières" + CUMUL,
       "icon": ICONE, "icon_color": "red"})
essai("moins de 20 tentatives — le cumul n'est pas affiché", ENCART_TAUX,
      taux_data("100.0", "30", "30", ok="4", ko="1"),
      {"primary": "100.0 %",
       "secondary": "30 / 30 trames produites par la station, 30 dernières",
       "icon": ICONE, "icon_color": "green"})
essai("première mesure impossible (0 émission comptée)", ENCART_TAUX, taux_data("unknown", "0", "0"),
      {"primary": "en attente", "secondary": "Analyse... (deux trames requises)",
       "icon": ICONE, "icon_color": "blue-grey"})
essai("compteurs indisponibles", ENCART_TAUX,
      taux_data("unavailable", "unavailable", "unavailable", "unavailable", "unavailable"),
      {"primary": "en attente", "secondary": "Indisponibilité",
       "icon": ICONE, "icon_color": "blue-grey"})
essai("entités absentes de HA (states() rend « unknown »)", ENCART_TAUX, {},
      {"primary": "en attente", "secondary": "Indisponibilité",
       "icon": ICONE, "icon_color": "blue-grey"})

print()
if failures:
    print(f"{len(failures)} ÉCHEC(S) : {failures}")
    sys.exit(1)
print(f"CONFORME — {len(echos)} contrôles, 0 échec")
