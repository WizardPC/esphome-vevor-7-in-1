#!/usr/bin/env python3
"""Balayage EN DIRECT d'un réglage radio : quel débit, quelle déviation, quel filtre décode le mieux ?

Deux inconnues de la chaîne radio n'ont jamais été tranchées :
  * le DÉBIT : 11 111 bauds configurés contre 11 312 mesurés sur les trames (88,4 µs de période) ;
  * la DÉVIATION : 70 kHz chez nous contre 37 kHz dans la référence rtl_433 — contradiction jamais
    levée, et peut-être sans objet si le registre n'agit pas en réception.
Le pilote enregistre cc1101.set_symbol_rate / set_fsk_deviation / set_filter_bandwidth : un réglage
change SANS recompiler, du moment que l'entité correspondante est déclarée dans le YAML.

Métrique principale : le RAPPORT DE DÉCODAGE (trames / rafales), continu et insensible à la position
dans le temps. Secondaires : les rejets, les réparations, l'écart entre trames (la station émet toutes
les 20 s) et l'état des compteurs internes publiés par la carte.

Chaque valeur est posée, RELUE (une écriture non prise ne doit pas compter comme un essai), laissée à
se stabiliser, puis échantillonnée. La valeur de départ est restaurée à la fin, quoi qu'il arrive.

Sorties : dev/state/balayage_<etiquette>.jsonl et .log
Usage :
  balayage_reglages.py --reglage "Data rate" --valeurs 11111,11200,11312,11400 --secondes 150
  balayage_reglages.py --serie            # les trois réglages d'affilée, valeurs par défaut
"""
from __future__ import annotations

import argparse
import asyncio
import datetime
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import DEV, ROOT, PY, resolve_key, maybe_await  # noqa: E402

HOTE = os.environ.get("VEVOR_HOST") or "172.16.0.205"
PORT = 6053
ETAT = DEV / "state"

RE_TRAME = re.compile(r"V7IN1 OK (\{.*\})")
RE_COMPTEURS = re.compile(
    r"captures=(\d+) \(\+(\d+)\), trames=(\d+), rejets=(\d+), réparées=(\d+)"
    r"(?: \(dont (\d+) refusées\))?.*dernières impulsions=(\d+), plus longue=(\d+)")
CAPTEURS = {"rmt captures": "captures", "valid frames": "trames",
            "rejected frames": "rejets", "duplicates ignored": "doublons"}

# (nom d'entité, valeurs à essayer, secondes par valeur, unité)
SERIE = [
    ("Data rate", [11111, 11200, 11312, 11400, 11000], 150),
    ("FSK deviation", [70, 37, 50, 90, 100], 150),
    ("RX filter bandwidth", [100, 162, 203, 232, 58], 150),
]


class Balayage:
    def __init__(self, etiquette: str):
        self.jsonl = open(ETAT / f"balayage_{etiquette}.jsonl", "a", buffering=1)
        self.log = open(ETAT / f"balayage_{etiquette}.log", "a", buffering=1)
        self.noms_cles: dict[int, str] = {}
        self.cles: dict[str, int] = {}
        self.compteurs: dict[str, int] = {}
        self.trames = 0
        self.derniere_trame = 0.0
        self.ecarts: list[float] = []

    def note(self, **kw) -> None:
        kw = {"t": round(time.time(), 3),
              "h": datetime.datetime.now().strftime("%H:%M:%S"), **kw}
        self.jsonl.write(json.dumps(kw, ensure_ascii=False) + "\n")

    def sur_log(self, reponse) -> None:
        try:
            texte = (reponse.message.decode("utf8", "replace")
                     if isinstance(reponse.message, (bytes, bytearray)) else str(reponse.message))
        except Exception:                                        # pragma: no cover
            return
        for ligne in texte.splitlines():
            self.log.write(ligne + "\n")
            if RE_TRAME.search(ligne):
                self.trames += 1
                if self.derniere_trame:
                    self.ecarts.append(round(time.time() - self.derniere_trame, 1))
                self.derniere_trame = time.time()
            m = RE_COMPTEURS.search(ligne)
            if m:
                self.compteurs.update(captures=int(m.group(1)), trames_c=int(m.group(3)),
                                      rejets=int(m.group(4)), reparees=int(m.group(5)),
                                      impulsions=int(m.group(7)))

    def sur_etat(self, etat) -> None:
        nom = (self.noms_cles.get(etat.key, "") or "").strip().lower()
        if nom in CAPTEURS:
            try:
                self.compteurs[CAPTEURS[nom]] = int(float(etat.state))
            except (TypeError, ValueError):
                pass

    def instantane(self) -> dict:
        return dict(self.compteurs)


async def balayer(reglage: str, valeurs: list[float], secondes: float, etiquette: str) -> int:
    import aioesphomeapi
    b = Balayage(etiquette)
    cle_api = resolve_key()

    async def connecter():
        """Un client connecté, ou None. Le mode est détecté une fois (clair puis chiffré)."""
        for psk, nom in ((None, "clair"), (cle_api, "chiffré")):
            essai = aioesphomeapi.APIClient(HOTE, PORT, None, noise_psk=psk)
            try:
                await asyncio.wait_for(essai.connect(login=True), 25)
                print(f"[mode] API en {nom}", flush=True)
                return essai
            except Exception as exc:
                print(f"[mode] {nom} refusé : {exc!r}"[:140], flush=True)
                try:
                    await asyncio.wait_for(essai.disconnect(force=True), 8)
                except Exception:
                    pass
        return None

    async def rejoindre():
        """(re)connexion + abonnements. NE DOIT JAMAIS laisser l'outil mourir : le 05/10 la série
        s'est arrêtée sur « Not connected » et deux passes entières ont été perdues."""
        essai = await connecter()
        if essai is None:
            return None, None
        try:
            ent, _ = await asyncio.wait_for(essai.list_entities_services(), 25)
        except Exception as exc:
            print(f"!! liste des entités indisponible : {exc!r}"[:140], flush=True)
            try:
                await asyncio.wait_for(essai.disconnect(force=True), 8)
            except Exception:
                pass
            return None, None
        b.noms_cles = {e.key: (getattr(e, "name", "") or "") for e in ent}
        cible = next((e for e in ent
                      if (getattr(e, "name", "") or "").strip().lower() == reglage.strip().lower()),
                     None)
        etats: dict[int, float] = {}

        def sur_etat(etat) -> None:
            etats[etat.key] = getattr(etat, "state", None)
            b.sur_etat(etat)

        try:
            await maybe_await(essai.subscribe_states(sur_etat))
            try:
                from aioesphomeapi.model import LogLevel
                niveau = LogLevel.LOG_LEVEL_DEBUG
            except Exception:                                     # pragma: no cover
                niveau = 5
            await maybe_await(essai.subscribe_logs(b.sur_log, log_level=niveau))
        except Exception as exc:
            print(f"!! abonnements indisponibles : {exc!r}"[:140], flush=True)
        return essai, (cible, etats)

    cli = None
    cible = etats = None
    for tentative in range(12):
        cli, paquet = await rejoindre()
        if cli is not None and paquet is not None:
            cible, etats = paquet
            break
        print(f"  connexion {tentative + 1}/12 impossible, nouvelle tentative dans 20 s", flush=True)
        await asyncio.sleep(20)
    if cli is None or cible is None:
        print("!! carte injoignable : rien ne peut être mesuré", file=sys.stderr)
        return 2
    print(f"[cible] {cible.name} (clé {cible.key})", flush=True)
    await asyncio.sleep(3)
    depart = etats.get(cible.key)
    b.note(ev="debut", reglage=reglage, cle=cible.key, depart=depart, valeurs=valeurs,
           secondes=secondes)
    print(f"[cible] {cible.name} = {depart} (valeur de départ) | {len(valeurs)} valeurs × "
          f"{secondes:.0f} s ≈ {len(valeurs) * (secondes + 15) / 60:.0f} min", flush=True)

    resultats = []
    for valeur in valeurs:
        # Robustesse : une commande peut bloquer ou tomber sur une socket morte (la carte n'accepte
        # qu'un nombre limité de clients). Sans ces bornes, la boucle restait bloquée sur la première
        # valeur — constaté le 05/10 au soir : vingt minutes sans une seule mesure.
        try:
            await asyncio.wait_for(maybe_await(cli.number_command(cible.key, float(valeur))), 20)
        except Exception as exc:
            print(f"  !! commande « {valeur} » impossible ({exc!r}) — reconnexion", flush=True)
            b.note(ev="perte_pendant_valeur", valeur=valeur, detail=repr(exc)[:120])
            nouveau, paquet = await rejoindre()
            if nouveau is not None and paquet is not None and paquet[0] is not None:
                cli, (cible, etats) = nouveau, paquet
                await asyncio.sleep(3)
                try:
                    await asyncio.wait_for(
                        maybe_await(cli.number_command(cible.key, float(valeur))), 20)
                except Exception as exc2:
                    b.note(ev="valeur_abandonnee", valeur=valeur, detail=repr(exc2)[:120])
                    print(f"  !! valeur « {valeur} » abandonnée : {exc2!r}"[:140], flush=True)
                    continue
            else:
                continue
        await asyncio.sleep(2)
        relu = etats.get(cible.key)
        try:
            pris = relu is not None and abs(float(relu) - float(valeur)) <= 0.01
        except (TypeError, ValueError):
            pris = False
        await asyncio.sleep(12)                    # pose de la puce
        avant, t0 = b.instantane(), time.time()
        tr0, ec0 = b.trames, len(b.ecarts)
        await asyncio.sleep(secondes)
        apres = b.instantane()
        dc = apres.get("captures", 0) - avant.get("captures", 0)
        dt = apres.get("trames_c", 0) - avant.get("trames_c", 0)
        dr = apres.get("rejets", 0) - avant.get("rejets", 0)
        ecarts = b.ecarts[ec0:]
        res = {"reglage": reglage, "valeur": valeur, "prise": pris, "relu": relu,
               "dcaptures": dc, "dtrames": dt, "drejets": dr,
               "impulsions": apres.get("impulsions"),
               "rapport": round(dt / dc, 3) if dc else None,
               "ecarts": ecarts, "secondes": round(time.time() - t0, 1)}
        resultats.append(res)
        b.note(ev="valeur", **res)
        print(f"  {reglage} = {valeur} : rafales +{dc}, trames +{dt}, rejets +{dr}, "
              f"rapport={res['rapport']}, écarts={ecarts}"
              + ("" if pris else "  [VALEUR NON PRISE]"), flush=True)

    await maybe_await(cli.number_command(cible.key, float(depart if depart is not None else valeurs[0])))
    await asyncio.sleep(1.5)
    b.note(ev="restauration", reglage=reglage, valeur=depart, relu=etats.get(cible.key))
    print(f"[fin] {reglage} restauré à {depart} (relu {etats.get(cible.key)})", flush=True)

    print(f"\n=== bilan {reglage} ===")
    for r in resultats:
        barre = "" if r["rapport"] is None else "█" * int(r["rapport"] * 40)
        print(f"  {r['valeur']:>9} : rafales {r['dcaptures']:4d}  trames {r['dtrames']:3d}  "
              f"rejets {r['drejets']:4d}  {barre}")
    b.note(ev="fin", reglage=reglage, resultats=resultats)
    try:
        await asyncio.wait_for(cli.disconnect(force=True), 10)
    except Exception:
        pass
    for f in (b.jsonl, b.log):
        f.flush()
        os.fsync(f.fileno())
    return 0


def serie() -> int:
    python = str(PY) if Path(PY).exists() else sys.executable
    script = str(Path(__file__).resolve())
    for reglage, valeurs, secondes in SERIE:
        etiquette = reglage.lower().replace(" ", "_")
        commande = [python, script, "--reglage", reglage,
                    "--valeurs", ",".join(str(v) for v in valeurs),
                    "--secondes", str(secondes), "--etiquette", etiquette]
        print(f"\n===== BALAYAGE « {reglage} » : {valeurs} =====", flush=True)
        try:
            subprocess.run(commande, timeout=int(secondes * len(valeurs) + 600), check=False,
                           cwd=str(ROOT), env={**os.environ, "VEVOR_HOST": HOTE})
        except subprocess.TimeoutExpired:
            print(f"[{reglage}] balayage tué par le délai de sécurité", flush=True)
        time.sleep(10)
    print("\n===== SÉRIE TERMINÉE =====", flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--serie", action="store_true", help="les trois réglages d'affilée")
    ap.add_argument("--reglage", help="nom EXACT de l'entité, ex. \"Data rate\"")
    ap.add_argument("--valeurs", help="valeurs séparées par des virgules")
    ap.add_argument("--secondes", type=float, default=150.0)
    ap.add_argument("--etiquette", default="reglage")
    a = ap.parse_args()
    ETAT.mkdir(parents=True, exist_ok=True)
    if a.serie:
        return serie()
    if not a.reglage or not a.valeurs:
        ap.error("--reglage et --valeurs sont requis (ou --serie)")
    return asyncio.run(balayer(a.reglage, [float(x) for x in a.valeurs.split(",")],
                               a.secondes, a.etiquette))


if __name__ == "__main__":
    sys.exit(main())
