#!/usr/bin/env python3
"""Chronologie : compteurs (reboots) + repartition horaire des trames et des anomalies."""
import json, os, re, collections
D = "/home/hermes/projets/vevor-7in1/dev/state/nuit_20261005"
P = "jardin_vevor_7_in_1_weather_station_"
def load(n): return json.load(open(os.path.join(D, n + ".json")))[0]
def num(x):
    try: return float(x)
    except Exception: return None

print("=== RESETS DE COMPTEURS (rouge = reboot de la carte) ===")
for n in ("valid_frames", "rejected_frames", "rmt_captures", "duplicates_ignored", "tx_counter"):
    h = [(s["last_changed"][:19], num(s.get("state"))) for s in load(P + n)]
    h = [(t, v) for t, v in h if v is not None]
    res = []
    for i in range(1, len(h)):
        if h[i][1] < h[i-1][1]:
            res.append((h[i][0], h[i-1][1], h[i][1], h[i-1][0]))
    print("\n%s : %d etats ; remises a zero : %d" % (n, len(h), len(res)))
    for t, a, b, ta in res[:20]:
        print("   %s : %g (a %s) -> %g" % (t, a, ta, b))
    if h: print("   dernier etat :", h[-1])

print("\n=== TRANCHES DE COMPTEURS (fin de fenetre) ===")
for n in ("valid_frames", "rejected_frames", "rmt_captures", "duplicates_ignored"):
    h = [(s["last_changed"][:19], num(s.get("state"))) for s in load(P + n)]
    h = [(t, v) for t, v in h if v is not None]
    for lo, hi, lab in (("2026-10-04T22:20", "2026-10-04T23:59", "apres reflash 22:26 UTC"),
                        ("2026-10-05T00:00", "2026-10-05T06:35", "nuit 00:00->maintenant"),
                        ("2026-10-04T20:26", "2026-10-04T22:20", "avant reflash (ref 139)")):
        seg = [(t, v) for t, v in h if lo <= t <= hi]
        if seg: print("  %-28s %-12s : %g -> %g  (+%g)" % (n, lab, seg[0][1], seg[-1][1], seg[-1][1]-seg[0][1]))
