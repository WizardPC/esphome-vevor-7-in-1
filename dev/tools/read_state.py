#!/usr/bin/env python3
"""Lit et affiche l'état de TOUTES les entités de la carte, par l'API native.

Pourquoi : `scan_freq.py --list` ne donne que le nom des entités, pas leur valeur. Or plusieurs
diagnostics dépendent de valeurs d'état et non du flux de logs — en premier lieu « Fréquence
CC1101 » (l'entité `number` a `restore_value: true` : sa valeur restaurée au boot entre en
concurrence avec la fréquence du YAML) et les compteurs « Captures RMT », « Trames valides »,
« Doublons ignorés ».

Piège déjà rencontré ailleurs : `subscribe_states` ne livre pas les états immédiatement. On
attend donc d'avoir reçu quelque chose, sinon on lirait des vides et on conclurait à tort.

Usage:
 dev/tools/read_state.py [--host <ip-de-la-carte>] [--json logs/state.json]

Code retour :
    0  au moins un état d'entité reçu ;
    2  échec technique (connexion, exception) ;
    3  MESURE NULLE : aucun état reçu — rien n'a été mesuré.
"""
from __future__ import annotations

import os
import argparse
import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _common import (Device, RC_ERREUR, RC_MESURE_NULLE, RC_OK,  # noqa: E402
                     atomic_write_json, resolve_key)


async def run(host: str, port: int, key: str | None) -> dict:
    async with Device(host, port, key) as dev:
        for _ in range(40):
            if dev.state:
                break
            await asyncio.sleep(0.25)
        await asyncio.sleep(1.0)
        values = {}
        for name, k in sorted(dev.keys.items()):
            v = dev.state.get(k)
            if isinstance(v, float) and v != v:  # NaN = jamais publié
                v = None
            values[name] = v
        return {"entites": len(dev.keys), "recues": len(dev.state), "valeurs": values}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default=os.environ.get("VEVOR_HOST"),
                    required="VEVOR_HOST" not in os.environ,
                    help="adresse IP de la carte. À défaut : variable d'environnement VEVOR_HOST, ou dev/tools/find_esp32.py pour la découvrir")
    ap.add_argument("--port", type=int, default=6053)
    ap.add_argument("--key", default=None)
    ap.add_argument("--json", default=None, help="fichier JSON (relatif = racine du projet)")
    a = ap.parse_args()
    try:
        rep = asyncio.run(run(a.host, a.port, resolve_key(a.key)))
    except SystemExit:
        raise
    except Exception as exc:
        print(f"# ERREUR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return RC_ERREUR
    print(f"# {rep['recues']}/{rep['entites']} entités avec une valeur")
    for name, v in rep["valeurs"].items():
        print(f"  {name:24s} = {v}")
    if a.json:
        print(f"-> {atomic_write_json(a.json, rep)}")
    if not rep["recues"]:
        print("# MESURE NULLE — aucun état d'entité reçu : rien n'a été mesuré", file=sys.stderr)
        return RC_MESURE_NULLE
    return RC_OK


if __name__ == "__main__":
    raise SystemExit(main())
