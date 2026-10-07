#!/usr/bin/env python3
"""Summarizes a set of sweep captures (one file per frequency step).

Each step is judged on what matters: the number of frames REALLY extracted from the demodulated
stream (component "trame extraite" line), not the RMT capture count — noise produces those too.
The "captures" and "longest" counters are reported to diagnose the instrument, not to
conclude about the signal.

Usage:
 dev/tools/sweep_summary.py "logs/sweep1_frozen/*.log" --out logs/sweep1_summary.json
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

FREQ_RE = re.compile(r"sweepas_([0-9.]+)\.log$")
CAP_RE = re.compile(r"captures=(\d+) \(\+(\d+)\), frames=(\d+), dernières pulses=(\d+), longest=(\d+)")


def analyse(p: pathlib.Path) -> dict:
    txt = p.read_text(encoding="utf-8", errors="replace")
    caps = CAP_RE.findall(txt)
    lignes = [l for l in txt.splitlines() if l.strip()]
    m = FREQ_RE.search(p.name)
    return {
        "log": p.name,
        "freq_mhz": float(m.group(1)) if m else None,
        "extraites": txt.count("trame extraite"),
        "trames_raw": txt.count("V7IN1 RAW"),
        "trames_valides": txt.count("V7IN1 OK"),
        "captures_fin": int(caps[-1][0]) if caps else None,
        "captures_delta": sum(int(c[1]) for c in caps),
        "trames_compteur": int(caps[-1][2]) if caps else 0,
        "pulses_max": max((int(c[4]) for c in caps), default=None),
        "horodatage_debut": lignes[0][1:9] if lignes and lignes[0].startswith("[") else None,
        "horodatage_fin": lignes[-1][1:9] if lignes and lignes[-1].startswith("[") else None,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("glob")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    rows = [analyse(p) for p in sorted(pathlib.Path(".").glob(args.glob))]
    rows.sort(key=lambda r: (r["freq_mhz"] is None, r["freq_mhz"]))

    print(f"{'MHz':>8}  {'extracted':>9}  {'capt.delta':>10}  {'pulses.max':>8}  {'start':>8}  {'end':>8}")
    for r in rows:
        print(f"{r['freq_mhz'] if r['freq_mhz'] is not None else '-':>8}  {r['extraites']:>9}  "
              f"{r['captures_delta']:>10}  {r['pulses_max'] if r['pulses_max'] is not None else '-':>8}  "
              f"{r['horodatage_debut'] or '-':>8}  {r['horodatage_fin'] or '-':>8}")

    total_ext = sum(r["extraites"] for r in rows)
    total_cap = sum(r["captures_delta"] for r in rows)
    avec_captures = [r["freq_mhz"] for r in rows if r["captures_delta"]]
    print(f"\nTOTAL extracted={total_ext} over {len(rows)} steps ; cumulative RMT captures={total_cap}")
    print(f"steps with at least one RMT capture: {len(avec_captures)}/{len(rows)} "
          f"({', '.join(str(f) for f in avec_captures if f is not None)})")
    print("VERDICT: " + ("NO frame extracted over the whole swept range"
                          if total_ext == 0 else f"{total_ext} frame(s) extracted — to examine"))

    if args.out:
        pathlib.Path(args.out).write_text(
            json.dumps({"rows": rows, "total_extraites": total_ext,
                        "captures_rmt_cumulees": total_cap}, indent=1, ensure_ascii=False),
            encoding="utf-8")
        print(f"# report written: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
