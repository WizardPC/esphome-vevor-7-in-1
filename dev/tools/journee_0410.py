#!/usr/bin/env python3
"""Journee complete du 04/10 : comptage des trames fabriquees, par tranches de 2 h."""
import json, os, re, time, urllib.request, urllib.error, urllib.parse, collections, datetime as dt
BASE = "http://192.168.2.104"
TOKEN = open("/home/hermes/projets/vevor-7in1/.ha_token").read().strip()
P = "sensor.jardin_vevor_7_in_1_weather_station_"
def q(s): return urllib.parse.quote(s, safe="")
def fetch(eid, t0, t1, essais=5):
    u = (BASE + "/api/history/period/" + t0 + "?filter_entity_id=" + q(eid) +
         "&end_time=" + q(t1) + "&minimal_response&no_attributes")
    for k in range(essais):
        try:
            req = urllib.request.Request(u, headers={"Authorization": "Bearer " + TOKEN})
            with urllib.request.urlopen(req, timeout=180) as r:
                d = json.loads(r.read().decode())
                return d if d else [[]]
        except Exception as ex:
            time.sleep(4)
    print("    ECHEC", t0, t1)
    return [[]]

trames = []
d0 = dt.datetime(2026, 10, 4, 0, 0)
for k in range(12):
    t0 = (d0 + dt.timedelta(hours=2*k)).strftime("%Y-%m-%dT%H:%M:%SZ")
    t1 = (d0 + dt.timedelta(hours=2*k+2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    h = fetch(P + "last_raw_frame", t0, t1)[0]
    got = [(s["last_changed"][:19], s["state"]) for s in h
           if re.match(r"^[0-9a-f]{2}( [0-9a-f]{2}){20}$", str(s["state"]))]
    got = [ (t, s) for t, s in got if t != (d0 + dt.timedelta(hours=2*k)).strftime("%Y-%m-%dT%H:%M:%S") or k == 0 ]
    trames += got
    print("  %s -> %s : %d trames" % (t0[11:16], t1[11:16], len(got)))
    time.sleep(0.5)

bad = [t for t, s in trames if s.split()[8:11] == ["02", "80", "80"]]
print("\nJOURNEE 04/10 : %d trames brutes (a partir de %s), %d en 02 80 80" % (len(trames), trames[0][0] if trames else "-", len(bad)))
if bad:
    print("  premiere %s  derniere %s" % (bad[0], bad[-1]))
    print("  par heure UTC :", dict(sorted(collections.Counter(t[:13] for t in bad).items())))
for trio in ("01 01 80", "01 80 80", "02 80 80", "01 01 00"):
    print("  b[8..10]==%s : %d" % (trio, sum(1 for t, s in trames if " ".join(s.split()[8:11]) == trio)))
json.dump(trames, open("/home/hermes/projets/vevor-7in1/dev/state/nuit_20261005/journee_0410.json", "w"))
