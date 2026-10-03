#!/usr/bin/env python3
"""Réécrit explicitement la fréquence du CC1101 depuis l'API, puis ramène les logs de la fenêtre.

Pourquoi : dans l'état « puce présente et prête mais aucune trame décodée » (CHIP_RDYn bas,
Chip ID 0x0014 lu du premier coup), le suspect restant est que la configuration radio ne soit pas
appliquée correctement — registres de fréquence écrits de travers, puce en RX mais pas sur 868,35 MHz.
Cette commande passe par un chemin INDÉPENDANT du démarrage : elle force une écriture fraîche de la
fréquence (action `set_frequency` du composant), sans reflasher et sans redémarrer.

Usage: tools/regler_frequence.py [--mhz 868.35] [--seconds 150]

Code retour :
    0  écriture prise (relue) et fenêtre mesurée ;
    2  échec technique : entité absente, connexion, ou ÉCRITURE NON PRISE (relue ≠ demandée) ;
    3  MESURE NULLE : aucun log reçu — rien n'a été mesuré.
"""
from __future__ import annotations

import os
import argparse
import asyncio
import datetime
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _common import (FREQ_RE, RC_ERREUR, RC_MESURE_NULLE, RC_OK,  # noqa: E402
                     key_from_yaml)

from aioesphomeapi import APIClient  # noqa: E402


async def run(host: str, port: int, key: str, mhz: float, seconds: float) -> int:
    cli = APIClient(host, port, None, noise_psk=key)
    await cli.connect(login=True)
    entities, _ = await cli.list_entities_services()
    # Entité ANCRÉE : ne pas confondre avec « Offset fréquence » (capteur).
    cible = None
    for e in entities:
        if FREQ_RE.search(getattr(e, "name", "") or ""):
            cible = e
            break
    if cible is None:
        print("!! entité « Fréquence CC1101 » introuvable", file=sys.stderr)
        for e in entities:
            print("   -", getattr(e, "name", "?"), file=sys.stderr)
        await cli.disconnect()
        return RC_ERREUR

    etats = {e.key: getattr(e, "state", None) for e in entities if hasattr(e, "state")}
    compteur = {"logs": 0}

    def horodate(txt: str) -> str:
        return f"[{datetime.datetime.now(datetime.timezone.utc):%H:%M:%S}] {txt}"

    def sur_log(message) -> None:
        compteur["logs"] += 1
        txt = message.message.decode(errors="replace") if isinstance(message.message, bytes) else str(message.message)
        print(horodate(txt[:170]), flush=True)

    def sur_etat(state) -> None:
        etats[state.key] = getattr(state, "state", None)

    cli.subscribe_logs(sur_log)
    cli.subscribe_states(sur_etat)
    await asyncio.sleep(2)
    print(horodate(f"réglage de {cible.name} = {mhz} MHz (écriture fraîche des registres FREQ2/1/0)"))
    await cli.number_command(cible.key, mhz)
    await asyncio.sleep(1.5)
    got = etats.get(cible.key)
    try:
        pris = got is not None and abs(float(got) - mhz) <= 0.001
    except (TypeError, ValueError):
        pris = False
    print(horodate(f"relecture de {cible.name} : {got!r}"))
    await asyncio.sleep(seconds)
    await cli.disconnect()

    if not pris:
        print(f"# ERREUR : la carte n'a PAS pris la fréquence {mhz} MHz (relue {got!r})",
              file=sys.stderr)
        return RC_ERREUR
    if compteur["logs"] == 0:
        print("# MESURE NULLE — écriture prise mais aucun log reçu : rien n'a été mesuré",
              file=sys.stderr)
        return RC_MESURE_NULLE
    return RC_OK


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default=os.environ.get("VEVOR_HOST"),
                    required="VEVOR_HOST" not in os.environ,
                    help="adresse IP de la carte. À défaut : variable d'environnement VEVOR_HOST, ou dev/tools/find_esp32.py pour la découvrir")
    ap.add_argument("--port", type=int, default=6053)
    ap.add_argument("--yaml", default="esphome/vevor-7in1.yaml")
    ap.add_argument("--mhz", type=float, default=868.35)
    ap.add_argument("--seconds", type=float, default=150)
    args = ap.parse_args()
    try:
        key = key_from_yaml(pathlib.Path(args.yaml))
        return asyncio.run(run(args.host, args.port, key, args.mhz, args.seconds))
    except SystemExit:
        raise
    except Exception as exc:
        print(f"# ERREUR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return RC_ERREUR


if __name__ == "__main__":
    sys.exit(main())
