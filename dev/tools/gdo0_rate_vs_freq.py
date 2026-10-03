#!/usr/bin/env python3
"""Quantifie l'activité de la sortie GDO0 du CC1101 par palier de fréquence.

Pourquoi : en mode série asynchrone, ce qui reste mesurable est le débit de transitions de
GDO0 (le slicer sort du bruit démodulé). Avant de conclure « aucun signal », il faut savoir si
cette activité dépend de la fréquence : si elle est identique à 867,000 MHz (hors bande, aucun
émetteur attendu), à 868,050 (brouilleur identifié le 30/09) et à 868,300 (fréquence nominale),
alors l'activité observée est du bruit interne à la puce et ne peut PAS servir de détecteur.

Usage:
 dev/tools/gdo0_rate_vs_freq.py logs/gdo0_freq_*.log [--out logs/gdo0_rate_vs_freq.json]

Chaque fichier doit contenir des lignes « sonde GDO0 : N transition(s) en U us » et des lignes
« captures=N (+d), trames=T, dernières impulsions=P, plus longue=L ».
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import statistics
import sys

TRANS_RE = re.compile(r"sonde GDO0 : (\d+) transition\(s\) en (\d+) us")
CAP_RE = re.compile(r"captures=(\d+) \(\+(\d+)\), trames=(\d+), dernières impulsions=(\d+), plus longue=(\d+)")
NOIMP_RE = re.compile(r"aucune impulsion depuis (\d+) s \(captures=(\d+), trames=(\d+)\)")
EXTRACT_RE = re.compile(r"trame extraite")
FREQ_RE = re.compile(r"gdo0_freq_([0-9.]+)\.log$")


def analyse(path: pathlib.Path) -> dict:
    txt = path.read_text(encoding="utf-8", errors="replace")
    trans = [(int(n), int(u)) for n, u in TRANS_RE.findall(txt)]
    rates = [n * 1e6 / u for n, u in trans if u]  # transitions par seconde
    caps = CAP_RE.findall(txt)
    m = FREQ_RE.search(path.name)
    return {
        "log": path.name,
        "freq_mhz": float(m.group(1)) if m else None,
        "sondes": len(trans),
        "transitions_moy": round(statistics.fmean(rates), 1) if rates else None,
        "transitions_min": round(min(rates), 1) if rates else None,
        "transitions_max": round(max(rates), 1) if rates else None,
        "captures_fin": int(caps[-1][0]) if caps else None,
        "captures_delta": sum(int(c[1]) for c in caps),
        "trames_fin": int(caps[-1][2]) if caps else 0,
        "impulsions_max": max((int(c[4]) for c in caps), default=None),
        "extractions": len(EXTRACT_RE.findall(txt)),
        "lignes_sans_impulsion": len(NOIMP_RE.findall(txt)),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("logs", nargs="+")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    rows = []
    for pat in args.logs:
        for p in sorted(pathlib.Path(".").glob(pat)) if any(c in pat for c in "*?[") else [pathlib.Path(pat)]:
            if p.exists():
                rows.append(analyse(p))
    rows.sort(key=lambda r: (r["freq_mhz"] is None, r["freq_mhz"]))

    print(f"{'fréquence':>10}  {'sondes':>6}  {'trans/s moy':>11}  {'min':>7}  {'max':>7}  "
          f"{'captures':>8}  {'impuls.max':>10}  {'extractions':>11}")
    for r in rows:
        print(f"{r['freq_mhz'] if r['freq_mhz'] is not None else '-':>10}  {r['sondes']:>6}  "
              f"{r['transitions_moy'] if r['transitions_moy'] is not None else '-':>11}  "
              f"{r['transitions_min'] if r['transitions_min'] is not None else '-':>7}  "
              f"{r['transitions_max'] if r['transitions_max'] is not None else '-':>7}  "
              f"{r['captures_delta']:>8}  {r['impulsions_max'] if r['impulsions_max'] is not None else '-':>10}  "
              f"{r['extractions']:>11}")

    moyennes = [r["transitions_moy"] for r in rows if r["transitions_moy"] is not None]
    verdict = None
    if len(moyennes) >= 2:
        mini, maxi = min(moyennes), max(moyennes)
        verdict = ("activité GDO0 INDÉPENDANTE de la fréquence (écart < 20 %) : sortie non "
                   "discriminante, inutilisable comme détecteur de signal"
                   if mini and (maxi - mini) / mini < 0.20 else
                   "activité GDO0 DÉPENDANTE de la fréquence : la chaîne passe bien la bande "
                   "et la sonde reste exploitable")
        print("\nVERDICT : " + verdict)
    else:
        print("\nVERDICT : pas assez de paliers exploitables pour trancher")

    if args.out:
        pathlib.Path(args.out).write_text(
            json.dumps({"rows": rows, "verdict": verdict}, indent=1, ensure_ascii=False), encoding="utf-8")
        print(f"# rapport écrit: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
