#!/usr/bin/env python3
"""Contrôle hors ligne de docs/ha-card.yaml — la carte Lovelace du projet.

Ce que ce script vérifie, sans Home Assistant et sans matériel :

  1. le YAML se charge, et il a la forme d'une carte Lovelace ;
  2. chaque `entity_id` cité dans les lignes actives existe bien dans
     `esphome/vevor-7in1.yaml` (entity_id = translittération de
     « <friendly_name> <nom de l'entité> », règle documentée par HA) : la carte ne
     pointe donc aucune entité qui n'existe pas ;
  3. aucun identifiant de l'ancien projet (`esp32_weather`, `jardin_vevor`) ne
     subsiste dans une ligne active ;
  4. les trois modèles du bandeau (état, icône, couleur) sont réellement exécutés
     sur des scénarios chiffrés et comparés au verdict attendu par
     `docs/forecast-rules.md` — y compris les cas honnêtes « nuit » et
     « mesures insuffisantes », et le cas d'un capteur de pluie indisponible.

Usage :   .venv/bin/python tools/check_ha_card.py
Sortie :  0 si tout est conforme, 1 sinon (chaque écart est affiché).
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
except ImportError as exc:  # pragma: no cover - dépendance de l'environnement
    sys.exit(f"dépendance manquante ({exc}) — lancer avec .venv/bin/python")

ROOT = Path(__file__).resolve().parent.parent
CARD = ROOT / "docs" / "ha-card.yaml"
FIRMWARE = ROOT / "esphome" / "vevor-7in1.yaml"
NOW = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)

echos: list[str] = []
failures: list[str] = []


def check(condition: bool, message: str) -> bool:
    (echos if condition else failures).append(message)
    print(("  OK   " if condition else "  ÉCHEC ") + message)
    return condition


def slugify(value: str) -> str:
    """Translittération HA/ESPHome (« Température extérieure » → temperature_exterieure)."""
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
active = "\n".join(
    line for line in raw.splitlines()
    if line.strip() and not line.lstrip().startswith("#")
)
used = sorted(set(re.findall(r"\b(?:sensor|binary_sensor|text_sensor|number|button)\.[a-z0-9_]+", active)))

firmware = FIRMWARE.read_text(encoding="utf-8")
device = slugify(re.search(r"friendly_name:\s*(.+)", firmware).group(1).strip())
declared: set[str] = set()
domain = None
for line in firmware.splitlines():
    head = re.match(r"^(\w+):\s*$", line)
    if head and head.group(1) in ("sensor", "binary_sensor", "text_sensor", "number", "button"):
        domain = head.group(1)
    name = re.match(r'\s+name:\s+"([^"]+)"', line)
    if name and domain:
        declared.add(f"{domain}.{device}_{slugify(name.group(1))}")

print(f"2. Entités : {len(used)} référencées dans la carte, {len(declared)} déclarées par le firmware")
unknown = [entity for entity in used if entity not in declared]
check(not unknown, f"aucune entité inconnue du firmware ({'aucune' if not unknown else unknown})")

# --------------------------------------------------------------------------- 3
legacy = [line.strip() for line in active.splitlines() if re.search(r"esp32_weather|jardin_vevor", line)]
check(not legacy, f"aucun identifiant de l'ancien projet dans les lignes actives ({legacy or 'aucun'})")


# --------------------------------------------------------------------------- 4
class State:
    def __init__(self, state: str, last_changed: datetime | None = None):
        self.state, self.last_changed = state, last_changed


class States:
    """`states('x.y')` ET `states.sensor.x` (objet d'état, pour last_changed)."""

    def __init__(self, data: dict):
        self._data = data

    def __call__(self, entity_id: str, default: str = "unknown") -> str:
        found = self._data.get(entity_id)
        return found.state if found else default

    def __getattr__(self, dom: str):
        if dom.startswith("_"):
            raise AttributeError(dom)

        data = object.__getattribute__(self, "_data")  # pas de récursion via __getattr__

        class Domain:
            def __getattr__(self, obj: str):
                if obj.startswith("_"):
                    raise AttributeError(obj)
                return data.get(f"{dom}.{obj}")

        return Domain()


def render(template: str, data: dict) -> str:
    """Exécute un modèle avec les filtres et fonctions de HA utilisés par la carte."""
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
clear_40 = 133800 * math.sin(math.radians(40)) ** 1.15  # référence ciel clair à 40° (§6)


def scenario(label, *, t, lux, elev, rafale, pluie, il_y_a, attendu, icone, couleur, horizon="above_horizon"):
    data = {
        "sensor.station_vevor_7_en_1_temperature_exterieure": State(str(t)),
        "sensor.station_vevor_7_en_1_vent_rafale": State(str(rafale)),
        "sensor.station_vevor_7_en_1_luminosite": State(str(lux)),
        "sensor.station_vevor_7_en_1_pluie_cumulee": State(str(pluie), NOW - timedelta(seconds=il_y_a)),
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


print("4. Modèles du bandeau exécutés sur des scénarios (verdicts de docs/forecast-rules.md)")
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
scenario("soleil rasant, référence < 1 000 lx — le rapport n'a plus de sens", t=21.0, lux=600,
         elev=0.5, rafale=15, pluie=59.2, il_y_a=3600, attendu="Indéterminé",
         icone="mdi:weather-cloudy-alert", couleur="grey")

print()
if failures:
    print(f"{len(failures)} ÉCHEC(S) : {failures}")
    sys.exit(1)
print(f"CONFORME — {len(echos)} contrôles, 0 échec")
