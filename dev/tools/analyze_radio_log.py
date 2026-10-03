#!/usr/bin/env python3
"""Résume les lignes « RADIO … » (lecture SPI des registres du CC1101) d'une capture de logs.

Ces lignes sont produites par le composant vevor_7in1 (itération 9) : à chaque battement de cœur
(5 s) il lit par SPI le RSSI, MARCSTATE, PKTSTATUS et FREQ2/1/0, sans rien écrire dans la puce.
Ce script en tire la distribution (plancher de bruit, état de la puce, porteuse détectée) et
recoupe avec les captures RMT et les trames décodées.

Références sur cette même carte (mode packet, 30/09) : plancher −106,2 dBm, RSSI max −95,5 dBm.

Usage : tools/analyze_radio_log.py logs/iter9_rssi_300s_20260930.log
"""

from __future__ import annotations

import collections
import re
import statistics
import sys
from pathlib import Path

RADIO = re.compile(
    r"RADIO RSSI=(?P<rssi>-?[\d.]+) dBm \(brut (?P<raw>0x[0-9A-Fa-f]{2})\) \| "
    r"MARCSTATE=(?P<marc>0x[0-9A-Fa-f]{2}) (?P<marcname>\S+) \| PKTSTATUS=(?P<pkt>0x[0-9A-Fa-f]{2}) "
    r"CS=(?P<cs>\d) SFD=(?P<sfd>\d) \| FREQ=(?P<freq>[\d.]+) MHz .* \| VERSION=(?P<ver>0x[0-9A-Fa-f]{2})"
)
CAPS = re.compile(r"captures RMT=(\d+)")


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    path = Path(sys.argv[1])
    text = path.read_text(encoding="utf-8", errors="replace")

    rows = [m.groupdict() for m in RADIO.finditer(text)]
    if not rows:
        print(f"{path} : aucune ligne RADIO (firmware sans instrumentation SPI ? capture vide ?)")
        print(f"  lignes V7IN1 OK : {text.count('V7IN1 OK')}")
        return 1

    rssi = [float(r["rssi"]) for r in rows]
    caps = [int(m.group(1)) for m in CAPS.finditer(text)]
    print(f"fichier            : {path}")
    print(f"échantillons RADIO : {len(rows)}")
    print(f"RSSI               : moy={statistics.fmean(rssi):.1f} min={min(rssi):.1f} max={max(rssi):.1f} dBm")
    print(f"  histogramme      : " + ", ".join(
        f"{v}dBm×{n}" for v, n in sorted(collections.Counter(round(x) for x in rssi).items())))
    print(f"  référence carte  : plancher −106,2 dBm / max −95,5 dBm (mode packet, 30/09)")
    print(f"MARCSTATE          : {dict(collections.Counter(r['marcname'] for r in rows))}")
    print(f"PKTSTATUS CS=1     : {sum(1 for r in rows if r['cs'] == '1')} / {len(rows)}")
    print(f"PKTSTATUS SFD=1    : {sum(1 for r in rows if r['sfd'] == '1')} / {len(rows)}")
    freqs = {r["freq"] for r in rows}
    vers = collections.Counter(r["ver"] for r in rows)
    print(f"fréquence (registres) : {sorted(freqs)} MHz")
    print(f"VERSION            : {dict(vers)} (0x14 attendu)")
    if caps:
        print(f"captures RMT       : {caps[0]} → {caps[-1]} ({caps[-1] - caps[0]} pendant la fenêtre)")
    print(f"trames décodées    : V7IN1 OK ×{text.count('V7IN1 OK')}, "
          f"lignes RAW ×{text.count('V7IN1 RAW')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
