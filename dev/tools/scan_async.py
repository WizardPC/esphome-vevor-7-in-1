#!/usr/bin/env python3
"""Frequency sweep on the ASYNCHRONOUS path, judged by the board counters.

Unlike scan_freq.py (written for packet mode and its RSSI), this sweep uses only what the
asynchronous path actually publishes: the "Trames valides / Trames rejetées" counters and the
component heartbeats ("captures=…, trames=…, plus longue=…"), read through the native API.
Capture rate and pulse durations are NOT signal criteria (noise produces just as many): only
decoding a frame counts.

Usage:
 dev/tools/scan_async.py --freqs 868.15,868.20,868.25,868.30,868.35 --dwell 25 \
        [--host <board-ip>] [--out logs/scan_async.json]
"""
from __future__ import annotations

import os
import argparse
import asyncio
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _common import (atomic_write_json, key_from_yaml,  # noqa: E402
                     maybe_await)

from aioesphomeapi import APIClient


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default=os.environ.get("VEVOR_HOST"),
                    required="VEVOR_HOST" not in os.environ,
                    help="board IP address. Fallback: VEVOR_HOST environment variable, or dev/tools/find_esp32.py to discover it")
    ap.add_argument("--freqs", required=True, help="comma-separated list, in MHz")
    ap.add_argument("--dwell", type=float, default=25.0, help="seconds per step")
    ap.add_argument("--out", default="logs/scan_async.json")
    args = ap.parse_args()

    key = key_from_yaml()
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
            return 0  # never published (nan) = 0

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

    print(f"-> {atomic_write_json(args.out, results)}")
    await client.disconnect()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
