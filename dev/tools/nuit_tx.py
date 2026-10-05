#!/usr/bin/env python3
"""Le compteur TX avance-t-il de +39 par emission ? Et que dit-il aux reprises apres un trou ?"""
import json, os, re, datetime as dt, collections
D = "/home/hermes/projets/vevor-7in1/dev/state/nuit_20261005"
P = "jardin_vevor_7_in_1_weather_station_"
def load(n): return json.load(open(os.path.join(D, n + ".json")))[0]
raw = [(s["last_changed"][:19], s["state"]) for s in load(P + "last_raw_frame")]
raw = [(t, s) for t, s in raw if re.match(r"^[0-9a-f]{2}( [0-9a-f]{2}){20}$", str(s))]
def T(s): return dt.datetime.strptime(s, "%Y-%m-%dT%H:%M:%S")
FLASH = "2026-10-04T22:25:04"
post = [(t, s.split()) for t, s in raw if t >= FLASH]

d = collections.Counter()
for i in range(1, len(post)):
    dt_s = (T(post[i][0]) - T(post[i-1][0])).total_seconds()
    delta = (int(post[i][1][18], 16) - int(post[i-1][1][18], 16)) & 0xFF
    d[(round(dt_s), delta)] += 1
print("== (intervalle s, delta compteur TX) les plus frequents ==")
for k, v in d.most_common(12): print("   %s : %d" % (k, v))
print("\n== reprises apres un trou > 300 s ==")
for i in range(1, len(post)):
    dt_s = (T(post[i][0]) - T(post[i-1][0])).total_seconds()
    if dt_s > 300:
        delta = (int(post[i][1][18], 16) - int(post[i-1][1][18], 16)) & 0xFF
        print("   %s -> %s (%5.0f s) : delta=%3d -> emissions entieres plausibles : %s" %
              (post[i-1][0][11:], post[i][0][11:], dt_s, delta,
               [k for k in range(1, 40) if abs((39*k) % 256 - delta) <= 2]))
