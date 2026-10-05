#!/usr/bin/env python3
"""Campagne « seuils du garde-fou » : attendre x2, x5, x10 capte-t-il encore des trames valides ?

Une phase règle les DEUX seuils du chien de garde — créneaux muets avant ré-armement radio, et
silence maximal avant redémarrage — puis écoute la carte et archive tout, sans rien interpréter :
trames, compteurs internes, avertissements du garde-fou, états des capteurs, connexions/déconnexions.
Les fichiers produits sont la matière première de l'analyse.

Robustesse (apprise à la dure) :
  * chaque phase est un PROCESSUS séparé, borné par un délai : rien ne peut rester bloqué ;
  * la socket morte est détectée (le rappel de fermeture ET un chien de garde de 90 s) et refaite ;
  * les seuils sont RÉAPPLIQUÉS à chaque reconnexion — la carte les remet à leurs valeurs
    compilées quand elle redémarre, sinon une phase mesurerait silencieusement autre chose.

Sorties (dev/state/) :
  campagne_<etiquette>.jsonl   un événement par ligne (t = epoch, h = heure locale)
  campagne_<etiquette>.log     le journal brut de la carte, tel quel

Usage :
  campagne_rearmement.py --campagne          # les quatre phases d'affilée, bornées
  campagne_rearmement.py --etiquette x5 --creneaux 15 --redemarrage 900 --duree 2100
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

NOM_CRENEAUX = re.compile(r"watchdog\s+silent\s+slots", re.I)
NOM_REDEMARRAGE = re.compile(r"watchdog\s+max\s+silence", re.I)

RE_TRAME = re.compile(r"V7IN1 OK (\{.*\})")
RE_COMPTEURS = re.compile(
    r"captures=(\d+) \(\+(\d+)\), trames=(\d+), rejets=(\d+), réparées=(\d+)"
    r"(?: \(dont (\d+) refusées\))?.*dernières impulsions=(\d+), plus longue=(\d+)")
RE_REARMEMENT = re.compile(r"ré-armement radio (\d+) \(un tous les (\d+) créneaux\)")
RE_REDEMARRAGE = re.compile(r"redémarrage n°(\d+)")
RE_MUET = re.compile(r"aucune trame depuis (\d+) s")

CAPTEURS = ("rmt captures", "valid frames", "rejected frames",
            "duplicates ignored", "tx counter", "station id")


class Phase:
    """Un fichier JSONL d'événements + le journal brut, tous deux écrits ligne par ligne."""

    def __init__(self, etiquette: str, creneaux: int, redemarrage: int, duree: int,
                 appui_periode: int = 0):
        self.etiquette, self.creneaux, self.redemarrage, self.duree = \
            etiquette, creneaux, redemarrage, duree
        # Ré-appui périodique sur « Re-apply radio config » : teste si c'est l'ÉTAT de la puce qui
        # lâche (un ré-armement régulier l'empêcherait de durer) ou autre chose.
        self.appui_periode = appui_periode
        self.dernier_appui = 0.0
        self.jsonl = open(ETAT / f"campagne_{etiquette}.jsonl", "a", buffering=1)
        self.log = open(ETAT / f"campagne_{etiquette}.log", "a", buffering=1)
        self.arret_demande = False
        self.derniere_activite = time.time()
        self.trames = 0
        self.derniere_trame = 0.0
        self.regles_confirmes: dict[str, float] = {}
        self.cles: dict[str, int] = {}
        self.noms_cles: dict[int, str] = {}

    # --- écriture -----------------------------------------------------------
    def note(self, ev: str, **kw) -> None:
        kw = {"ev": ev, "t": round(time.time(), 3),
              "h": datetime.datetime.now().strftime("%H:%M:%S"), **kw}
        self.jsonl.write(json.dumps(kw, ensure_ascii=False) + "\n")
        self.derniere_activite = time.time()

    def brut(self, ligne: str) -> None:
        self.log.write(ligne + "\n")
        self.derniere_activite = time.time()

    # --- rappels aioesphomeapi ---------------------------------------------
    def sur_log(self, reponse) -> None:
        try:
            brut = reponse.message.decode("utf8", "replace") if isinstance(
                reponse.message, (bytes, bytearray)) else str(reponse.message)
        except Exception:                                    # pragma: no cover
            return
        for ligne in brut.splitlines():
            self.brut(ligne)
            m = RE_TRAME.search(ligne)
            if m:
                self.trames += 1
                try:
                    trame = json.loads(m.group(1))
                except Exception:
                    trame = {}
                maintenant = time.time()
                self.note("trame", tx=trame.get("tx_counter"),
                          ecart_s=round(maintenant - self.derniere_trame, 1)
                          if self.derniere_trame else None)
                self.derniere_trame = maintenant
                continue
            m = RE_COMPTEURS.search(ligne)
            if m:
                self.note("compteurs", captures=int(m.group(1)), delta=int(m.group(2)),
                          trames=int(m.group(3)), rejets=int(m.group(4)),
                          reparees=int(m.group(5)), refusees=int(m.group(6) or 0),
                          dernieres_impulsions=int(m.group(7)), plus_longue=int(m.group(8)))
                continue
            m = RE_REARMEMENT.search(ligne)
            if m:
                self.note("rearmement", numero=int(m.group(1)), pas=int(m.group(2)))
                continue
            m = RE_REDEMARRAGE.search(ligne)
            if m:
                self.note("redemarrage_composant", numero=int(m.group(1)))
                continue
            m = RE_MUET.search(ligne)
            if m:
                self.note("muet_composant", secondes=int(m.group(1)))

    def sur_etat(self, etat) -> None:
        # Les objets d'état de l'API ne portent PAS leur nom : la table clé→nom vient de la liste
        # des entités (sans elle, le rappel levait une AttributeError à chaque état).
        nom = self.noms_cles.get(etat.key, "")
        cle = nom.strip().lower()
        valeur = getattr(etat, "state", None)
        if cle in CAPTEURS or NOM_CRENEAUX.search(nom) or NOM_REDEMARRAGE.search(nom):
            self.note("etat", nom=nom, valeur=valeur)
            if NOM_CRENEAUX.search(nom) and float(valeur or 0) == self.creneaux:
                self.regles_confirmes["creneaux"] = valeur
            if NOM_REDEMARRAGE.search(nom) and float(valeur or 0) == self.redemarrage:
                self.regles_confirmes["redemarrage"] = valeur

    async def sur_arret(self, attendu: bool) -> None:
        self.note("socket_fermee", attendu=attendu)
        self.arret_demande = True


async def regler_et_ecouter(cli, phase: Phase, entites) -> None:
    phase.cles = {getattr(e, "name", "") or "": e.key for e in entites}
    phase.noms_cles = {e.key: (getattr(e, "name", "") or "") for e in entites}
    for motif, valeur, nom in ((NOM_CRENEAUX, phase.creneaux, "creneaux_avant_rearmement"),
                               (NOM_REDEMARRAGE, phase.redemarrage, "duree_max_avant_redemarrage")):
        cle = next((k for n, k in phase.cles.items() if motif.search(n)), None)
        if cle is None:
            phase.note("entite_absente", parametre=nom)
            continue
        await maybe_await(cli.number_command(cle, float(valeur)))
        phase.note("reglage_envoye", parametre=nom, valeur=valeur)
    await maybe_await(cli.subscribe_states(phase.sur_etat))
    phase.note("abonnement_capteurs", noms=[n for n in phase.cles if n.strip().lower() in CAPTEURS])
    try:
        from aioesphomeapi.model import LogLevel
        niveau = LogLevel.LOG_LEVEL_DEBUG
    except Exception:                                        # pragma: no cover
        niveau = 5
    await maybe_await(cli.subscribe_logs(phase.sur_log, log_level=niveau))
    phase.note("abonnement_journal")


async def couper(cli) -> None:
    try:
        await asyncio.wait_for(asyncio.shield(cli.disconnect(force=True)), 8)
    except Exception:
        pass


async def choisir_psk(cle_api):
    """Le mode d'authentification réel de la carte : clair d'abord, clé du YAML en secours.

    La carte a été reflashée SANS chiffrement (l'intégration Home Assistant s'en plaint) alors que
    le YAML du dépôt déclare encore une clé : se tromper de mode donne une erreur de connexion
    immédiate, pas une mesure fausse — mais autant le détecter une fois pour toutes.
    """
    import aioesphomeapi
    for psk, nom in ((None, "clair"), (cle_api, "chiffré (clé du YAML)")):
        cli = aioesphomeapi.APIClient(HOTE, PORT, None, noise_psk=psk)
        try:
            await asyncio.wait_for(cli.connect(login=True), 20)
            await asyncio.wait_for(cli.device_info(), 20)
            print(f"[mode] API ESPHome en {nom}", flush=True)
            return psk
        except Exception as exc:
            print(f"[mode] {nom} refusé : {exc!r}"[:170], flush=True)
        finally:
            await couper(cli)
    print("[mode] aucun mode accepté — la carte répond-elle ?", flush=True)
    return None


async def phase_async(a) -> None:
    import aioesphomeapi

    phase = Phase(a.etiquette, a.creneaux, a.redemarrage, a.duree,
                  appui_periode=getattr(a, "appui", 0))
    psk = await choisir_psk(resolve_key())
    fin = time.time() + a.duree
    phase.note("phase_debut", creneaux=a.creneaux, redemarrage_s=a.redemarrage,
               duree_s=a.duree, mode="clair" if psk is None else "chiffre",
               appui_periode_s=phase.appui_periode)
    print(f"[{phase.etiquette}] début : créneaux={a.creneaux} ({a.creneaux * 20} s), "
          f"redémarrage={a.redemarrage} s, durée={a.duree // 60} min", flush=True)

    while time.time() < fin:
        cli = aioesphomeapi.APIClient(HOTE, PORT, None,
                                      noise_psk=psk if psk and psk != "None" else None)
        try:
            await asyncio.wait_for(cli.connect(login=True, on_stop=phase.sur_arret), 25)
            entites, _ = await asyncio.wait_for(cli.list_entities_services(), 25)
            phase.cles = {}
            await regler_et_ecouter(cli, phase, entites)
            phase.note("connecte", entites=len(entites))
            print(f"[{phase.etiquette}] connecté — {len(entites)} entités, seuils envoyés", flush=True)
        except Exception as exc:
            phase.note("erreur_connexion", detail=repr(exc)[:200])
            print(f"[{phase.etiquette}] connexion impossible : {exc!r}"[:160], flush=True)
            await couper(cli)
            await asyncio.sleep(15)
            continue

        phase.arret_demande = False
        phase.derniere_activite = time.time()
        dernier_bilan = time.time()
        try:
            while time.time() < fin and not phase.arret_demande:
                # Chien de garde local : une socket morte ne prévient pas toujours.
                if time.time() - phase.derniere_activite > 90:
                    raise TimeoutError("aucune ligne ni état depuis 90 s")
                if phase.appui_periode and time.time() - phase.dernier_appui >= phase.appui_periode:
                    phase.dernier_appui = time.time()
                    cle = next((k for n, k in phase.cles.items()
                                if n.strip().lower().startswith("re-apply")), None)
                    if cle is None:
                        phase.note("appui_impossible", raison="bouton absent")
                    else:
                        # thread : button_command est synchrone et peut bloquer la boucle asyncio
                        try:
                            await asyncio.wait_for(
                                asyncio.to_thread(cli.button_command, cle), 15)
                            phase.note("appui_reapply")
                        except Exception as exc:
                            phase.note("appui_impossible", raison=repr(exc)[:120])
                            phase.derniere_activite = 0.0
                if time.time() - dernier_bilan > 120:
                    dernier_bilan = time.time()
                    ecart = (round(time.time() - phase.derniere_trame, 1)
                             if phase.derniere_trame else None)
                    print(f"[{phase.etiquette}] {phase.trames} trames, dernier écart={ecart} s, "
                          f"seuils confirmés={phase.regles_confirmes or 'en attente'}", flush=True)
                    phase.note("bilan", trames=phase.trames, ecart_s=ecart)
                await asyncio.sleep(2)
        except Exception as exc:
            phase.note("flux_perdu", detail=repr(exc)[:200])
            print(f"[{phase.etiquette}] flux perdu : {exc!r}"[:160], flush=True)
        finally:
            await couper(cli)
        if not phase.arret_demande:
            await asyncio.sleep(5)

    phase.note("phase_fin", trames=phase.trames,
               seuils_confirmes=phase.regles_confirmes)
    print(f"[{phase.etiquette}] FIN — {phase.trames} trames, "
          f"seuils confirmés={phase.regles_confirmes}", flush=True)
    for f in (phase.jsonl, phase.log):
        f.flush()
        os.fsync(f.fileno())
    phase.jsonl.close()
    phase.log.close()


# --- Les quatre phases de la campagne --------------------------------------
# (étiquette, créneaux avant ré-armement, silence max avant redémarrage en s, minutes)
PHASES = [
    ("x1", 3, 180, 20),      # référence : ce que fait le firmware actuellement (60 s / 180 s)
    ("x2", 6, 360, 20),      # x2 : ré-armement à 120 s, redémarrage à 360 s
    ("x5", 15, 900, 35),     # x5 : 300 s / 900 s
    ("x10", 30, 1800, 40),   # x10 : 600 s / 1800 s
]


# --- Test apparié : bras alternés ------------------------------------------
# Pourquoi alterner : la réception varie d'un quart d'heure à l'autre (4 trous en 20 min, puis
# 0 rejet pendant 16 min). Un plan séquentiel confondrait ce lent changement avec l'effet testé.
# Chaque bras dure 10 min, et on alterne sans/avec le ré-appui périodique. Les seuils du firmware
# sont repoussés (600 s / 3600 s) pour que le garde-fou NE puisse PAS intervenir : la seule
# variable est l'appui. Pourquoi 120 s : les épisodes de surdité naturels durent 3 à 15 min.
BRAS = [("sans1", 0), ("avec1", 120), ("sans2", 0), ("avec2", 120), ("sans3", 0)]
DUREE_BRAS_S = 600


def alternance() -> int:
    python = str(PY) if Path(PY).exists() else sys.executable
    script = str(Path(__file__).resolve())
    for nom, appui in BRAS:
        etiquette = f"pair_{nom}"
        commande = [python, script, "--etiquette", etiquette, "--creneaux", "30",
                    "--redemarrage", "3600", "--duree", str(DUREE_BRAS_S), "--appui", str(appui)]
        print(f"\n===== BRAS {nom} : ré-appui {'toutes les 120 s' if appui else 'AUCUN'} "
              f"({DUREE_BRAS_S // 60} min) =====", flush=True)
        try:
            subprocess.run(commande, timeout=DUREE_BRAS_S + 180, check=False,
                           cwd=str(ROOT), env={**os.environ, "VEVOR_HOST": HOTE})
        except subprocess.TimeoutExpired:
            print(f"[{nom}] bras tué par le délai de sécurité", flush=True)
        time.sleep(15)
    print("\n===== ALTERNANCE TERMINÉE =====", flush=True)
    return 0


def campagne() -> int:
    python = str(PY) if Path(PY).exists() else sys.executable
    script = str(Path(__file__).resolve())
    for etiquette, creneaux, redemarrage, minutes in PHASES:
        duree = minutes * 60
        commande = [python, script, "--etiquette", etiquette, "--creneaux", str(creneaux),
                    "--redemarrage", str(redemarrage), "--duree", str(duree)]
        print(f"\n===== PHASE {etiquette} : {minutes} min, créneaux={creneaux} "
              f"({creneaux * 20} s), redémarrage={redemarrage} s =====", flush=True)
        try:
            subprocess.run(commande, timeout=duree + 180, check=False,
                           cwd=str(ROOT), env={**os.environ, "VEVOR_HOST": HOTE})
        except subprocess.TimeoutExpired:
            print(f"[{etiquette}] phase tuée par le délai de sécurité", flush=True)
        time.sleep(20)
    print("\n===== CAMPAGNE TERMINÉE =====", flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--campagne", action="store_true", help="les quatre phases d'affilée")
    ap.add_argument("--alternance", action="store_true",
                    help="test apparié : bras sans/avec ré-appui périodique, alternés (10 min chacun)")
    ap.add_argument("--etiquette")
    ap.add_argument("--creneaux", type=int)
    ap.add_argument("--redemarrage", type=int)
    ap.add_argument("--duree", type=int, help="secondes")
    ap.add_argument("--appui", type=int, default=0,
                    help="ré-appui périodique sur « Re-apply radio config », en secondes (0 = jamais)")
    a = ap.parse_args()
    ETAT.mkdir(parents=True, exist_ok=True)
    if a.campagne:
        return campagne()
    if a.alternance:
        return alternance()
    if None in (a.etiquette, a.creneaux, a.redemarrage, a.duree):
        ap.error("--etiquette, --creneaux, --redemarrage et --duree sont requis (ou --campagne)")
    asyncio.run(phase_async(a))
    return 0


if __name__ == "__main__":
    sys.exit(main())
