#!/usr/bin/env python3
"""Analysis of the night 04/10 22:26 UTC -> 05/10 06:31 UTC (Paris time: 00:26 -> 08:31)."""
import json, os, re
D = "/home/hermes/projets/vevor-7in1/dev/state/nuit_20261005"
P = "jardin_vevor_7_in_1_weather_station_"

def load(n):
    return json.load(open(os.path.join(D, n + ".json")))[0]

def ts(s):
    return s["last_changed"][:19]

def num(x):
    try: return float(x)
    except Exception: return None

def parse(hexs):
    parts = hexs.split()
    if len(parts) != 21: return None
    try: v = [int(p, 16) for p in parts]
    except Exception: return None
    b = list(v)
    for i in (8, 9, 11, 12, 13, 14, 16, 17): b[i] = (b[i] - 1) & 0xFF
    f = {}
    f["id"] = (v[2] << 8) | v[3]
    f["temp"] = ((v[5] << 8) | v[6]) - 500
    f["hum"] = v[7]
    f["wind_raw"] = (b[8] << 8) | b[9]
    f["wind"] = f["wind_raw"] / 8.333
    f["gust"] = v[10] / 1.25
    f["dir"] = ((b[11] & 0x0F) << 8) | b[12]
    f["rain"] = (((b[13] << 8) | b[14])) * 0.233
    f["uv"] = (v[15] & 0x1F) - 1
    lux = (b[16] << 8) | b[17]
    f["lux"] = (lux & 0x7FFF) * 10 if lux & 0x8000 else lux
    f["tx"] = v[18]
    f["cks"] = sum(v[:19]) & 0xFF
    f["cks_ok"] = (f["cks"] == v[19])
    f["b"] = " ".join("%02x" % x for x in v)
    f["w3"] = "%02x %02x %02x" % (v[8], v[9], v[10])
    return f

raw = [(ts(s), s["state"]) for s in load(P + "last_raw_frame")
       if re.match(r"^[0-9a-f]{2}( [0-9a-f]{2}){20}$", str(s["state"]))]

# Initial state (first point = state at window start): ignore it for the counts
frames = []
for t, s in raw:
    f = parse(s)
    if f: f["t"] = t; frames.append(f)

# ---- 1. Fabrications ------------------------------------------------
bad = [f for f in frames if f["w3"] == "02 80 80"]
# incoherence with neighbours: non-zero wind or gust while both before AND after are 0/0
inc = []
for i, f in enumerate(frames):
    if f["wind"] == 0 and f["gust"] == 0: continue
    prev = frames[i-1] if i else None
    nxt = frames[i+1] if i+1 < len(frames) else None
    if prev and nxt and prev["wind"] == 0 and prev["gust"] == 0 and nxt["wind"] == 0 and nxt["gust"] == 0:
        inc.append((f["t"], f["b"]))

# ---- 2. Reception ---------------------------------------------------
print("ANALYSED WINDOW:", frames[0]["t"], "->", frames[-1]["t"], "(%d raw frames)" % len(frames))
import datetime as dt
def T(s): return dt.datetime.strptime(s, "%Y-%m-%dT%H:%M:%S")
ivs = [(T(frames[i+1]["t"]) - T(frames[i]["t"])).total_seconds() for i in range(len(frames)-1)]
seuil = 20
print("\n-- Cadence --")
print("intervals: median %.1f s ; <=40 s: %d ; >60 s: %d" %
      (sorted(ivs)[len(ivs)//2], sum(1 for x in ivs if x <= 40), sum(1 for x in ivs if x > 60)))
gaps = sorted(((ivs[i], frames[i]["t"], frames[i+1]["t"]) for i in range(len(ivs)) if ivs[i] > 60), reverse=True)
print("longest gaps:")
for g in gaps[:8]: print("   %6.0f s  %s -> %s" % g)

# ---- 3. Field anomalies --------------------------------------------
print("\n-- Fabrications --")
print("frames b[8..10]==02 80 80:", len(bad))
for f in bad[:6]: print("   ", f["t"], f["b"])
print("wind/gust non-zero framed by 0/0:", len(inc))
for x in inc[:10]: print("   ", x)

print("\n-- Field ranges (raw frames) --")
for k in ("temp", "hum", "dir", "rain", "uv", "lux", "id"):
    vals = [f[k] for f in frames]
    print("  %-5s min %s max %s" % (k, min(vals), max(vals)))
# backward jumps
prev = None
sauts = []
for f in frames:
    if prev:
        if f["temp"] != prev["temp"]: sauts.append((f["t"], "temp", prev["temp"]/10, f["temp"]/10))
        if f["rain"] < prev["rain"] - 0.001: sauts.append((f["t"], "rain", prev["rain"], f["rain"]))
        if abs(f["dir"] - prev["dir"]) > 60: sauts.append((f["t"], "dir", prev["dir"], f["dir"]))
    prev = f
print("\n-- Jumps (temp change, rain decrease, direction >60 deg): %d --" % len(sauts))
for x in sauts[:25]: print("   ", x)
print("   ... total", len(sauts))
