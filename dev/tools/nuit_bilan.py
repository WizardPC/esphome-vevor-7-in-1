#!/usr/bin/env python3
"""Bilan chiffre par segment (entre redemarrages) + journee complete du 04/10."""
import json, os, re, urllib.request, urllib.parse, collections
BASE = "http://192.168.2.104"
TOKEN = open("/home/hermes/projets/vevor-7in1/.ha_token").read().strip()
D = "/home/hermes/projets/vevor-7in1/dev/state/nuit_20261005"
P = "jardin_vevor_7_in_1_weather_station_"
def load(n): return json.load(open(os.path.join(D, n + ".json")))[0]
def num(x):
    try: return float(x)
    except Exception: return None

def fetch(url, essais=4):
    import time
    for k in range(essais):
        try:
            req = urllib.request.Request(url, headers={"Authorization": "Bearer " + TOKEN})
            with urllib.request.urlopen(req, timeout=180) as r:
                return json.loads(r.read().decode())
        except Exception as ex:
            print("   (essai %d: %s)" % (k, ex)); time.sleep(6)
    raise SystemExit("echec")

# --- journee complete : comptage des 02 80 80 ---
url = (BASE + "/api/history/period/2026-10-04T00:00:00Z?filter_entity_id=" +
       urllib.parse.quote(P + "last_raw_frame", safe="") +
       "&end_time=2026-10-04T22:24:00Z&minimal_response&no_attributes")
h = fetch(url)[0]
h = [(s["last_changed"][:19], s["state"]) for s in h]
h = [(t, s) for t, s in h if re.match(r"^[0-9a-f]{2}( [0-9a-f]{2}){20}$", str(s))]
bad = [t for t, s in h if s.split()[8:11] == ["02", "80", "80"]]
print("JOURNEE 04/10 (00:00 -> 22:24 UTC) : %d trames brutes, %d trames 02 80 80" % (len(h), len(bad)))
print("  premiere :", bad[0] if bad else "-", "| derniere :", bad[-1] if bad else "-")
print("  par heure UTC :", dict(sorted(collections.Counter(t[:13] for t in bad).items())))
# autres valeurs anormales notables
for trio in ("01 01 80", "01 80 80", "02 80 80"):
    n = sum(1 for t, s in h if " ".join(s.split()[8:11]) == trio)
    print("   b[8..10] == %s : %d" % (trio, n))

# --- segments post-flash ---
print("\n=== SEGMENTS post-reflash (22:25:04 UTC = 00:25 Paris) ===")
def serie(n):
    hh = [(s["last_changed"][:19], num(s.get("state"))) for s in load(P + n)]
    return [(t, v) for t, v in hh if v is not None]
vs, rs, cs = serie("valid_frames"), serie("rejected_frames"), serie("rmt_captures")
FLASH = "2026-10-04T22:25:04"
seg, segs = [], []
prev = None
for t, v in vs:
    if prev is not None and v < prev:
        segs.append(seg); seg = []
    seg.append((t, v)); prev = v
segs.append(seg)
tval = trej = trmt = 0
print("  %-21s %-21s %6s %6s %6s" % ("debut", "fin", "val", "rej", "rmt"))
for s in segs:
    t0, t1 = s[0][0], s[-1][0]
    if t1 < FLASH: continue
    mv = max(v for _, v in s)
    mr = max([v for t, v in rs if t0 <= t <= t1] or [0])
    mc = max([v for t, v in cs if t0 <= t <= t1] or [0])
    tval += mv; trej += mr; trmt += mc
    print("  %-21s %-21s %6g %6g %6g" % (t0, t1, mv, mr, mc))
print("  TOTAL : valides=%g rejetees=%g captures=%g  -> rejets/captures = %.2f" % (tval, trej, trmt, trej/trmt if trmt else 0))
print("  (reference avant correctif, journee 04/10 00:00->22:24 : a calculer ci-dessous)")
b = serie("valid_frames"); r = serie("rejected_frames"); c = serie("rmt_captures")
print("  avant reflash : valid_frames %g -> %g" % (b[0][1], b[-1][1] if b[-1][0] < FLASH else 0))
