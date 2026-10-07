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
  5. the two "Reception" cards (age of the last frame, reception rate and its two terms) run on
     scenarios: fresh frame, missed frame, silent radio, unavailable entity, no measurement
     possible yet, and each colour band.

The forecast banner of the previous reference card is no longer part of the card: it left with the
commented options on 07/10/2026 (see the note where its code used to be, and the git history).

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
    sys.exit(f"missing dependency ({exc}) — run with .venv/bin/python")

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
# Declared by the firmware but not yet visible in HA, because the board has not been flashed with it
# since. Deliberately kept APART from EXCEPTIONS_HA: those five are permanent (the owner's helpers),
# these must be removed from here as soon as the listing reports them — otherwise the entry would
# silently mask a genuine disappearance later. Printed on every run so it cannot go unnoticed.
PENDING_FLASH = ("reset_reason",)

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
        sys.exit(f"--refresh: no entity in \"_{ANCRAGE}\" in HA — anchor to review")
    prefix = anchor.split(".", 1)[1][: -(len(ANCRAGE) + 1)]
    ids = sorted(
        state["entity_id"] for state in states
        if state["entity_id"].split(".", 1)[0] in ("sensor", "binary_sensor", "number", "button")
        and state["entity_id"].split(".", 1)[1].startswith(prefix + "_")
        and state["entity_id"].split(".", 1)[1][len(prefix) + 1:] not in EXCEPTIONS_HA
    )
    head = [
        "# Entities actually exposed by Home Assistant — measured, not inferred.",
        "#",
        f"# Source      = Home Assistant REST API, {HA_URL}/api/states",
        f"# Measured on = {datetime.now().strftime('%d/%m/%Y %H:%M')} (local time)",
        f"# Prefix      = {prefix}   (read, never derived)",
        "# Refresh     = .venv/bin/python dev/tools/check_ha_card.py --refresh",
        "# Check       = .venv/bin/python dev/tools/check_ha_card.py  (step 5 of run_tests.sh)",
        "#",
        "# NOT listed below, although attached to the same device: the utility counters",
        f"# created by the owner on rain_total ({', '.join(EXCEPTIONS_HA)} — measured platform:",
        "# utility_meter). They are HA helpers, not firmware entities: including them would",
        "# break the firmware <-> HA equality of step 3.",
        "#",
        "# The entity_id is not derivable from the firmware: the device name is renamed in Home",
        "# Assistant and renames all entity_ids at once. Hence this MEASURED list, and the rule:",
        "# re-read it before touching the card.",
        "#",
        "## Device",
        f"# device_prefix: {prefix}",
        "",
        "## Entities",
    ]
    ENTITIES.write_text("\n".join(head + ids) + "\n", encoding="utf-8")
    print(f"--refresh: {len(ids)} entities measured in HA, prefix {prefix} -> {ENTITIES}")
    sys.exit(0)
FIRMWARE = ROOT / "esphome" / "vevor-7in1.yaml"
NOW = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)

echos: list[str] = []
failures: list[str] = []


def check(condition: bool, message: str) -> bool:
    (echos if condition else failures).append(message)
    print(("  OK   " if condition else "  FAIL ") + message)
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
    print(f"1. YAML: card '{card['type']}' loaded, {len(card['cards'])} top-level cards")
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
    sys.exit(f"2. docs/ha-entities.txt: no entity in \"_{ANCRAGE}\" — cannot derive "
             "the device prefix (update ANCRAGE if the entity name changed)")
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
print(f"2. Entities: device \"{prefix}\", {len(reference)} entities measured in HA, "
      f"{len(cited)} cited by the card, {len(HELPERS)} HA helpers declared → {HELPERS}")
unknown = [entity for entity in cited if entity not in reference]
check(not unknown, f"all cited entities exist in the listing ({unknown or 'no divergence'})")
unused = sorted(entity for entity in reference if entity not in cited)
print(f"     listing not cited by the card (expected: diag. and commands): {len(unused)} → {unused}")

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
      f"negative control: the broken id is detected ({inconnus_casse[:1] or 'NOT DETECTED'})")

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

pending = sorted(entity for entity in declared - reference
                 if entity.split(".", 1)[1][len(prefix) + 1:] in PENDING_FLASH)
only_firmware = sorted(declared - reference - set(pending))
only_ha = sorted(reference - declared)
print(f"3. Firmware / HA agreement: {len(declared)} entities declared by esphome/vevor-7in1.yaml, "
      f"{len(reference)} measured in HA")
print(f"     declared but not in HA yet (pending the next flash): {pending or 'none'}"
      f"  — drop them from PENDING_FLASH once HA reports them")
check(not only_firmware and not only_ha,
      f"the listing matches the firmware (firmware only: {only_firmware or 'none'} | "
      f"HA only: {only_ha or 'none'})")

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
check(not legacy, f"no identifier of the old project in the active lines ({legacy or 'none'})")

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
check(not broken, f"the {len(blocks)} commented option blocks load as YAML "
                  f"({broken or 'no divergence'})")


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
    env.filters["sin"] = lambda v, default=0: math.sin(float(v))
    env.globals.update(
        pi=math.pi,
        states=states,
        state_attr=lambda entity, attr: {"elevation": data["_sun_elevation"]}.get(attr)
        if entity == "sun.sun" else None,
        is_state=lambda entity, value: states(entity) == value,
        now=lambda: NOW,
        relative_time=lambda when: f"{int((NOW - when).total_seconds() // 60)} minutes",
        # `as_timestamp`: HA exposes it as a function AND as a filter. The last-frame tile
        # uses it to display the exact time of the last passage — an absolute timestamp does not
        # drift, unlike the age, which is a snapshot taken at render time.
        as_timestamp=lambda when: when.timestamp() if hasattr(when, "timestamp") else 0.0,
    )
    env.filters["timestamp_custom"] = lambda value, fmt="%H:%M:%S", local=True: (
        datetime.fromtimestamp(float(value)).strftime(fmt))
    return str(env.from_string(template).render()).strip()


# The forecast banner of the old reference card is NOT in this card: this is the owner's card,
# and they do not display it. Its three templates and the 12 scenarios that checked them
# (docs/forecast-rules.md) were removed with the commented options on 07/10/2026; they remain
# in the git history (commit e169663 and earlier) if they are ever to be reinstated. The render
# functions above (State, States, render) serve the check that follows.

# --------------------------------------------------------------------------- 5
# --------------------------------------------------------------------------- 5
# The "Reception" tiles are found by their ENTITY, never by their position: reordering
# the card must not be able to make this check mute. The templates tested are the exact
# strings extracted from the YAML, executed with the same Jinja filters as HA (section 5).
print()
print("5. \"Reception\" tiles executed on scenarios (freshness, conformant reception rate)")


def encart(needle: str) -> dict:
    """The mushroom-template-card whose `entity` contains `needle` — exactly one expected."""
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
        sys.exit(f"6. {len(found)} tile(s) citing \"{needle}\" — exactly 1 expected")
    return found[0]


ENCART_AGE = encart("tx_counter")
# The rate is found by ITS entity, never by its position nor by an old name: the card changed
# its measure on 07/10/2026 (ratio OK/(OK+KO) -> reception_rate, the share of the station's
# EMISSIONS actually decoded).
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
    print(f"   {'OK  ' if ok else 'FAIL'} {label}")
    print(f"        → {got['primary']} | {got['secondary']}  "
          f"[{got['icon']} / {got['icon_color']}]")
    if ok:
        echos.append(label)
        return
    print(f"        diff (got, expected): "
          f"{ {c: (got[c], attendu[c]) for c in CHAMPS if got[c] != attendu[c]} }")
    failures.append(label)


def age_data(secondes, etat: str = "1234.0") -> dict:
    """State set for the freshness tile. `None` = entity missing (states.sensor.x → None)."""
    if secondes is None:
        return {ENTITY_AGE: None}
    return {ENTITY_AGE: State(etat, NOW - timedelta(seconds=secondes))}


def heure_de(secondes) -> str:
    """The time the card displays for a frame that arrived `secondes` ago — computed with the
    same conversion as the timestamp_custom filter, so without assuming the workstation timezone."""
    return datetime.fromtimestamp((NOW - timedelta(seconds=secondes)).timestamp()).strftime("%H:%M:%S")


def verdict_fraicheur(secondes, texte: str) -> str:
    """The card line: frame number, timestamp, then the verdict (timestamp first)."""
    return f"Trame 1234 à {heure_de(secondes)} — {texte}"


print("   — age of the last frame (reference \"TX counter\")")
essai("frame 2 s ago — normal reception", ENCART_AGE, age_data(2),
      {"primary": "il y a 2 s", "secondary": verdict_fraicheur(2, "Réception normale"),
       "icon": "mdi:clock-check-outline", "icon_color": "green"})
essai("frame 35 s ago — last green value", ENCART_AGE, age_data(35),
      {"primary": "il y a 35 s", "secondary": verdict_fraicheur(35, "Réception normale"),
       "icon": "mdi:clock-check-outline", "icon_color": "green"})
essai("frame 45 s ago — one missed frame", ENCART_AGE, age_data(45),
      {"primary": "il y a 45 s", "secondary": verdict_fraicheur(45, "Trame manquée"),
       "icon": "mdi:clock-alert-outline", "icon_color": "amber"})
essai("frame 61 s ago — the guard re-arms the radio", ENCART_AGE, age_data(61),
      {"primary": "il y a 1 min", "secondary": verdict_fraicheur(61, "Silence (ré-armement)"),
       "icon": "mdi:clock-alert-outline", "icon_color": "orange"})
essai("frame 200 s ago — silence, the board restarts", ENCART_AGE, age_data(200),
      {"primary": "il y a 3 min", "secondary": verdict_fraicheur(200, "Silence (reboot)"),
       "icon": "mdi:clock-remove-outline", "icon_color": "red"})
essai("frame 2 h ago — age switches to hours", ENCART_AGE, age_data(7200),
      {"primary": "il y a 2.0 h", "secondary": verdict_fraicheur(7200, "Silence (reboot)"),
       "icon": "mdi:clock-remove-outline", "icon_color": "red"})
essai("entity missing — \"inconnu\", never \"il y a 0 s\"", ENCART_AGE, age_data(None),
      {"primary": "inconnu", "secondary": "Carte injoignable, ou entité absente",
       "icon": "mdi:help-circle-outline", "icon_color": "grey"})
essai("entity unavailable — no freshness displayed", ENCART_AGE,
      {ENTITY_AGE: State("unavailable", NOW - timedelta(seconds=5))},
      {"primary": "inconnu", "secondary": "Carte injoignable, ou entité absente",
       "icon": "mdi:help-circle-outline", "icon_color": "grey"})


def taux_data(taux: str, rd: str, re_: str, ok: str = "149", ko: str = "50") -> dict:
    """States of the five entities the rate tile reads."""
    return {ENTITY_TAUX: State(taux), ENTITY_RD: State(rd), ENTITY_RE: State(re_),
            ENTITY_OK: State(ok), ENTITY_KO: State(ko)}


# The tile is the owner's: its icon is FIXED (mdi:access-point), and its words are theirs —
# the card text is French (see the expected values). The expected values below are therefore
# copied from the card, not from an ideal version.
ICONE = "mdi:access-point"
CUMUL = " · cumul 149 / 199"


print("   — conformant reception rate (\"Reception rate\" and its two terms)")
essai("100% — no missed emission, 30/30 (measured 07/10)", ENCART_TAUX,
      taux_data("100.0", "30", "30"),
      {"primary": "100.0 %",
       "secondary": "30 / 30 trames produites par la station, 30 dernières" + CUMUL,
       "icon": ICONE, "icon_color": "green"})
essai("96.666… % — ONE emission missed out of 30 (measured at 08:53 that day)", ENCART_TAUX,
      taux_data("96.6666641235352", "29", "30"),
      {"primary": "96.7 %",
       "secondary": "29 / 30 trames produites par la station, 30 dernières" + CUMUL,
       "icon": ICONE, "icon_color": "green"})
essai("75% — lower limit of green", ENCART_TAUX, taux_data("75.0", "30", "40"),
      {"primary": "75.0 %",
       "secondary": "30 / 40 trames produites par la station, 30 dernières" + CUMUL,
       "icon": ICONE, "icon_color": "amber"})
essai("69.9% — below 70%, the rate turns red", ENCART_TAUX, taux_data("69.9", "16", "23"),
      {"primary": "69.9 %",
       "secondary": "16 / 23 trames produites par la station, 30 dernières" + CUMUL,
       "icon": ICONE, "icon_color": "red"})
essai("64% — the night of 06-07/10, third-party transmitter active (measured)", ENCART_TAUX,
      taux_data("64.0", "16", "25"),
      {"primary": "64.0 %",
       "secondary": "16 / 25 trames produites par la station, 30 dernières" + CUMUL,
       "icon": ICONE, "icon_color": "red"})
essai("fewer than 20 attempts — the cumulative total is not displayed", ENCART_TAUX,
      taux_data("100.0", "30", "30", ok="4", ko="1"),
      {"primary": "100.0 %",
       "secondary": "30 / 30 trames produites par la station, 30 dernières",
       "icon": ICONE, "icon_color": "green"})
essai("first measurement impossible (0 emission counted)", ENCART_TAUX, taux_data("unknown", "0", "0"),
      {"primary": "en attente", "secondary": "Analyse... (deux trames requises)",
       "icon": ICONE, "icon_color": "blue-grey"})
essai("counters unavailable", ENCART_TAUX,
      taux_data("unavailable", "unavailable", "unavailable", "unavailable", "unavailable"),
      {"primary": "en attente", "secondary": "Indisponibilité",
       "icon": ICONE, "icon_color": "blue-grey"})
essai("entities missing from HA (states() returns \"unknown\")", ENCART_TAUX, {},
      {"primary": "en attente", "secondary": "Indisponibilité",
       "icon": ICONE, "icon_color": "blue-grey"})

# --------------------------------------------------------------------------- 6
# Icon of the brightness/UV tile: it follows the state of the sky, measured, not a fixed icon.
# Rule re-taken from dev/docs/forecast-rules.md (Kittler/CIE clear-sky reference, thresholds 0.70
# and 0.35, minimum elevation 3°) — no raw lux thresholds: at 3° elevation a clear sky gives
# only ~4500 lx vs ~80000 at 40°, so a fixed threshold would declare a clear sky "cloudy"
# at sunrise and sunset. Owner's choice (07/10/2026): no partly-cloudy night icon — the sensor
# returns 0 lx at night (8 readings out of 8), it says nothing about clouds.
print()
print("6. Icon of the brightness/UV tile — sky state on scenarios")
ENCART_LUX = encart("illuminance")
ENTITY_LUX = f"sensor.{prefix}_illuminance"
ENTITY_UV = f"sensor.{prefix}_uv_index"
# Clear-sky reference at 40° (Kittler/CIE): basis of the scenarios, as in the card.
clear_40 = 133800 * math.sin(math.radians(40)) ** 1.15


def lux_data(lux, elev, uv: str = "0") -> dict:
    return {ENTITY_LUX: State(str(lux)), ENTITY_UV: State(uv), "_sun_elevation": elev}


def klx(lux) -> str:
    """What the tile displays in kilolux — same rounding as the card."""
    return f"{round(float(lux) / 1000, 2)} klx"


ICONES = {"clair": "mdi:weather-sunny", "partiel": "mdi:weather-partly-cloudy",
          "couvert": "mdi:weather-cloudy", "nuit": "mdi:weather-night",
          "absent": "mdi:help-circle-outline"}


def essai_icone(label, lux, elev, attendu_icone, uv: str = "0", couleur: str = "green") -> None:
    essai(label, ENCART_LUX, lux_data(lux, elev, uv),
          {"primary": klx(lux) if lux != "unavailable" else klx(0),
           "secondary": f"UV : {int(float(uv))} / 11+",
           "icon": ICONES[attendu_icone], "icon_color": couleur})


essai_icone("clear day, 85% of the reference (40°)", round(0.85 * clear_40), 40, "clair")
essai_icone("partly cloudy, 50% of the reference", round(0.50 * clear_40), 40, "partiel")
essai_icone("overcast, 10% of the reference", round(0.10 * clear_40), 40, "couvert")
essai_icone("grazing sun (2°, below the 3° threshold) — night", 3000, 2, "nuit")
essai_icone("clear night, 0 lx (sun at -12.3°)", 0, -12.3, "nuit")
essai_icone("illuminance unavailable in full daylight — help icon, not \"couvert\"",
            "unavailable", 40, "absent")
essai_icone("UV 6 under overcast sky — the colour follows the UV, not the icon",
            round(0.10 * clear_40), 40, "couvert", uv="6", couleur="orange")

print()
if failures:
    print(f"{len(failures)} FAILURE(S): {failures}")
    sys.exit(1)
print(f"CONFORMANT — {len(echos)} checks, 0 failure")
