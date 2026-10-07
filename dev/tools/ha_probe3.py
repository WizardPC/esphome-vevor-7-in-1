#!/usr/bin/env python3
import json, urllib.request, urllib.error, urllib.parse
TOKEN = open("/home/hermes/projets/vevor-7in1/.ha_token").read().strip()
P = "sensor.jardin_vevor_7_in_1_weather_station_"
def raw(u):
    req = urllib.request.Request(u, headers={"Authorization": "Bearer " + TOKEN})
    try:
        with urllib.request.urlopen(req, timeout=180) as r: return r.status, len(r.read())
    except urllib.error.HTTPError as e: return e.code, e.read().decode()[:200]
q = lambda eid: urllib.parse.quote(eid, safe="")
for end in ["2026-10-04T06:00:00Z", "2026-10-04T12:00:00Z", "2026-10-04T18:00:00Z", "2026-10-04T22:24:00Z"]:
    u = ("http://192.168.2.104/api/history/period/2026-10-04T00:00:00Z?filter_entity_id=" + q(P+"last_raw_frame") +
         "&end_time=" + q(end) + "&minimal_response&no_attributes")
    print(end, raw(u))
u = ("http://192.168.2.104/api/history/period/2026-10-04T00:00:00Z?filter_entity_id=" + q(P+"last_raw_frame") +
     "&minimal_response&no_attributes")
print("without end_time", raw(u))
