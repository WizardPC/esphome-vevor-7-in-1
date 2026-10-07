#!/usr/bin/env python3
"""Carte Lovelace du recepteur Vevor 7-en-1 — liste mesuree des entites, verification hors ligne.

    .venv/bin/python dev/tools/carte_ha.py --refresh   interroge Home Assistant et reecrit
                                                       dev/state/entites_ha.txt (liste mesuree)
    .venv/bin/python dev/tools/carte_ha.py             verifie dev/docs/ha-card-vevor-7in1.yaml
                                                       contre cette liste, croise le firmware et
                                                       rend les templates sur des scenarios joues

Le prefixe des entites n'est JAMAIS deduit : il est lu dans Home Assistant (--refresh) et la carte
est verifiee contre cette lecture. Un controle qui re-derive les identifiants qu'il est cense
verifier ne peut que confirmer sa propre supposition.
"""
from __future__ import annotations

import json
import re
import sys
import unicodedata
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

import yaml

RACINE = Path(__file__).resolve().parents[2]
CARTE = RACINE / "dev/docs/ha-card-vevor-7in1.yaml"
LISTE = RACINE / "dev/state/entites_ha.txt"
YAML_FW = RACINE / "esphome/vevor-7in1.yaml"
BASE = "http://192.168.2.104"

# Entites presentes dans Home Assistant mais qui ne viennent PAS du firmware. Declarees ici pour
# que le croisement firmware <-> HA ne les signale pas comme une derive ; chacune expire avec la
# raison qui la documente.
EXCEPTIONS_HA = {
    "rain_hour": "agregat cote HA (utility_meter) sur Rain total",
    "rain_day": "agregat cote HA (utility_meter) sur Rain total",
    "rain_week": "agregat cote HA (utility_meter) sur Rain total",
    "rain_month": "agregat cote HA (utility_meter) sur Rain total",
    "rain_year": "agregat cote HA (utility_meter) sur Rain total",
}

DOMAINES = ("sensor", "binary_sensor", "number", "button", "switch", "text_sensor", "select")

# Le domaine change en passant par Home Assistant : un text_sensor d'ESPHome atterrit sous
# `sensor` cote HA (l'ecrire `text_sensor.` invente un identifiant fantome).
DOMAINE_HA = {"text_sensor": "sensor"}

MOTIF_ID = re.compile(r"\b(" + "|".join(DOMAINES) + r")\.([A-Za-z0-9_]+)")


def slug(nom: str) -> str:
    """Transliteration des noms d'entites, telle que Home Assistant la pratique."""
    s = unicodedata.normalize("NFKD", nom)
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")


class _Chargeur(yaml.SafeLoader):
    """YAML d'ESPHome : !secret, !lambda et !include n'ont pas de constructeur standard."""


def _tag_inconnu(loader, suffixe, noeud):
    if isinstance(noeud, yaml.ScalarNode):
        return loader.construct_scalar(noeud)
    if isinstance(noeud, yaml.SequenceNode):
        return loader.construct_sequence(noeud)
    return loader.construct_mapping(noeud)


_Chargeur.add_multi_constructor("!", _tag_inconnu)


def charger_yaml(chemin: Path):
    return yaml.load(chemin.read_text(encoding="utf8"), Loader=_Chargeur)


def interroger_ha():
    token = (RACINE / ".ha_token").read_text().strip()
    req = urllib.request.Request(
        BASE + "/api/states", headers={"Authorization": "Bearer " + token}
    )
    return json.load(urllib.request.urlopen(req, timeout=30))


def rafraichir() -> int:
    """Reecrit la liste mesuree a partir de Home Assistant."""
    etats = interroger_ha()
    vevor = sorted(
        (s for s in etats if "vevor" in s["entity_id"].lower()),
        key=lambda s: s["entity_id"],
    )
    if not vevor:
        print("ECHEC : aucune entite vevor dans Home Assistant")
        return 1
    prefixe = _prefixe_commun([s["entity_id"] for s in vevor])
    LISTE.parent.mkdir(parents=True, exist_ok=True)
    lignes = [
        "# Entites exposees par Home Assistant pour le recepteur Vevor 7-en-1 (jardin).",
        "# Source   = API REST de Home Assistant, " + BASE + "/api/states",
        "# Lu le    = " + datetime.now().strftime("%d/%m/%Y %H:%M") + " (heure locale)",
        "# Prefixe  = " + prefixe + "   (lu, jamais derive)",
        "# Procedure = .venv/bin/python dev/tools/carte_ha.py --refresh",
        "# Verification de la carte = .venv/bin/python dev/tools/carte_ha.py",
        "# Exceptions declarees (entites HA qui ne viennent pas du firmware) :",
    ]
    for suffixe, raison in sorted(EXCEPTIONS_HA.items()):
        lignes.append("#   " + suffixe + " -> " + raison)
    lignes.append("#")
    for s in vevor:
        lignes.append("%-70s %-14s %s" % (s["entity_id"], s["state"], s["last_changed"][:19]))
    LISTE.write_text("\n".join(lignes) + "\n", encoding="utf8")
    print("liste mesuree reecrite : %s (%d entites, prefixe %s)" % (LISTE.name, len(vevor), prefixe))
    return 0


def _prefixe_commun(ids: list[str]) -> str:
    """Prefixe d'appareil commun a des identifiants de domaines differents."""
    morceaux = [i.split(".", 1)[1] for i in ids]
    commun = morceaux[0]
    for m in morceaux[1:]:
        while not m.startswith(commun):
            commun = commun[:-1]
    return commun.rstrip("_")


def _suffixe(identifiant: str, prefixe: str) -> str:
    """Nom de l'entite sans son domaine ni le prefixe d'appareil."""
    return identifiant.split(".", 1)[1].removeprefix(prefixe).strip("_")


def lire_liste():
    if not LISTE.exists():
        print("ECHEC : %s absent — lancer --refresh" % LISTE.name)
        sys.exit(1)
    ids = []
    for ligne in LISTE.read_text(encoding="utf8").splitlines():
        if ligne.startswith("#") or not ligne.strip():
            continue
        ids.append(ligne.split()[0])
    return ids


def ids_de_la_carte(texte: str):
    """Tous les identifiants cites par la carte (y compris ceux des templates)."""
    trouves = set()
    for domaine, nom in MOTIF_ID.findall(texte):
        nom = nom.rstrip("_")
        if nom:
            trouves.add("%s.%s" % (domaine, nom))
    return sorted(trouves)


def verifier_ids(texte_carte: str, mesures: list[str]):
    cites = ids_de_la_carte(texte_carte)
    inconnus = [i for i in cites if i not in mesures]
    return cites, inconnus


def croiser_firmware(mesures: list[str], prefixe: str):
    """Compare 1 pour 1 les entites declarees par le firmware et celles vues par Home Assistant."""
    doc = charger_yaml(YAML_FW)
    attendus, vus = {}, set(mesures)
    for domaine in DOMAINES:
        for bloc in doc.get(domaine) or []:
            nom = bloc.get("name")
            if not nom:
                continue
            attendus["%s.%s_%s" % (DOMAINE_HA.get(domaine, domaine), prefixe, slug(nom))] = nom
    manquants = {k: v for k, v in attendus.items() if k not in vus}
    hors_firmware = sorted(i for i in vus if _suffixe(i, prefixe) in EXCEPTIONS_HA)
    orphelins = sorted(
        i for i in vus
        if i not in attendus and _suffixe(i, prefixe) not in EXCEPTIONS_HA
    )
    return attendus, manquants, orphelins, hors_firmware


# ------------------------------------------------------------------------------------------------
# Rendu des templates sur des scenarios joues (le harness du projet, version carte HA).
# ------------------------------------------------------------------------------------------------
class Etat:
    def __init__(self, valeur, age_s=None):
        self.state = valeur
        self.last_changed = None if age_s is None else datetime.now() - timedelta(seconds=age_s)


class _Ns:
    def __init__(self, d):
        self._d = d

    def __getattr__(self, n):
        return self._d.get(n)


class States:
    def __init__(self, entites):
        self._e = entites

    def __call__(self, eid, default=None):
        e = self._e.get(eid)
        return e.state if e is not None else (default if default is not None else "unknown")

    def __getattr__(self, domaine):
        return _Ns({k.split(".", 1)[1]: v for k, v in self._e.items() if k.startswith(domaine + ".")})


def rendre(template_str: str, states: States):
    import jinja2

    env = jinja2.Environment(undefined=jinja2.StrictUndefined)
    env.filters["float"] = lambda v, d=0.0: float(v) if _numerique(v) else d
    env.filters["int"] = lambda v, d=0: int(float(v)) if _numerique(v) else d
    env.filters["round"] = lambda v, p=0: round(float(v), int(p)) if _numerique(v) else v
    env.filters["as_timestamp"] = lambda v: v.timestamp() if hasattr(v, "timestamp") else 0.0
    env.filters["timestamp_custom"] = lambda v, f="%H:%M:%S", l=True: datetime.fromtimestamp(float(v)).strftime(f)
    env.globals["now"] = datetime.now
    env.globals["as_timestamp"] = lambda v: v.timestamp() if hasattr(v, "timestamp") else 0.0
    env.globals["states"] = states
    return " ".join(env.from_string(template_str).render().split())


def _numerique(v):
    try:
        float(v)
        return True
    except (TypeError, ValueError):
        return False


def scenarios(prefixe: str):
    base = prefixe + "_"
    tx = "sensor." + base + "tx_counter"
    rate = "sensor." + base + "reception_rate"
    ok = "sensor." + base + "valid_frames"
    ko = "sensor." + base + "rejected_frames"
    dup = "sensor." + base + "duplicates_ignored"

    def etats(tx_e: Etat | None = None, rate_v: object = "unknown", nok: object = 44,
              nko: object = 15, ndup: object = 43):
        d = {
            rate: Etat(str(rate_v)),
            ok: Etat(str(nok)),
            ko: Etat(str(nko)),
            dup: Etat(str(ndup)),
        }
        if tx_e is not None:
            d[tx] = tx_e
        return States(d)

    return [
        ("entite absente", etats(tx_e=None), "inconnu", "injoignable", "grey"),
        ("carte muette", etats(tx_e=Etat("unavailable")), "inconnu", "injoignable", "grey"),
        ("trame fraiche", etats(tx_e=Etat("121", age_s=5), rate_v=100.0), "il y a 5 s", "réception normale", "green"),
        ("une trame manquee", etats(tx_e=Etat("121", age_s=40), rate_v=100.0), "il y a 40 s", "trame manqu", "amber"),
        ("re-armement", etats(tx_e=Etat("121", age_s=90), rate_v=64.0), "il y a 2 min", "ré-armement", "orange"),
        ("redemarrage", etats(tx_e=Etat("121", age_s=400), rate_v=40.0), "il y a 7 min", "redémarre", "red"),
    ]


def main() -> int:
    if "--refresh" in sys.argv:
        return rafraichir()

    mesures = lire_liste()
    prefixe = _prefixe_commun(mesures)
    texte = CARTE.read_text(encoding="utf8")
    carte = charger_yaml(CARTE)
    v1, v2 = carte[0]["cards"]
    echecs = []

    print("=== 1. identifiants cites par la carte ===")
    cites, inconnus = verifier_ids(texte, mesures)
    for i in cites:
        print("   %-72s %s" % (i, "vu dans HA" if i in mesures else "INCONNU"))
    if inconnus:
        echecs.append("%d identifiant(s) absent(s) de Home Assistant : %s" % (len(inconnus), ", ".join(inconnus)))
    print("   prefixe retenu depuis la liste mesuree : %s" % prefixe)

    print("=== 2. croisement firmware <-> Home Assistant ===")
    attendus, manquants, orphelins, hors_firmware = croiser_firmware(mesures, prefixe)
    for k, nom in sorted(attendus.items()):
        print("   %-72s %s" % (k, "present" if k in mesures else "ABSENT DE HA"))
    if manquants:
        echecs.append("declare(s) par le firmware mais absent(s) de HA : %s" % ", ".join(sorted(manquants)))
    if hors_firmware:
        print("   entites HA declarees hors firmware : %s" % ", ".join(hors_firmware))
    if orphelins:
        echecs.append("entite(s) HA rattachee(s) au prefixe mais absente(s) du firmware : %s" % ", ".join(orphelins))

    print("=== 3. scenarios joues ===")
    for nom, states, attendu1, attendu2, couleur in scenarios(prefixe):
        p1 = rendre(v1["primary"], states)
        s1 = rendre(v1["secondary"], states)
        c1 = rendre(v1["icon_color"], states)
        p2 = rendre(v2["primary"], states)
        c2 = rendre(v2["icon_color"], states)
        ok1 = attendu1 in p1 and attendu2 in s1 and c1 == couleur
        print("   %-20s v1(%-24s | %-58s | %-6s) v2(%s | %s)" % (nom, p1, s1[:57], c1, p2, c2))
        if not ok1:
            echecs.append("scenario « %s » : attendu %r / %r / %s, obtenu %r / %r / %s"
                          % (nom, attendu1, attendu2, couleur, p1, s1, c1))

    print("=== 4. controle negatif (la verification doit savoir echouer) ===")
    casse = texte.replace("tx_counter", "tx_couner")
    _, inconnus_casse = verifier_ids(casse, mesures)
    if inconnus_casse:
        print("   identifiant casse detecte : %s  (OK)" % ", ".join(inconnus_casse))
    else:
        echecs.append("controle negatif : un identifiant casse n'a PAS ete detecte")

    print()
    if echecs:
        print("ECHEC : %d probleme(s)" % len(echecs))
        for e in echecs:
            print("   - " + e)
        return 1
    print("OK : carte conforme a la liste mesuree et aux scenarios")
    return 0


if __name__ == "__main__":
    sys.exit(main())
