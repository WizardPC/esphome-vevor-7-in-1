#!/usr/bin/env python3
"""Probe the firmware counters over the API, WITHOUT depending on the log stream.

A log capture can show no `V7IN1 RAW` line either because the receiver demodulates nothing or
because the log subscription dropped. The "Valid frames" / "Rejected frames" counters are state
entities that advance on any packet, independent of the log stream; comparing the two resolves
the doubt.

Usage:
 dev/tools/count_probe.py --host <board-ip> [--seconds 30] [--json logs/count_probe.json]

Return codes: 0 measurement done (a delta of 0 packets is the result "no frame"); 2 technical
error (connection, exception); 3 empty measurement: no entity state received
(0 received != 0 packets).
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
        # subscribe_states has not delivered entity states yet: reading counters now returns 0 and
        # the "delta" would equal the absolute counter. Wait for a state, else refuse to conclude.
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

        # 0 entities received means NOTHING was measured, NOT "no packet": without this distinct
        # verdict a "frozen counter" reads as radio silence by mistake.
        if n_states0 == 0 or len(dev.state) == 0:
            verdict = "NULL MEASUREMENT (no entity state received — nothing was measured)"
            rc = RC_MESURE_NULLE
        elif delta > 0:
            verdict = "RECEPTION ALIVE"
            rc = RC_OK
        else:
            verdict = "NO FRAME (counters frozen over the window — negative result)"
            rc = RC_OK
        return rc, {
            "fenetre_s": round(t1 - t0, 1),
            # Number of entity states received: 0 means the device delivered nothing, so a
            # "frozen counter" does NOT mean "no packet" — the measurement is null.
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
    ap.add_argument("--json", default=None, help="JSON report (relative = project root)")
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
        print(f"# report written (atomic): {atomic_write_json(a.json, rep)}")
    if rc == RC_MESURE_NULLE:
        print("# NULL MEASUREMENT — nothing was measured (return code 3)", file=sys.stderr)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
