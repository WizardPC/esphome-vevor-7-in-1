#!/usr/bin/env python3
"""Reads and prints the state of ALL board entities through the native API.

Unlike `scan_freq.py --list`, which only gives entity names, several diagnostics need state
values: "Fréquence CC1101" (the `number` entity has `restore_value: true`, so its restored boot
value competes with the YAML frequency) and the "Captures RMT" / "Trames valides" / "Doublons
ignorés" counters.

Note: `subscribe_states` does not deliver states immediately, so wait for the first one
before concluding.

Usage:
 dev/tools/read_state.py [--host <board-ip>] [--json logs/state.json]

Return codes:
    0  at least one entity state received;
    2  technical failure (connection, exception);
    3  NULL MEASUREMENT: no state received — nothing was measured.
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
            if isinstance(v, float) and v != v:  # NaN = never published
                v = None
            values[name] = v
        return {"entites": len(dev.keys), "recues": len(dev.state), "valeurs": values}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default=os.environ.get("VEVOR_HOST"),
                    required="VEVOR_HOST" not in os.environ,
                    help="board IP address. Fallback: VEVOR_HOST environment variable, or dev/tools/find_esp32.py to discover it")
    ap.add_argument("--port", type=int, default=6053)
    ap.add_argument("--key", default=None)
    ap.add_argument("--json", default=None, help="JSON file (relative = project root)")
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
