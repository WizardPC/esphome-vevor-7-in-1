#!/usr/bin/env python3
"""Veille de réception de la station Vevor 7-en-1 (carte 172.16.0.205).

But : ne plus jamais rater une panne de décodage. Le script
  - souscrit au journal de la carte par l'API ESPHome (sans chiffrement) et l'archive tel quel ;
  - surveille l'arrivée des trames ;
  - quand la réception casse (aucune trame publiée pendant PANNE_S secondes) alors que la carte
    reçoit toujours des captures, il appuie LUI-MÊME sur « Dump pulses » pour vider les impulsions
    brutes des rafales en cause, et écrit un instantané du journal à cet instant.

Leçons du 05/10/2026 (les trois premières étaient des bugs réels, constatés en service) :
  - un socket MUET ne lève AUCUNE exception dans aioesphomeapi : après un flash de la carte, la
    veille est restée vivante et figée 7 minutes sans écrire une ligne. La seule détection fiable
    est l'absence de lignes pendant CANARI_S — la carte publie un compteur toutes les ~20 s ;
  - à chaque reconnexion, l'ancien client doit être explicitement déconnecté, sinon ses abonnements
    survivent et chaque ligne est journalisée deux fois ;
  - l'instantané doit être écrit DANS le bloc `with` qui a lu le journal, sinon le fichier est
    créé vide (deux instantanés de 0 octet observés) ;
  - la branche de panne doit APPUYER sur le bouton : l'annoncer sans le faire ne produit aucune
    impulsion, donc aucune preuve (constaté : marqueur « ### PANNE » puis zéro ligne `capture #N`).
  - la clé du bouton est relevée par le script (`list_entities_services`), jamais codée en dur :
    une clé figée survit mal à un reflash.

Sortie : dev/state/veille_reception.log (journal brut + marqueurs), et dev/state/panne_*.txt
(instantané du journal au moment de chaque panne détectée).
"""
import asyncio
import datetime
import os
import sys
import time

try:
    from aioesphomeapi import APIClient, LogLevel
except ImportError:
    sys.exit("aioesphomeapi absent de l'interpréteur : utiliser .venv/bin/python")

HOST = "172.16.0.205"
PORT = 6053
NOM_BOUTON_VIDAGE = "Dump pulses"
PANNE_S = 240                  # aucune trame pendant 4 min alors que des captures arrivent
IMMOBILE_S = 900               # aucune capture du tout pendant 15 min : carte muette, inutile d'insister
REESSAI_S = 300                # ne pas redemander un vidage plus d'une fois par tranche de 5 min
VIDAGE_PERIODIQUE_S = 600      # vidage de courtoisie toutes les 10 min de silence
CANARI_S = 90                  # aucune ligne du tout pendant 90 s : socket muet, on reconnecte

ETAT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "state")
JOURNAL = os.path.join(ETAT, "veille_reception.log")


def horodate() -> str:
    return datetime.datetime.now().strftime("%d/%m %H:%M:%S")


class Veille:
    def __init__(self) -> None:
        self.derniere_trame = time.time()
        self.derniere_capture = time.time()
        self.derniere_ligne = time.time()
        self.dernier_vidage = 0.0
        self.frames = 0
        self.dump_key = None
        self.cli = None

    def ligne(self, texte: str) -> None:
        with open(JOURNAL, "a", encoding="utf8") as f:
            f.write(f"[{horodate()}] {texte}\n")

    def on_log(self, message) -> None:
        brut = getattr(message, "message", None)
        if isinstance(brut, (bytes, bytearray)):
            brut = brut.decode("utf8", "replace")
        elif brut is None:
            brut = str(message)
        self.derniere_ligne = time.time()
        self.ligne(brut.rstrip())
        if "V7IN1 OK" in brut:
            self.derniere_trame = time.time()
            self.frames += 1
        elif "captures=" in brut:
            self.derniere_capture = time.time()

    def _vider(self, raison: str) -> None:
        """Appuie sur « Dump pulses ». Le faire est le SEUL moyen d'obtenir les impulsions brutes."""
        if self.cli is None or self.dump_key is None:
            self.ligne(f"### {raison} — vidage IMPOSSIBLE (bouton inconnu)")
            return
        self.dernier_vidage = time.time()
        self.ligne(f"### {raison} — vidage des impulsions demandé")
        try:
            self.cli.button_command(self.dump_key)
        except Exception as exc:                                 # pragma: no cover
            self.ligne(f"### appui sur le bouton impossible : {exc!r}")

    def _instantane(self) -> None:
        instantane = os.path.join(ETAT, f"panne_{datetime.datetime.now():%Y%m%d_%H%M%S}.txt")
        try:
            with open(JOURNAL, encoding="utf8") as src:
                lignes = src.readlines()[-4000:]                 # lire DANS le with...
            with open(instantane, "w", encoding="utf8") as dst:  # ...et écrire dans un autre :
                dst.writelines(lignes)                           # sinon le fichier reste vide
            self.ligne(f"### instantané avant panne : {os.path.basename(instantane)}")
        except OSError as exc:                                   # pragma: no cover
            self.ligne(f"### instantané impossible : {exc}")

    async def surveiller(self) -> None:
        maintenant = time.time()
        if maintenant - self.derniere_capture > IMMOBILE_S:
            return                                    # rien n'arrive du tout : autre problème
        if maintenant - self.derniere_trame < PANNE_S:
            return
        if maintenant - self.dernier_vidage < REESSAI_S:
            return
        self._vider(f"### PANNE : aucune trame depuis {int(maintenant - self.derniere_trame)} s "
                    "alors que des captures arrivent")
        self._instantane()


async def main() -> None:
    veille = Veille()
    veille.ligne("=== veille démarrée ===")
    while True:
        cli = None
        try:
            cli = APIClient(HOST, PORT, None)
            await asyncio.wait_for(cli.connect(login=True), 30)
            ents, _ = await cli.list_entities_services()
            for e in ents:
                if getattr(e, "name", "") == NOM_BOUTON_VIDAGE:
                    veille.dump_key = e.key
            veille.cli = cli
            cli.subscribe_logs(veille.on_log, log_level=LogLevel.LOG_LEVEL_DEBUG)
            veille.derniere_ligne = time.time()
            veille.ligne(f"--- connecté à la carte, journal en cours "
                         f"(bouton de vidage : {veille.dump_key}) ---")
            while True:
                await asyncio.sleep(10)
                if time.time() - veille.derniere_ligne > CANARI_S:
                    veille.ligne(f"--- aucune ligne depuis {int(time.time() - veille.derniere_ligne)} s : "
                                 "socket muet, reconnexion ---")
                    break
                if time.time() - veille.derniere_trame > VIDAGE_PERIODIQUE_S:
                    veille._vider(f"### silence long ({int(time.time() - veille.derniere_trame)} s)")
                await veille.surveiller()
        except Exception as exc:                                 # reconnexion permanente
            veille.ligne(f"--- connexion perdue ({exc!r}), nouvelle tentative dans 30 s ---")
            await asyncio.sleep(30)
        finally:
            veille.cli = None
            if cli is not None:
                try:
                    await cli.disconnect()                       # sinon : abonnements fantômes
                except Exception:                                # pragma: no cover
                    pass


if __name__ == "__main__":
    asyncio.run(main())
