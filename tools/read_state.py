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
    tools/read_state.py [--host 172.16.0.205] [--json logs/state.json]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from scan_freq import Device, key_from_yaml  # noqa: E402  (outil voisin, même API)

ROOT = pathlib.Path(__file__).resolve().parent.parent


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
    ap.add_argument("--host", default="172.16.0.205")
    ap.add_argument("--port", type=int, default=6053)
    ap.add_argument("--key", default=None)
    ap.add_argument("--json", default=None)
    a = ap.parse_args()
    rep = asyncio.run(run(a.host, a.port, a.key or key_from_yaml()))
    print(f"# {rep['recues']}/{rep['entites']} entités avec une valeur")
    for name, v in rep["valeurs"].items():
        print(f"  {name:24s} = {v}")
    if a.json:
        p = ROOT / a.json
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"-> {p}")
    return 0 if rep["recues"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
