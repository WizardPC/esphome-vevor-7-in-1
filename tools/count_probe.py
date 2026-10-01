#!/usr/bin/env python3
"""Sonde les compteurs du firmware par l'API, SANS dépendre du flux de logs.

Raison d'être : une capture de logs peut n'afficher aucune ligne `V7IN1 RAW` soit parce que
le récepteur ne démodule rien, soit parce que la souscription de logs a décroché. Les
compteurs « Trames valides » / « Trames rejetées » sont des entités d'état : elles avancent
dès qu'un paquet est reçu, indépendamment du flux de logs. Comparer les deux lève le doute.

Usage:
    tools/count_probe.py --host 172.16.0.205 [--seconds 30] [--json logs/count_probe.json]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from scan_freq import Device, key_from_yaml  # noqa: E402  (outil voisin, même API)


async def run(host: str, port: int, key: str | None, seconds: float) -> dict:
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
        return {
            "fenetre_s": round(t1 - t0, 1),
            # Nombre d'états d'entités reçus : 0 = l'appareil n'a rien livré, donc un
            # « compteur figé » ne veut PAS dire « aucun paquet » — la mesure est nulle.
            "entites_recues": {"t0": n_states0, "t1": len(dev.state)},
            "valides": {"t0": v0, "t1": v1},
            "rejetees": {"t0": r0, "t1": r1},
            "paquets_recus": delta,
            "cadence_paquet_par_s": round(delta / max(t1 - t0, 0.1), 3),
            "rssi": {"t0": rssi0, "t1": rssi1},
            "verdict": "RECEPTION VIVANTE" if delta > 0 else "AUCUN PAQUET (compteurs figes)",
        }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", required=True)
    ap.add_argument("--port", type=int, default=6053)
    ap.add_argument("--key", default=None)
    ap.add_argument("--seconds", type=float, default=30.0)
    ap.add_argument("--json", default=None)
    a = ap.parse_args()
    key = a.key or key_from_yaml()
    rep = asyncio.run(run(a.host, a.port, key, a.seconds))
    print(json.dumps(rep, ensure_ascii=False, indent=2))
    print("# " + rep["verdict"])
    if a.json:
        pathlib.Path(a.json).write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"# rapport écrit: {a.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
