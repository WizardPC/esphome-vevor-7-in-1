#!/usr/bin/env python3
"""Sweeps the CC1101 frequency live through the ESPHome native API and measures the signal.

Main autonomy tool: no need to rebuild/reflash to search for the station. It drives the
firmware's `number` entity "Fréquence CC1101" and reads the received frame count (valid +
rejected) and the RSSI at each step.

Usage:
    scan_freq.py --host <board-ip> [--key KEY] [--start 867.8 --stop 868.6 --step 0.05]
                 [--dwell 25] [--out scan.json]
    scan_freq.py --host <board-ip> --list          # lists the exposed entities
    scan_freq.py --host <board-ip> --set 868.30    # just sets the frequency

A step must last at least ~25 s: the station only emits one burst every 20 s.

Return codes:
    0  sweep measured; a total of 0 frames is a RESULT ("no frame"), not a failure;
    2  technical failure: connection, exception, or frequency write NOT accepted (read back != requested);
    3  NULL MEASUREMENT: the "Trames valides" entity is missing / no state received — nothing was measured.
"""
from __future__ import annotations

import argparse
import math
import pathlib
import statistics
import sys
import time
import asyncio

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _common import (Device, RC_ERREUR, RC_MESURE_NULLE, RC_OK,  # noqa: E402
                     VALID_RE, atomic_write_json, resolve_key)


async def do_list(dev: Device) -> None:
    print(f"# {dev.info.name} — esphome {dev.info.esphome_version}")
    for name, k in sorted(dev.keys.items()):
        print(f"{k:>6}  {name}")


async def do_set(dev: Device, mhz: float) -> int:
    """Sets the frequency AND READS IT BACK. A read-back catches a lost command (wrong entity
    key). The entity is `optimistic: true`: if it does not read back the requested value,
    the command did not arrive."""
    dev.set_freq(mhz)
    await asyncio.sleep(1.5)
    got = dev.get("Fréquence CC1101")
    print(f"# fréquence réglée sur {mhz} MHz — entité relue : {got}")
    try:
        ok = got is not None and abs(float(got) - mhz) <= 0.001
    except (TypeError, ValueError):
        ok = False
    if not ok:
        print(f"# ERREUR : la carte n'a PAS pris la valeur (lue {got!r}) — voir FREQ_RE",
              file=sys.stderr)
        return RC_ERREUR
    return RC_OK


async def scan(dev: Device, start: float, stop: float, step: float,
               dwell: float, settle: float) -> list[dict] | None:
    """Returns the measured steps, or None if NOTHING could be measured (missing entity)."""
    # Without the "Trames valides" entity no counter is readable: refuse to conclude
    # (RC_MESURE_NULLE in main).
    if not dev.has(VALID_RE):
        print("# MESURE NULLE : entité « Trames valides » absente — aucun compteur à lire",
              file=sys.stderr)
        return None
    freqs = []
    f = start
    while f <= stop + 1e-9:
        freqs.append(round(f, 4))
        f += step
    results = []
    for mhz in freqs:
        dev.set_freq(mhz)
        await asyncio.sleep(settle)
        v0, r0, _ = dev.counts()
        rssis: list[float] = []
        t_end = time.monotonic() + dwell
        while time.monotonic() < t_end:
            await asyncio.sleep(0.5)
            r = dev.get("RSSI")
            try:
                if r is not None and not math.isnan(float(r)):
                    rssis.append(float(r))
            except (TypeError, ValueError):
                pass
        v1, r1, _ = dev.counts()
        row = {
            "freq_mhz": mhz,
            "frames": (v1 - v0) + (r1 - r0),
            "valid": v1 - v0,
            "rejected": r1 - r0,
            "rssi_max": round(max(rssis), 1) if rssis else None,
            "rssi_mean": round(statistics.fmean(rssis), 1) if rssis else None,
        }
        results.append(row)
        print(
            f"{mhz:8.3f} MHz  trames={int(row['frames']):3d} "
            f"(valides={int(row['valid']):3d} rejetées={int(row['rejected']):3d})  "
            f"rssi_max={row['rssi_max']}  rssi_moy={row['rssi_mean']}",
            flush=True,
        )
    return results


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", required=True)
    ap.add_argument("--port", type=int, default=6053)
    ap.add_argument("--key", default=None)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--set", type=float, dest="set_mhz")
    ap.add_argument("--start", type=float, default=867.8)
    ap.add_argument("--stop", type=float, default=868.6)
    ap.add_argument("--step", type=float, default=0.05)
    ap.add_argument("--dwell", type=float, default=25.0, help="seconds per step (>=25 recommended)")
    ap.add_argument("--settle", type=float, default=1.0)
    ap.add_argument("--out", default=None, help="JSON report (relative = project root)")
    args = ap.parse_args()

    key = resolve_key(args.key)

    async def run() -> tuple[int, list[dict] | None]:
        async with Device(args.host, args.port, key) as dev:
            if args.list:
                await do_list(dev)
                return RC_OK, []
            if args.set_mhz is not None:
                return await do_set(dev, args.set_mhz), []
            rows = await scan(dev, args.start, args.stop, args.step, args.dwell, args.settle)
            return (RC_MESURE_NULLE if rows is None else RC_OK), rows

    try:
        rc, rows = asyncio.run(run())
    except SystemExit:
        raise
    except Exception as exc:
        print(f"# ERREUR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return RC_ERREUR

    if not rows:
        if rc == RC_MESURE_NULLE:
            print("# MESURE NULLE — rien n'a été mesuré (pas de compteur lisible)", file=sys.stderr)
        return rc

    best = max(rows, key=lambda r: (r["frames"], -(r["rssi_mean"] or -999)))
    print(f"\n# meilleur palier: {best['freq_mhz']} MHz "
          f"({int(best['frames'])} trames, rssi_moy={best['rssi_mean']})")
    total = sum(r["frames"] for r in rows)
    if total == 0:
        print("# AUCUNE TRAME sur toute la plage (mesure faite) : vérifier SPI/alim, puis "
              "déviation, bande passante, syncword, câblage et antenne "
              "(voir MISSION.md § ordre de diagnostic)")
    if args.out:
        p = atomic_write_json(args.out, {"rows": rows, "best": best})
        print(f"# rapport écrit (atomique): {p}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
