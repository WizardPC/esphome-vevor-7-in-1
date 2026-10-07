#!/usr/bin/env python3
"""Family of fabrications: +0x80 companions. gust<wind statistics over the day 04/10."""
import json, os, re, collections
D = "/home/hermes/projets/vevor-7in1/dev/state/nuit_20261005"
def parse(s):
    v = [int(x, 16) for x in s.split()] if re.match(r"^[0-9a-f]{2}( [0-9a-f]{2}){20}$", str(s)) else None
    if not v: return None
    b = list(v)
    for i in (8, 9, 11, 12, 13, 14, 16, 17): b[i] = (b[i]-1) & 0xFF
    return dict(v=v, wind=((b[8] << 8) | b[9]) / 8.333, gust=v[10] / 1.25,
                uv=(v[15] & 0x1F) - 1, lux=(b[16] << 8) | b[17], b15=v[15], b17=v[17])
jour = json.load(open(os.path.join(D, "journee_0410.json")))
print("== day 04/10 (n=%d) ==" % len(jour))
print("  frames where b[8..10] == 01 01 80:")
for t, s in jour:
    if " ".join(s.split()[8:11]) == "01 01 80":
        f = parse(s)
        print("     %s  %s   b[15]=%02x (0x01 expected) b[17]=%02x" % (t, s, f["b15"], f["b17"]))
print("  frames where b[8..10] == 02 80 80 and b[15] != 01 / b[17] != 01:")
n = 0
for t, s in jour:
    if " ".join(s.split()[8:11]) == "02 80 80":
        f = parse(s)
        if f["b15"] != 1 or f["b17"] != 1:
            n += 1
            print("     %s  %s  b[15]=%02x b[17]=%02x" % (t, s, f["b15"], f["b17"]))
print("     total:", n)
g = [(t, parse(s)["wind"], parse(s)["gust"]) for t, s in jour if parse(s) and parse(s)["gust"] < parse(s)["wind"] - 0.5]
print("  day: gust < wind by more than 0.5 km/h: %d frames out of %d (%.1f %%)" % (len(g), len(jour), 100*len(g)/len(jour)))
print("     examples:", g[:8])
F = {"P": "jardin_vevor_7_in_1_weather_station_"}
post = [(s["last_changed"][:19], s["state"]) for s in json.load(open(os.path.join(D, F["P"] + "last_raw_frame.json")))[0]]
post = [(t, parse(s)) for t, s in post if parse(s) and t >= "2026-10-04T22:25:04"]
gw = [(t, f["wind"], f["gust"]) for t, f in post if f["gust"] < f["wind"] - 0.5]
print("  after the reflash: gust < wind: %d frames out of %d" % (len(gw), len(post)))
print("     ", gw)
