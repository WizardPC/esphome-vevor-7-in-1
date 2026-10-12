#!/usr/bin/env python3
"""Offline check of the reference dashboard cards — examples/ha-card-fr.yaml and -en.yaml.

Without Home Assistant and without hardware, it verifies, for EACH card:

  1. the YAML loads and has the shape of a Lovelace card;
  2. every `entity_id` cited by the card — the commented-out option blocks included, which will be
     uncommented one day — exists in `dev/docs/ha-entities.txt`, HA's measured listing (never
     reconstructed: the entity_id depends on the device name, which is renamed inside HA);
  3. that listing holds exactly the entities `esphome/vevor-7in1.yaml` declares — the EXCEPTIONS
     below included, so a fresh divergence still fails;
  4. no identifier of the old project remains in an active line;
  5. the two "reception" tiles executed on numeric scenarios (fresh frame, missed frame, silent
     radio, unavailable entity, no measurement possible yet, each colour band);
  6. the brightness/UV tile's sky icon, the same way.

Each card is checked against the words of its OWN language (LANG below): the French card and the
English card share their structure and their thresholds, never their labels.

The listing is a MEASUREMENT: `--refresh` rewrites it from the live instance. That path needs the
Home Assistant address (the $HA_URL environment variable, or the git-ignored .ha_url file) and
.ha_token.

Usage:   .venv/bin/python dev/tools/check_ha_card.py [--refresh]
Exit:    0 if both cards conform, 1 otherwise (each discrepancy is printed).
"""

from __future__ import annotations

import math
import os
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
ROOT = DEV.parent                              # repo root
ENTITIES = DEV / "docs" / "ha-entities.txt"
FIRMWARE = ROOT / "esphome" / "vevor-7in1.yaml"
# No address in the code (dev/tools/_common.py is the reference for that rule): $HA_URL, else the
# git-ignored .ha_url file. Only --refresh needs it; the checks below run offline.
HA_URL = os.environ.get("HA_URL") or (
    (ROOT / ".ha_url").read_text(encoding="utf-8").strip() if (ROOT / ".ha_url").exists() else "")
# ANCHOR: entity-id suffix used to find the device-name prefix in the listing. One constant for
# both selecting and trimming the probe, so the two uses cannot diverge. Must match the YAML name.
ANCRAGE = "outdoor_temperature"
# Entity ids Home Assistant did NOT derive from the device name: the owner's utility_meter helpers
# on rain_total. Helpers, not firmware entities — kept OUT of the listing, because the
# firmware <-> HA comparison (step 3) must stay an equality.
EXCEPTIONS_HA = ("rain_hour", "rain_day", "rain_week", "rain_month", "rain_year")
# Declared by the firmware but not yet visible in HA, because the board has not been flashed with it
# since. Deliberately kept APART from EXCEPTIONS_HA: those five are permanent (the owner's helpers),
# these must be removed from here as soon as the listing reports them — otherwise the entry would
# silently mask a genuine disappearance later. Printed on every run so it cannot go unnoticed.
PENDING_FLASH = ()   # empty since the 07/10 17:38 flash: reset_reason arrived in HA.

CARDS = (("fr", ROOT / "examples" / "ha-card-fr.yaml"),
         ("en", ROOT / "examples" / "ha-card-en.yaml"))

# --------------------------------------------------------------------------- refresh
# The listing is a MEASUREMENT: never derive it, always re-read it. This rewrites it from the live
# instance and is the only thing a device rename needs (then re-run without --refresh).
if "--refresh" in sys.argv:
    import json
    import urllib.request

    if not HA_URL:
        sys.exit("--refresh: no Home Assistant address — set $HA_URL or create .ha_url")
    token = (ROOT / ".ha_token").read_text(encoding="utf-8").strip()
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
        "# re-read it before touching a card.",
        "#",
        "## Device",
        f"# device_prefix: {prefix}",
        "",
        "## Entities",
    ]
    ENTITIES.write_text("\n".join(head + ids) + "\n", encoding="utf-8")
    print(f"--refresh: {len(ids)} entities measured in HA, prefix {prefix} -> {ENTITIES}")
    sys.exit(0)

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


# --------------------------------------------------------------------------- shared rendering
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
    """Render a template with the HA filters and functions the cards use."""
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
        # `as_timestamp`: HA exposes it as a function AND as a filter. The last-frame tile uses it
        # to display the exact time of the last passage — an absolute timestamp does not drift,
        # unlike the age, which is a snapshot taken at render time.
        as_timestamp=lambda when: when.timestamp() if hasattr(when, "timestamp") else 0.0,
    )
    env.filters["timestamp_custom"] = lambda value, fmt="%H:%M:%S", local=True: (
        datetime.fromtimestamp(float(value)).strftime(fmt))
    return str(env.from_string(template).render()).strip()


# --------------------------------------------------------------------------- languages
# The labels each card displays. Thresholds are identical in both cards (the scenarios below use
# the same numbers for both, and the same icons): only the words differ, so a translation cannot
# silently move a colour band or a decision boundary.
LANG = {
    "fr": {
        "age_s": "il y a {v} s", "age_min": "il y a {v} min", "age_h": "il y a {v} h",
        "unknown": "inconnu", "unreachable": "Carte injoignable, ou entité absente",
        "frame": "Trame {n} à {t} — {verdict}",
        "normal": "Réception normale", "missed": "Trame manquée",
        "rearm": "Silence (ré-armement)", "reboot": "Silence (reboot)",
        "waiting": "en attente", "unavailable": "Indisponibilité",
        "analyse": "Analyse... (deux trames requises)",
        "window": "{a} / {b} trames produites par la station, 30 dernières",
        "cumul": " · cumul {ok} / {tot}",
        "uv": "UV : {n} / 11+",
    },
    "en": {
        "age_s": "{v} s ago", "age_min": "{v} min ago", "age_h": "{v} h ago",
        "unknown": "unknown", "unreachable": "Card unreachable, or entity missing",
        "frame": "Frame {n} at {t} — {verdict}",
        "normal": "normal reception", "missed": "missed frame",
        "rearm": "silence (re-arm)", "reboot": "silence (reboot)",
        "waiting": "waiting", "unavailable": "unavailable",
        "analyse": "Analyse... (two frames required)",
        "window": "{a} / {b} frames emitted by the station, last 30",
        "cumul": " · total {ok} / {tot}",
        "uv": "UV: {n} / 11+",
    },
}

# --------------------------------------------------------------------------- listing + firmware
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
    sys.exit(f"no entity in \"_{ANCRAGE}\" in dev/docs/ha-entities.txt — cannot derive the device "
             "prefix (update ANCRAGE if the entity name changed)")
prefix = probe.split(".", 1)[1][: -(len(ANCRAGE) + 1)]

# EXCEPTIONS: entity ids HA did NOT derive from the device name, measured on the listing.
# Keyed by the firmware entity name, slugified. An entry here is a measurement, not a workaround:
# the cross-check below stays an equality check, exception included, so a fresh divergence still
# fails. EMPTY since 05/10/2026 — the old ESPHome node was cleaned up in HA and Illuminance came
# back under the device prefix (see dev/docs/ha-entities.txt); the shape is kept so a future
# exception has a documented home.
#     EXCEPTIONS = {"illuminance": "sensor.esp32_weather_illuminance"}
EXCEPTIONS: dict[str, str] = {}

# Step 3 is card-independent: the firmware's declarations against the measured listing.
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
print(f"3. Firmware / HA agreement: device \"{prefix}\", {len(declared)} entities declared by "
      f"esphome/vevor-7in1.yaml, {len(reference)} measured in HA")
print(f"     declared but not in HA yet (pending the next flash): {pending or 'none'}"
      f"  — drop them from PENDING_FLASH once HA reports them")
check(not only_firmware and not only_ha,
      f"the listing matches the firmware (firmware only: {only_firmware or 'none'} | "
      f"HA only: {only_ha or 'none'})")


def check_card(lang: str, path: Path) -> None:
    """Every structural and scenario check of ONE card file, with its own labels."""
    lbl = LANG[lang]
    print()
    print(f"=== {path.relative_to(ROOT)}  (card labels: {lang})")
    raw = path.read_text(encoding="utf-8")

    # ----------------------------------------------------------------- 1
    try:
        card = yaml.safe_load(raw)
        assert isinstance(card, dict) and "cards" in card
        print(f"1. YAML: card '{card['type']}' loaded, {len(card['cards'])} top-level cards")
        echos.append(f"{lang}:yaml")
    except Exception as exc:
        failures.append(f"{lang}:yaml")
        print(f"1. FAIL invalid YAML: {exc}")
        return

    # ----------------------------------------------------------------- 2
    cited = sorted(set(re.findall(
        rf"\b(?:sensor|binary_sensor|text_sensor|number|button)\.{re.escape(prefix)}_[A-Za-z0-9_]+",
        raw)) | {entity for entity in EXCEPTIONS.values() if entity in raw})
    # HELPERS: ids the CARD cites that are neither firmware entities nor HA-listing entries — the
    # owner's utility_meter counters on rain_total (kept out of the listing for the very same
    # reason, see EXCEPTIONS_HA). Declared, never worked around: the check below stays an equality.
    helpers = sorted(entity for entity in cited
                     if entity.split(".", 1)[1][len(prefix) + 1:] in EXCEPTIONS_HA)
    cited = [entity for entity in cited if entity not in helpers]
    print(f"2. Entities: {len(reference)} measured in HA, {len(cited)} cited by the card, "
          f"{len(helpers)} HA helpers declared")
    unknown = [entity for entity in cited if entity not in reference]
    check(not unknown, f"all cited entities exist in the listing ({unknown or 'no divergence'})")
    unused = sorted(entity for entity in reference if entity not in cited)
    print(f"     listing not cited by the card (expected: diag. and commands): {len(unused)}")

    # Negative control of THAT check, before trusting its green: the same extraction, on a copy
    # with one deliberately broken id, must fail — and it must fail ON THAT ID, not on the declared
    # HA helpers (they are legitimately outside the listing, so they are removed first). A check
    # whose failure mode was never exercised is an untested claim.
    casse = raw.replace("tx_counter", "tx_couner")
    cites_casse = sorted(set(re.findall(
        rf"\b(?:sensor|binary_sensor|text_sensor|number|button)\.{re.escape(prefix)}_[A-Za-z0-9_]+",
        casse)))
    inconnus_casse = [entity for entity in cites_casse
                      if entity not in reference and entity not in helpers]
    check(any("tx_couner" in entity for entity in inconnus_casse),
          f"negative control: the broken id is detected ({inconnus_casse[:1] or 'NOT DETECTED'})")

    # ----------------------------------------------------------------- 4
    active = "\n".join(
        line for line in raw.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )
    # The current prefix itself contains "jardin_vevor": match the OLD project's patterns whole.
    legacy = [line.strip() for line in active.splitlines()
              if re.search(r"jardin_vevor_weather_station|esp32_weather_", line)]
    check(not legacy, f"no identifier of the old project in the active lines ({legacy or 'none'})")

    # Option blocks live in comments and will be uncommented one day, so check they parse as YAML.
    blocks: list[str] = []
    cur: list[str] = []
    base: int | None = None
    for line in raw.splitlines():
        starter = (re.match(r"^#(\s*)- ", line)
                   or re.match(r"^#(\s*)[A-Za-z_][A-Za-z0-9_]*:\s*$", line))
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

    # ----------------------------------------------------------------- 5
    # The "Reception" tiles are found by their ENTITY, never by their position: reordering the card
    # must not be able to make this check mute. The templates tested are the exact strings extracted
    # from the YAML, executed with the same Jinja filters as HA (render() above).
    print(f"5. \"Reception\" tiles executed on scenarios ({lang})")

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
            failures.append(f"{lang}:{needle} tile count")
            print(f"   FAIL {len(found)} tile(s) citing \"{needle}\" — exactly 1 expected")
            sys.exit(1)
        return found[0]

    encart_age = encart("tx_counter")
    # The rate is found by ITS entity, never by its position nor by an old name: the card changed
    # its measure on 07/10/2026 (ratio OK/(OK+KO) -> reception_rate, the share of the station's
    # EMISSIONS actually decoded).
    encart_taux = encart("reception_rate")
    entity_age = f"sensor.{prefix}_tx_counter"
    entity_taux = f"sensor.{prefix}_reception_rate"
    entity_rd = f"sensor.{prefix}_reception_window_decoded"
    entity_re = f"sensor.{prefix}_reception_window_emitted"
    entity_ok = f"sensor.{prefix}_valid_frames"
    entity_ko = f"sensor.{prefix}_rejected_frames"
    champs = ("primary", "secondary", "icon", "icon_color")

    def essai(label: str, entete: dict, data: dict, attendu: dict) -> None:
        got = {champ: render(entete[champ], data) for champ in champs}
        ok = all(got[champ] == attendu[champ] for champ in champs)
        print(f"   {'OK  ' if ok else 'FAIL'} {label}")
        print(f"        → {got['primary']} | {got['secondary']}  "
              f"[{got['icon']} / {got['icon_color']}]")
        if ok:
            echos.append(f"{lang}:{label}")
            return
        print(f"        diff (got, expected): "
              f"{ {c: (got[c], attendu[c]) for c in champs if got[c] != attendu[c]} }")
        failures.append(f"{lang}:{label}")

    def age_data(secondes, etat: str = "1234.0") -> dict:
        """State set for the freshness tile. `None` = entity missing (states.sensor.x → None)."""
        if secondes is None:
            return {entity_age: None}
        return {entity_age: State(etat, NOW - timedelta(seconds=secondes))}

    def heure_de(secondes) -> str:
        """The time the card displays for a frame that arrived `secondes` ago — computed with the
        same conversion as the timestamp_custom filter, so without assuming the workstation
        timezone."""
        return datetime.fromtimestamp(
            (NOW - timedelta(seconds=secondes)).timestamp()).strftime("%H:%M:%S")

    def ligne(secondes, verdict: str) -> str:
        """The card's line: frame number, timestamp, then the verdict."""
        return lbl["frame"].format(n=1234, t=heure_de(secondes), verdict=verdict)

    print("   — age of the last frame (reference \"TX counter\")")
    essai("frame 2 s ago — normal reception", encart_age, age_data(2),
          {"primary": lbl["age_s"].format(v=2), "secondary": ligne(2, lbl["normal"]),
           "icon": "mdi:clock-check-outline", "icon_color": "green"})
    essai("frame 35 s ago — last green value", encart_age, age_data(35),
          {"primary": lbl["age_s"].format(v=35), "secondary": ligne(35, lbl["normal"]),
           "icon": "mdi:clock-check-outline", "icon_color": "green"})
    essai("frame 45 s ago — one missed frame", encart_age, age_data(45),
          {"primary": lbl["age_s"].format(v=45), "secondary": ligne(45, lbl["missed"]),
           "icon": "mdi:clock-alert-outline", "icon_color": "amber"})
    essai("frame 61 s ago — the guard re-arms the radio", encart_age, age_data(61),
          {"primary": lbl["age_min"].format(v=1), "secondary": ligne(61, lbl["rearm"]),
           "icon": "mdi:clock-alert-outline", "icon_color": "orange"})
    essai("frame 200 s ago — silence, the board restarts", encart_age, age_data(200),
          {"primary": lbl["age_min"].format(v=3), "secondary": ligne(200, lbl["reboot"]),
           "icon": "mdi:clock-remove-outline", "icon_color": "red"})
    essai("frame 2 h ago — age switches to hours", encart_age, age_data(7200),
          {"primary": lbl["age_h"].format(v="2.0"), "secondary": ligne(7200, lbl["reboot"]),
           "icon": "mdi:clock-remove-outline", "icon_color": "red"})
    essai(f"entity missing — \"{lbl['unknown']}\", never an age of 0", encart_age, age_data(None),
          {"primary": lbl["unknown"], "secondary": lbl["unreachable"],
           "icon": "mdi:help-circle-outline", "icon_color": "grey"})
    essai("entity unavailable — no freshness displayed", encart_age,
          {entity_age: State("unavailable", NOW - timedelta(seconds=5))},
          {"primary": lbl["unknown"], "secondary": lbl["unreachable"],
           "icon": "mdi:help-circle-outline", "icon_color": "grey"})

    def taux_data(taux: str, rd: str, re_: str, ok: str = "149", ko: str = "50") -> dict:
        """States of the five entities the rate tile reads."""
        return {entity_taux: State(taux), entity_rd: State(rd), entity_re: State(re_),
                entity_ok: State(ok), entity_ko: State(ko)}

    # The tile's icon is FIXED (mdi:access-point) and its words come from the card's language (see
    # LANG): the expected values below are copied from the cards, not from an ideal version.
    icone = "mdi:access-point"
    cumul = lbl["cumul"].format(ok=149, tot=199)

    print(f"   — conformant reception rate (\"Reception rate\" and its two terms, {lang})")
    essai("100% — no missed emission, 30/30", encart_taux, taux_data("100.0", "30", "30"),
          {"primary": "100.0 %",
           "secondary": lbl["window"].format(a=30, b=30) + cumul,
           "icon": icone, "icon_color": "green"})
    essai("96.666… % — ONE emission missed out of 30", encart_taux,
          taux_data("96.6666641235352", "29", "30"),
          {"primary": "96.7 %",
           "secondary": lbl["window"].format(a=29, b=30) + cumul,
           "icon": icone, "icon_color": "green"})
    essai("75% — lower limit of green", encart_taux, taux_data("75.0", "30", "40"),
          {"primary": "75.0 %",
           "secondary": lbl["window"].format(a=30, b=40) + cumul,
           "icon": icone, "icon_color": "amber"})
    essai("69.9% — below 70%, the rate turns red", encart_taux, taux_data("69.9", "16", "23"),
          {"primary": "69.9 %",
           "secondary": lbl["window"].format(a=16, b=23) + cumul,
           "icon": icone, "icon_color": "red"})
    essai("64% — a third-party transmitter active", encart_taux, taux_data("64.0", "16", "25"),
          {"primary": "64.0 %",
           "secondary": lbl["window"].format(a=16, b=25) + cumul,
           "icon": icone, "icon_color": "red"})
    essai("fewer than 20 attempts — the cumulative total is not displayed", encart_taux,
          taux_data("100.0", "30", "30", ok="4", ko="1"),
          {"primary": "100.0 %",
           "secondary": lbl["window"].format(a=30, b=30),
           "icon": icone, "icon_color": "green"})
    essai("first measurement impossible (0 emission counted)", encart_taux,
          taux_data("unknown", "0", "0"),
          {"primary": lbl["waiting"], "secondary": lbl["analyse"],
           "icon": icone, "icon_color": "blue-grey"})
    essai("counters unavailable", encart_taux,
          taux_data("unavailable", "unavailable", "unavailable", "unavailable", "unavailable"),
          {"primary": lbl["waiting"], "secondary": lbl["unavailable"],
           "icon": icone, "icon_color": "blue-grey"})
    essai("entities missing from HA (states() returns \"unknown\")", encart_taux, {},
          {"primary": lbl["waiting"], "secondary": lbl["unavailable"],
           "icon": icone, "icon_color": "blue-grey"})

    # ----------------------------------------------------------------- 6
    # Icon of the brightness/UV tile: it follows the state of the sky. Rule taken from
    # dev/docs/forecast-rules.md (Kittler/CIE clear-sky reference, thresholds 0.70 and 0.35,
    # minimum elevation 3°) — no raw lux thresholds: at 3° elevation a clear sky gives only
    # ~4500 lx vs ~80000 at 40°, so a fixed threshold would declare a clear sky "cloudy" at
    # sunrise and sunset. No partly-cloudy night icon: the sensor returns 0 lx at night, it says
    # nothing about clouds.
    print(f"6. Icon of the brightness/UV tile — sky state on scenarios ({lang})")
    encart_lux = encart("illuminance")
    entity_lux = f"sensor.{prefix}_illuminance"
    entity_uv = f"sensor.{prefix}_uv_index"
    # Clear-sky reference at 40° (Kittler/CIE): basis of the scenarios, as in the card.
    clear_40 = 133800 * math.sin(math.radians(40)) ** 1.15

    def lux_data(lux, elev, uv: str = "0") -> dict:
        return {entity_lux: State(str(lux)), entity_uv: State(uv), "_sun_elevation": elev}

    def klx(lux) -> str:
        """What the tile displays in kilolux — same rounding as the card."""
        return f"{round(float(lux) / 1000, 2)} klx"

    icones = {"clair": "mdi:weather-sunny", "partiel": "mdi:weather-partly-cloudy",
              "couvert": "mdi:weather-cloudy", "nuit": "mdi:weather-night",
              "absent": "mdi:help-circle-outline"}

    def essai_icone(label, lux, elev, attendu_icone, uv: str = "0", couleur: str = "green") -> None:
        essai(label, encart_lux, lux_data(lux, elev, uv),
              {"primary": klx(lux) if lux != "unavailable" else klx(0),
               "secondary": lbl["uv"].format(n=int(float(uv))),
               "icon": icones[attendu_icone], "icon_color": couleur})

    essai_icone("clear day, 85% of the reference (40°)", round(0.85 * clear_40), 40, "clair")
    essai_icone("partly cloudy, 50% of the reference", round(0.50 * clear_40), 40, "partiel")
    essai_icone("overcast, 10% of the reference", round(0.10 * clear_40), 40, "couvert")
    essai_icone("grazing sun (2°, below the 3° threshold) — night", 3000, 2, "nuit")
    essai_icone("clear night, 0 lx (sun at -12.3°)", 0, -12.3, "nuit")
    essai_icone("illuminance unavailable in full daylight — help icon, not \"couvert\"",
                "unavailable", 40, "absent")
    essai_icone("UV 6 under overcast sky — the colour follows the UV, not the icon",
                round(0.10 * clear_40), 40, "couvert", uv="6", couleur="orange")


for lang, path in CARDS:
    check_card(lang, path)

print()
if failures:
    print(f"{len(failures)} FAILURE(S): {failures}")
    sys.exit(1)
print(f"CONFORMANT — {len(echos)} checks, 0 failure")
