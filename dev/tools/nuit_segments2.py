#!/usr/bin/env python3
"""Segments entre redemarrages, cote carte (fichiers locaux uniquement)."""
import json, os
D = "/home/hermes/projets/vevor-7in1/dev/state/nuit_20261005"
P = "jardin_vevor_7_in_1_weather_station_"
def load(n): return json.load(open(os.path.join(D, n + ".json")))[0]
def num(x):
    try: return float(x)
    except Exception: return None
def serie(n):
    h = [(s["last_changed"][:19], num(s.get("state"))) for s in load(P + n)]
    return [(t, v) for t, v in h if v is not None]

vs, rs, cs, ds = serie("valid_frames"), serie("rejected_frames"), serie("rmt_captures"), serie("duplicates_ignored")
FLASH = "2026-10-04T22:25:04"
seg, segs, prev = [], [], None
for t, v in vs:
    if prev is not None and v < prev:
        segs.append(seg); seg = []
    seg.append((t, v)); prev = v
segs.append(seg)

def mx(s, t0, t1):
    v = [x for t, x in s if t0 <= t <= t1]
    return max(v) if v else 0

print("=== SEGMENTS (valid_frames) — %d redemarrages ===" % (len(segs)-1))
print("  %-21s %-21s %5s %6s %6s %5s %s" % ("debut", "fin", "val", "rej", "rmt", "dup", "duree"))
tot = [0, 0, 0, 0]
for s in segs:
    t0, t1 = s[0][0], s[-1][0]
    row = (mx(s, t0, t1), mx(rs, t0, t1), mx(cs, t0, t1), mx(ds, t0, t1))
    avant = t1 < FLASH
    if not avant:
        for i in range(4): tot[i] += row[i]
    print("  %-21s %-21s %5g %6g %6g %5g %s%s" % (t0, t1, row[0], row[1], row[2], row[3],
          "", "  [AVANT reflash]" if avant else ""))
print("\nTOTAL depuis le reflash : valides=%g rejetees=%g captures=%g doublons=%g" % tuple(tot))
print("  rejets/captures = %.3f   ; rejets/valides = %.2f" % (tot[1]/tot[2] if tot[2] else 0, tot[1]/tot[0] if tot[0] else 0))

# idem avant le reflash, sur la meme base (dernier segment non redemarre : 18:00->22:24)
s = [x for x in segs if x[-1][0] < FLASH][-1]
t0, t1 = s[0][0], s[-1][0]
print("\nAVANT reflash (segment %s -> %s, non redemarre pendant 4 h 25) :" % (t0[11:], t1[11:]))
print("  valides=%g rejetees=%g captures=%g" % (mx(s, t0, t1), mx(rs, t0, t1), mx(cs, t0, t1)))
