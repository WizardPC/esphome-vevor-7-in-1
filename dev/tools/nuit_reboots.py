#!/usr/bin/env python3
"""Nombre de redemarrages depuis le reflash (compteur captures, monotone) + etat des 20 dernieres minutes."""
import json, os, time, urllib.request, urllib.parse, datetime as dt
D = "/home/hermes/projets/vevor-7in1/dev/state/nuit_20261005"
P = "jardin_vevor_7_in_1_weather_station_"
TOKEN = open("/home/hermes/projets/vevor-7in1/.ha_token").read().strip()

cap = json.load(open(os.path.join(D, P + "rmt_captures.json")))[0]
h = [(s["last_changed"][:19], s["state"]) for s in cap]
FLASH = "2026-10-04T22:25:04"
reb = []
prev = None
for t, v in h:
    try: v = float(v)
    except Exception: continue
    if prev is not None and v < prev and t >= FLASH:
        reb.append(t)
    prev = v
print("redemarrages depuis le reflash (compteur captures qui retombe) : %d" % len(reb))
print("  liste :", ", ".join(x[11:] for x in reb))
# ecarts
import datetime
d = [(dt.datetime.strptime(reb[i+1], "%Y-%m-%dT%H:%M:%S") - dt.datetime.strptime(reb[i], "%Y-%m-%dT%H:%M:%S")).total_seconds() for i in range(len(reb)-1)]
print("  ecarts (min) :", [round(x/60, 1) for x in d])

# etat actuel
def get(u):
    req = urllib.request.Request(u, headers={"Authorization": "Bearer " + TOKEN})
    with urllib.request.urlopen(req, timeout=120) as r: return json.loads(r.read().decode())
end = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
start = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=25)).strftime("%Y-%m-%dT%H:%M:%SZ")
for e in ("valid_frames", "rejected_frames", "rmt_captures", "outdoor_temperature"):
    u = ("http://192.168.2.104/api/history/period/" + start + "?filter_entity_id=" +
         urllib.parse.quote(P + e, safe="") + "&end_time=" + urllib.parse.quote(end, safe="") +
         "&minimal_response&no_attributes")
    try:
        hh = get(u)[0]
        print("%-22s %s" % (e, [(x["last_changed"][11:19], x["state"]) for x in hh][-8:]))
    except Exception as ex:
        print(e, "ERREUR", ex)
print("maintenant (UTC) :", end)
