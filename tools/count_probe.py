#!/usr/bin/env python3
"""Sonde les compteurs du firmware par l'API, SANS dépendre du flux de logs.

Raison d'être : une capture de logs peut n'afficher aucune ligne `V7IN1 RAW` soit parce que
le récepteur ne démodule rien, soit parce que la souscription de logs a décroché. Les
compteurs « Trames valides » / « Trames rejetées » sont des entités d'état : elles avancent
dès qu'un paquet est reçu, indépendamment du flux de logs. Comparer les deux lève le doute.

Usage:
    tools/count_probe.py --host 172.16.0.205 [--seconds 30] [--json logs/count_probe.json]

Code retour :
    0  mesure faite ; un delta de 0 paquet est le RÉSULTAT « aucune trame » ;
    2  échec technique (connexion, exception) ;
    3  MESURE NULLE : aucun état d'entité reçu — rien n'a été mesuré (0 reçu ≠ 0 paquet).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _common import (Device, RC_ERREUR, RC_MESURE_NULLE, RC_OK,  # noqa: E402
                     atomic_write_json, resolve_key)


async def run(host: str, port: int, key: str | None, seconds: float) -> tuple[int, dict]:
    async with Device(host, port, key) as dev:
        # Piège : à la souscription, `subscribe_states` n'a pas encore livré l'état des entités.
        # Lire les compteurs tout de suite renvoie 0 → le « delta » vaudrait le compteur absolu.
        # On attend d'avoir reçu un état, sinon on refuse de conclure.
        for _ in range(40):
            if dev.state:
                break
            await asyncio.sleep(0.25)
        await asyncio.sleep(1.0)
        v0, r0, rssi0 = dev.counts()
        n_states0 = len(dev.state)
        t0 = time.time()
        await asyncio.sleep(seconds)
        v1, r1, rssi1 = dev.counts()
        t1 = time.time()
        delta = (v1 - v0) + (r1 - r0)

        # 0 entité reçue == RIEN n'a été mesuré. Ce n'est PAS « aucun paquet » : il faut le
        # distinguer explicitement, sinon un « compteur figé » se lit à tort comme un silence radio.
        if n_states0 == 0 or len(dev.state) == 0:
            verdict = "MESURE NULLE (aucun état d'entité reçu — rien n'a été mesuré)"
            rc = RC_MESURE_NULLE
        elif delta > 0:
            verdict = "RECEPTION VIVANTE"
            rc = RC_OK
        else:
            verdict = "AUCUNE TRAME (compteurs figés sur la fenêtre — résultat négatif)"
            rc = RC_OK
        return rc, {
            "fenetre_s": round(t1 - t0, 1),
            # Nombre d'états d'entités reçus : 0 = l'appareil n'a rien livré, donc un
            # « compteur figé » ne veut PAS dire « aucun paquet » — la mesure est nulle.
            "entites_recues": {"t0": n_states0, "t1": len(dev.state)},
            "valides": {"t0": v0, "t1": v1},
            "rejetees": {"t0": r0, "t1": r1},
            "paquets_recus": delta,
            "cadence_paquet_par_s": round(delta / max(t1 - t0, 0.1), 3),
            "rssi": {"t0": rssi0, "t1": rssi1},
            "verdict": verdict,
        }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", required=True)
    ap.add_argument("--port", type=int, default=6053)
    ap.add_argument("--key", default=None)
    ap.add_argument("--seconds", type=float, default=30.0)
    ap.add_argument("--json", default=None, help="rapport JSON (relatif = racine du projet)")
    a = ap.parse_args()
    try:
        key = resolve_key(a.key)
        rc, rep = asyncio.run(run(a.host, a.port, key, a.seconds))
    except SystemExit:
        raise
    except Exception as exc:
        print(f"# ERREUR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return RC_ERREUR
    print(json.dumps(rep, ensure_ascii=False, indent=2))
    print("# " + rep["verdict"])
    if a.json:
        print(f"# rapport écrit (atomique): {atomic_write_json(a.json, rep)}")
    if rc == RC_MESURE_NULLE:
        print("# MESURE NULLE — rien n'a été mesuré (code retour 3)", file=sys.stderr)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
