#!/usr/bin/env python3
"""Balayage de fréquence sur la voie ASYNCHRONE, jugé sur les compteurs de la carte.

Contrairement à scan_freq.py (écrit pour le mode packet et son RSSI), ce balayage-ci n'utilise
que ce que la voie asynchrone publie réellement : les compteurs « Trames valides / Trames
rejetées » et les battements de cœur du composant (« captures=…, trames=…, plus longue=… »), lus
par l'API native. La cadence de captures et les durées d'impulsions ne sont PAS des critères de
présence de signal (le bruit en produit autant) : seul le décodage d'une trame compte.

Usage :
    tools/scan_async.py --freqs 868.15,868.20,868.25,868.30,868.35 --dwell 25 \
        [--host 172.16.0.205] [--out logs/scan_async.json]
"""
from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import pathlib
import re
import time

from aioesphomeapi import APIClient

ROOT = pathlib.Path(__file__).resolve().parent.parent


def key_from_yaml(path: pathlib.Path) -> str:
    text = path.read_text(encoding="utf-8")
    m = re.search(r"api_key:\s*(\S+)", text)
    if not m:
        raise SystemExit("api_key introuvable dans secrets.yaml")
    return m.group(1).strip("\"'")


async def maybe_await(value):
    return await value if inspect.isawaitable(value) else value


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="172.16.0.205")
    ap.add_argument("--freqs", required=True, help="liste séparée par des virgules, en MHz")
    ap.add_argument("--dwell", type=float, default=25.0, help="secondes par palier")
    ap.add_argument("--out", default="logs/scan_async.json")
    args = ap.parse_args()

    key = key_from_yaml(ROOT / "esphome" / "secrets.yaml")
    client = APIClient(args.host, 6053, "", noise_psk=key)
    await client.connect(login=True)

    infos, _ = await client.list_entities_services()
    by_name = {getattr(i, "name", ""): i for i in infos}
    freq_entity = by_name.get("Fréquence CC1101")
    if freq_entity is None:
        raise SystemExit("entité « Fréquence CC1101 » introuvable")

    latest: dict[int, object] = {}

    def on_state(state):
        latest[state.key] = state

    await maybe_await(client.subscribe_states(on_state))
    await asyncio.sleep(2)

    def counter(name: str) -> int:
        st = latest.get(by_name[name].key) if name in by_name else None
        val = getattr(st, "state", None)
        try:
            return int(val)
        except (TypeError, ValueError):
            return 0  # jamais publié (nan) = 0

    results = []
    for freq in [float(f) for f in args.freqs.split(",")]:
        before_valid, before_rejected = counter("Trames valides"), counter("Trames rejetées")
        await maybe_await(client.number_command(freq_entity.key, freq))
        await asyncio.sleep(args.dwell)
        valid, rejected = counter("Trames valides"), counter("Trames rejetées")
        row = {
            "freq_mhz": freq,
            "trames_valides": valid,
            "trames_rejetees": rejected,
            "delta_valides": valid - before_valid,
            "delta_rejetees": rejected - before_rejected,
            "dwell_s": args.dwell,
            "horodatage": time.strftime("%FT%TZ", time.gmtime()),
        }
        results.append(row)
        print(
            f"{freq:8.3f} MHz : valides {valid} (+{row['delta_valides']}), "
            f"rejetées {rejected} (+{row['delta_rejetees']})"
        )

    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"-> {out}")
    await client.disconnect()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
