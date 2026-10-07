#!/usr/bin/env python3
import json, os, re, collections
D = "/home/hermes/projets/vevor-7in1/dev/state/nuit_20261005"
P = "jardin_vevor_7_in_1_weather_station_"
def load(n): return json.load(open(os.path.join(D, n + ".json")))[0]
def num(x):
    try: return float(x)
    except Exception: return None

raw = [(s["last_changed"][:19], s["state"]) for s in load(P + "last_raw_frame")]
raw = [(t, s) for t, s in raw if re.match(r"^[0-9a-f]{2}( [0-9a-f]{2}){20}$", str(s))]
bad = [(t, s) for t, s in raw if s.split()[8:11] == ["02", "80", "80"]]
print("raw frames: %d | 02 80 80: %d" % (len(raw), len(bad)))
FLASH = "2026-10-04T22:25:04"
print("02 80 80 BEFORE the reflash:", sum(1 for t, _ in bad if t < FLASH))
print("02 80 80 AFTER the reflash:", sum(1 for t, _ in bad if t >= FLASH))
for t, _ in bad:
    if t >= FLASH: print("   AFTER:", t)
print("hourly distribution of 02 80 80:", dict(sorted(collections.Counter(t[:13] for t, _ in bad).items())))
print()
print("first raw frame:", raw[0][0], "| last:", raw[-1][0])
print("raw frames after the reflash:", sum(1 for t, _ in raw if t >= FLASH))

print("\n=== SEGMENTS BETWEEN RESTARTS (valid_frames) ===")
h = [(s["last_changed"][:19], num(s.get("state"))) for s in load(P + "valid_frames")]
h = [(t, v) for t, v in h if v is not None]
seg, segs = [], []
prev = None
for t, v in h:
    if prev is not None and v < prev:
        segs.append(seg); seg = []
    seg.append((t, v)); prev = v
segs.append(seg)
tot = 0
for s in segs:
    if len(s) < 1: continue
    mx = max(v for _, v in s)
    tot += mx
    print("  %s -> %s : max valid=%g  (%d states)" % (s[0][0], s[-1][0], mx, len(s)))
print("  TOTAL valid frames accumulated over the window:", tot)

print("\n=== last_verdict: observed values ===")
lv = load(P + "last_verdict")
c = collections.Counter(str(s.get("state")) for s in lv)
for k, v in c.most_common(15): print("   %-40s %d" % (k[:40], v))
