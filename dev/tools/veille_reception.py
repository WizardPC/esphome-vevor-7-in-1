#!/usr/bin/env python3
"""Veille de réception de la station Vevor 7-en-1 (carte 172.16.0.205).

But : ne plus jamais rater une panne de décodage. Le script
  - souscrit au journal de la carte par l'API ESPHome (sans chiffrement) et l'archive tel quel ;
  - surveille l'arrivée des trames ;
  - quand la réception se casse (aucune trame publiée pendant PANNE_S secondes) alors que la carte
    reçoit toujours des captures, il appuie sur le bouton « Dump pulses » pour vider les impulsions
    brutes des rafales en cause, et marque l'instant.

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
DUMP_KEY = 2748092880          # entité « Dump pulses » de la carte
PANNE_S = 240                  # aucune trame pendant 4 min alors que des captures arrivent
IMMOBILE_S = 900               # aucune capture du tout pendant 15 min : carte muette, inutile d'insister
REESSAI_S = 900                # ne pas redemander un vidage plus d'une fois par quart d'heure

ETAT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "state")
JOURNAL = os.path.join(ETAT, "veille_reception.log")


def horodate() -> str:
    return datetime.datetime.now().strftime("%d/%m %H:%M:%S")


class Veille:
    def __init__(self) -> None:
        self.derniere_trame = time.time()
        self.derniere_capture = time.time()
        self.dernier_vidage = 0.0
        self.frames = 0
        self.dump_key = DUMP_KEY

    def ligne(self, texte: str) -> None:
        with open(JOURNAL, "a", encoding="utf8") as f:
            f.write(f"[{horodate()}] {texte}\n")

    def on_log(self, message) -> None:
        brut = getattr(message, "message", None)
        if isinstance(brut, (bytes, bytearray)):
            brut = brut.decode("utf8", "replace")
        elif brut is None:
            brut = str(message)
        self.ligne(brut.rstrip())
        if "V7IN1 OK" in brut:
            self.derniere_trame = time.time()
            self.frames += 1
        elif "captures=" in brut:
            self.derniere_capture = time.time()

    async def surveiller(self) -> None:
        maintenant = time.time()
        if maintenant - self.derniere_trame < PANNE_S:
            return
        if maintenant - self.derniere_capture > IMMOBILE_S:
            return
        if maintenant - self.dernier_vidage < REESSAI_S:
            return
        self.dernier_vidage = maintenant
        self.ligne(f"### PANNE : aucune trame depuis {int(maintenant - self.derniere_trame)} s "
                   f"alors que des captures arrivent — vidage des impulsions demandé")
        instantane = os.path.join(ETAT, f"panne_{datetime.datetime.now():%Y%m%d_%H%M%S}.txt")
        try:
            with open(JOURNAL, encoding="utf8") as src, open(instantane, "w", encoding="utf8") as dst:
                lignes = src.readlines()
            dst.writelines(lignes[-4000:])
            self.ligne(f"### instantané avant panne : {os.path.basename(instantane)}")
        except OSError as exc:                                   # pragma: no cover
            self.ligne(f"### instantané impossible : {exc}")


async def main() -> None:
    veille = Veille()
    veille.ligne("=== veille démarrée ===")
    while True:
        try:
            cli = APIClient(HOST, PORT, None)
            await asyncio.wait_for(cli.connect(login=True), 30)
            cli.subscribe_logs(veille.on_log, log_level=LogLevel.LOG_LEVEL_DEBUG)
            veille.ligne("--- connecté à la carte, journal en cours ---")
            while True:
                await asyncio.sleep(10)
                if time.time() - veille.derniere_trame > 600:
                    await asyncio.to_thread(cli.button_command, veille.dump_key)
                await veille.surveiller()
        except Exception as exc:                                 # reconnexion permanente
            veille.ligne(f"--- connexion perdue ({exc!r}), nouvelle tentative dans 30 s ---")
            await asyncio.sleep(30)


if __name__ == "__main__":
    asyncio.run(main())
