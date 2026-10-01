#!/usr/bin/env python3
"""Résumé compact d'une fenêtre de capture : trames, cadence, trous, cohérence.

Complement de `eval_frames.py` (qui valide trame par trame) : ce résumé répond aux questions
d'une fenêtre longue — la station a-t-elle émis en continu, à quelle cadence, quels trous, les
valeurs sont-elles restées cohérentes, y a-t-il eu des rejets.

Usage :
    tools/summarize_window.py logs/capture.log [--json logs/resume.json]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import re
import statistics
import sys
from collections import Counter

OK = re.compile(r"V7IN1 OK (\{.*\})$")
RAW = re.compile(r"V7IN1 RAW ([0-9a-f ]+)$")
REJ = re.compile(r"V7IN1 REJ ([^$]*)$")
TS = re.compile(r"^\[(\d\d):(\d\d):(\d\d)\]")
# ESPHome colore ses lignes (chaque ligne finit par une séquence ANSI) : sans ce nettoyage, les
# motifs ancrés en fin de ligne ne correspondent JAMAIS et un log plein de trames passe pour vide.
# C'est exactement le bug qui a fait afficher « AUCUNE trame décodée » sur une fenêtre de 181.
ANSI = re.compile(r"\x1b\[[0-9;]*m")


def secs(h: str, m: str, s: str) -> int:
    return int(h) * 3600 + int(m) * 60 + int(s)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("logfile")
    ap.add_argument("--json")
    args = ap.parse_args()

    path = pathlib.Path(args.logfile)
    if not path.exists():
        raise SystemExit(f"fichier absent : {path}")
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()

    frames, rejects, raw_count = [], [], 0
    for line in lines:
        line = ANSI.sub("", line).rstrip()
        m = TS.match(line)
        if not m:
            continue
        t = secs(*m.groups())
        if (k := OK.search(line)):
            d = json.loads(k.group(1))
            d["_t"] = t
            frames.append(d)
        elif (k := REJ.search(line)):
            rejects.append({"t": t, "raison": k.group(1).strip()})
        elif RAW.search(line):
            raw_count += 1

    if not frames:
        print(f"{path.name} : AUCUNE trame décodée ({len(lines)} lignes)")
        return 1

    times = sorted({f["_t"] for f in frames})           # émissions distinctes (dédoublonnées)
    span = times[-1] - times[0]
    deltas = [b - a for a, b in zip(times, times[1:]) if b - a > 1]
    gaps = [d for d in deltas if d > 30]
    buckets = Counter(t // 600 for t in times)          # par tranche de 10 min

    def span_of(key):
        vals = [f[key] for f in frames if isinstance(f.get(key), (int, float))]
        return (min(vals), max(vals)) if vals else None

    res = {
        "fichier": str(path),
        "lignes": len(lines),
        "trames_decodues": len(frames),
        "emissions_distinctes": len(times),
        "debut": str(dt.timedelta(seconds=times[0])),
        "fin": str(dt.timedelta(seconds=times[-1])),
        "duree_couverte_s": span,
        "cadence_mediane_s": statistics.median(deltas) if deltas else None,
        "cadence_min_s": min(deltas) if deltas else None,
        "cadence_max_s": max(deltas) if deltas else None,
        "trous_sup_30s": sorted(gaps, reverse=True)[:10],
        "rejets": len(rejects),
        "raisons_rejet": Counter(r["raison"] for r in rejects).most_common(5),
        "ids": sorted({f.get("id") for f in frames}),
        "temperature_C": span_of("temp_c"),
        "humidite_pct": span_of("humidity"),
        "vent_kmh": span_of("wind_kmh"),
        "rafale_kmh": span_of("gust_kmh"),
        "pluie_mm": sorted({f.get("rain_mm") for f in frames}),
        "uv": sorted({f.get("uv_index") for f in frames}),
        "lux": span_of("lux"),
        "emissions_par_10min": {f"{k*10}-{k*10+10} min": v for k, v in sorted(buckets.items())},
    }

    print(f"=== {path.name} ===")
    print(f"lignes lues : {len(lines)} | trames décodées : {len(frames)} | "
          f"émissions distinctes : {len(times)}")
    print(f"fenêtre couverte : {res['debut']} → {res['fin']} ({span} s)")
    if deltas:
        print(f"cadence : médiane {res['cadence_mediane_s']:.1f} s "
              f"(min {res['cadence_min_s']}, max {res['cadence_max_s']})")
    print(f"trous > 30 s : {res['trous_sup_30s'] or 'aucun'}")
    print(f"rejets : {len(rejects)} {res['raisons_rejet'] if rejects else ''}")
    print(f"station(s) : {[hex(i) for i in res['ids'] if i is not None]}")
    print(f"T {res['temperature_C']} °C | H {res['humidite_pct']} % | vent {res['vent_kmh']} | "
          f"rafale {res['rafale_kmh']} | pluie {res['pluie_mm']} mm | UV {res['uv']} | lux {res['lux']}")
    print("émissions par tranche de 10 min :")
    for k, v in res["emissions_par_10min"].items():
        print(f"   {k:>10s} : {'#' * min(v, 60)} {v}")

    if args.json:
        pathlib.Path(args.json).write_text(json.dumps(res, ensure_ascii=False, indent=2),
                                           encoding="utf-8")
        print(f"résumé JSON : {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
