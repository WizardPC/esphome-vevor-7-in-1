#!/usr/bin/env python3
"""Campaign "guard thresholds": waiting x2, x5, x10, does it still catch valid frames?

One phase sets BOTH watchdog thresholds — silent slots before radio re-arm, and
max silence before restart — then listens to the board and archives everything, without
interpreting anything: frames, internal counters, guard warnings, sensor states, connections/
disconnections. The files produced are the raw material of the analysis.

Robustness (learned the hard way):
  * each phase is a separate PROCESS, bounded by a timeout: nothing can stay stuck;
  * the dead socket is detected (the close callback AND a 90 s watchdog) and rebuilt;
  * the thresholds are RE-APPLIED on each reconnection — the board resets them to their
    compiled values when it restarts, otherwise a phase would silently measure something else.

Outputs (dev/state/):
  campagne_<label>.jsonl   one event per line (t = epoch, h = local time)
  campagne_<label>.log     the board's raw log, as-is

Usage:
  campagne_rearmement.py --campagne          # the four phases in a row, bounded
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
    r"captures=(\d+) \(\+(\d+)\), frames=(\d+), rejects=(\d+), repaired=(\d+)"
    r"(?: \((?:dont )?(\d+) refus(?:ées|ed)\))?.*(?:dernières|last) pulses=(\d+), longest=(\d+)")
RE_REARMEMENT = re.compile(r"(?:ré-armement|re-arm) radio (\d+) \((?:un tous les|one every) (\d+) (?:créneaux|slots)\)")
RE_REDEMARRAGE = re.compile(r"(?:redémarrage|restart) #?(\d+)")
RE_MUET = re.compile(r"(?:aucune trame depuis|no frame for) (\d+) s")

CAPTEURS = ("rmt captures", "valid frames", "rejected frames",
            "duplicates ignored", "tx counter", "station id")


class Phase:
    """A JSONL file of events + the raw log, both written line by line."""

    def __init__(self, etiquette: str, creneaux: int, redemarrage: int, duree: int,
                 appui_periode: int = 0):
        self.etiquette, self.creneaux, self.redemarrage, self.duree = \
            etiquette, creneaux, redemarrage, duree
        # Periodic re-press of "Re-apply radio config": tests whether it is the chip's STATE that
        # gives up (a regular re-arm would prevent it from lasting) or something else.
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

    # --- writing ------------------------------------------------------------
    def note(self, ev: str, **kw) -> None:
        kw = {"ev": ev, "t": round(time.time(), 3),
              "h": datetime.datetime.now().strftime("%H:%M:%S"), **kw}
        self.jsonl.write(json.dumps(kw, ensure_ascii=False) + "\n")
        self.derniere_activite = time.time()

    def brut(self, ligne: str) -> None:
        self.log.write(ligne + "\n")
        self.derniere_activite = time.time()

    # --- aioesphomeapi callbacks --------------------------------------------
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
                          frames=int(m.group(3)), rejects=int(m.group(4)),
                          reparees=int(m.group(5)), refusees=int(m.group(6) or 0),
                          dernieres_pulses=int(m.group(7)), plus_longue=int(m.group(8)))
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
        # The API state objects do NOT carry their name: the key→name table comes from the entity
        # list (without it, the callback raised an AttributeError on every state).
        nom = self.noms_cles.get(etat.key, "")
        cle = nom.strip().lower()
        value = getattr(etat, "state", None)
        if cle in CAPTEURS or NOM_CRENEAUX.search(nom) or NOM_REDEMARRAGE.search(nom):
            self.note("etat", nom=nom, value=value)
            if NOM_CRENEAUX.search(nom) and float(value or 0) == self.creneaux:
                self.regles_confirmes["creneaux"] = value
            if NOM_REDEMARRAGE.search(nom) and float(value or 0) == self.redemarrage:
                self.regles_confirmes["redemarrage"] = value

    async def sur_arret(self, attendu: bool) -> None:
        self.note("socket_fermee", attendu=attendu)
        self.arret_demande = True


async def regler_et_ecouter(cli, phase: Phase, entites) -> None:
    phase.cles = {getattr(e, "name", "") or "": e.key for e in entites}
    phase.noms_cles = {e.key: (getattr(e, "name", "") or "") for e in entites}
    for motif, value, nom in ((NOM_CRENEAUX, phase.creneaux, "rearm_after_slots"),
                               (NOM_REDEMARRAGE, phase.redemarrage, "max_restart_delay")):
        cle = next((k for n, k in phase.cles.items() if motif.search(n)), None)
        if cle is None:
            phase.note("entite_absente", parametre=nom)
            continue
        await maybe_await(cli.number_command(cle, float(value)))
        phase.note("reglage_envoye", parametre=nom, value=value)
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
    """The board's real authentication mode: plain first, YAML key as a fallback.

    The board was reflashed WITHOUT encryption (the Home Assistant integration complains about it)
    while the repo YAML still declares a key: getting the mode wrong gives an immediate connection
    error, not a false measurement — but might as well detect it once and for all.
    """
    import aioesphomeapi
    for psk, nom in ((None, "plain"), (cle_api, "encrypted (YAML key)")):
        cli = aioesphomeapi.APIClient(HOTE, PORT, None, noise_psk=psk)
        try:
            await asyncio.wait_for(cli.connect(login=True), 20)
            await asyncio.wait_for(cli.device_info(), 20)
            print(f"[mode] API ESPHome as {nom}", flush=True)
            return psk
        except Exception as exc:
            print(f"[mode] {nom} refused: {exc!r}"[:170], flush=True)
        finally:
            await couper(cli)
    print("[mode] no mode accepted — is the board answering?", flush=True)
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
    print(f"[{phase.etiquette}] start: slots={a.creneaux} ({a.creneaux * 20} s), "
          f"restart={a.redemarrage} s, duration={a.duree // 60} min", flush=True)

    while time.time() < fin:
        cli = aioesphomeapi.APIClient(HOTE, PORT, None,
                                      noise_psk=psk if psk and psk != "None" else None)
        try:
            await asyncio.wait_for(cli.connect(login=True, on_stop=phase.sur_arret), 25)
            entites, _ = await asyncio.wait_for(cli.list_entities_services(), 25)
            phase.cles = {}
            await regler_et_ecouter(cli, phase, entites)
            phase.note("connecte", entites=len(entites))
            print(f"[{phase.etiquette}] connected — {len(entites)} entities, thresholds sent", flush=True)
        except Exception as exc:
            phase.note("erreur_connexion", detail=repr(exc)[:200])
            print(f"[{phase.etiquette}] connection failed: {exc!r}"[:160], flush=True)
            await couper(cli)
            await asyncio.sleep(15)
            continue

        phase.arret_demande = False
        phase.derniere_activite = time.time()
        dernier_bilan = time.time()
        try:
            while time.time() < fin and not phase.arret_demande:
                # Local watchdog: a dead socket does not always warn.
                if time.time() - phase.derniere_activite > 90:
                    raise TimeoutError("no line nor state for 90 s")
                if phase.appui_periode and time.time() - phase.dernier_appui >= phase.appui_periode:
                    phase.dernier_appui = time.time()
                    cle = next((k for n, k in phase.cles.items()
                                if n.strip().lower().startswith("re-apply")), None)
                    if cle is None:
                        phase.note("appui_impossible", raison="bouton absent")
                    else:
                        # thread: button_command is synchronous and can block the asyncio loop
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
                    print(f"[{phase.etiquette}] {phase.trames} frames, last gap={ecart} s, "
                          f"confirmed thresholds={phase.regles_confirmes or 'pending'}", flush=True)
                    phase.note("bilan", frames=phase.trames, ecart_s=ecart)
                await asyncio.sleep(2)
        except Exception as exc:
            phase.note("flux_perdu", detail=repr(exc)[:200])
            print(f"[{phase.etiquette}] stream lost: {exc!r}"[:160], flush=True)
        finally:
            await couper(cli)
        if not phase.arret_demande:
            await asyncio.sleep(5)

    phase.note("phase_fin", frames=phase.trames,
               seuils_confirmes=phase.regles_confirmes)
    print(f"[{phase.etiquette}] END — {phase.trames} frames, "
          f"confirmed thresholds={phase.regles_confirmes}", flush=True)
    for f in (phase.jsonl, phase.log):
        f.flush()
        os.fsync(f.fileno())
    phase.jsonl.close()
    phase.log.close()


# --- The four campaign phases ----------------------------------------------
# (label, slots before re-arm, max silence before restart in s, minutes)
PHASES = [
    ("x1", 3, 180, 20),      # reference: what the firmware does now (60 s / 180 s)
    ("x2", 6, 360, 20),      # x2: re-arm at 120 s, restart at 360 s
    ("x5", 15, 900, 35),     # x5 : 300 s / 900 s
    ("x10", 30, 1800, 40),   # x10 : 600 s / 1800 s
]


# --- Paired test: alternating arms -----------------------------------------
# Why alternate: reception varies from one quarter-hour to the next (4 gaps in 20 min, then
# 0 reject for 16 min). A sequential plan would confuse this slow change with the effect tested.
# Each arm lasts 10 min, and we alternate without/with the periodic re-press. The firmware
# thresholds are pushed back (600 s / 3600 s) so that the guard CANNOT step in: the only
# variable is the press. Why 120 s: natural deafness episodes last 3 to 15 min.
BRAS = [("without1", 0), ("with1", 120), ("without2", 0), ("with2", 120), ("without3", 0)]
DUREE_BRAS_S = 600


def alternance() -> int:
    python = str(PY) if Path(PY).exists() else sys.executable
    script = str(Path(__file__).resolve())
    for nom, appui in BRAS:
        etiquette = f"pair_{nom}"
        commande = [python, script, "--etiquette", etiquette, "--creneaux", "30",
                    "--redemarrage", "3600", "--duree", str(DUREE_BRAS_S), "--appui", str(appui)]
        print(f"\n===== ARM {nom}: re-press {'every 120 s' if appui else 'NONE'} "
              f"({DUREE_BRAS_S // 60} min) =====", flush=True)
        try:
            subprocess.run(commande, timeout=DUREE_BRAS_S + 180, check=False,
                           cwd=str(ROOT), env={**os.environ, "VEVOR_HOST": HOTE})
        except subprocess.TimeoutExpired:
            print(f"[{nom}] arm killed by the safety timeout", flush=True)
        time.sleep(15)
    print("\n===== ALTERNATION DONE =====", flush=True)
    return 0


def campagne() -> int:
    python = str(PY) if Path(PY).exists() else sys.executable
    script = str(Path(__file__).resolve())
    for etiquette, creneaux, redemarrage, minutes in PHASES:
        duree = minutes * 60
        commande = [python, script, "--etiquette", etiquette, "--creneaux", str(creneaux),
                    "--redemarrage", str(redemarrage), "--duree", str(duree)]
        print(f"\n===== PHASE {etiquette}: {minutes} min, slots={creneaux} "
              f"({creneaux * 20} s), restart={redemarrage} s =====", flush=True)
        try:
            subprocess.run(commande, timeout=duree + 180, check=False,
                           cwd=str(ROOT), env={**os.environ, "VEVOR_HOST": HOTE})
        except subprocess.TimeoutExpired:
            print(f"[{etiquette}] phase killed by the safety timeout", flush=True)
        time.sleep(20)
    print("\n===== CAMPAIGN DONE =====", flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--campagne", action="store_true", help="the four phases in a row")
    ap.add_argument("--alternance", action="store_true",
                    help="paired test: arms without/with periodic re-press, alternated (10 min each)")
    ap.add_argument("--etiquette")
    ap.add_argument("--creneaux", type=int)
    ap.add_argument("--redemarrage", type=int)
    ap.add_argument("--duree", type=int, help="seconds")
    ap.add_argument("--appui", type=int, default=0,
                    help="periodic re-press of \"Re-apply radio config\", in seconds (0 = never)")
    a = ap.parse_args()
    ETAT.mkdir(parents=True, exist_ok=True)
    if a.campagne:
        return campagne()
    if a.alternance:
        return alternance()
    if None in (a.etiquette, a.creneaux, a.redemarrage, a.duree):
        ap.error("--etiquette, --creneaux, --redemarrage and --duree are required (or --campagne)")
    asyncio.run(phase_async(a))
    return 0


if __name__ == "__main__":
    sys.exit(main())
