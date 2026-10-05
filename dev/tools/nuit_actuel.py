#!/usr/bin/env python3
"""Etat des 35 dernieres minutes (le signal est-il revenu au lever du jour ?)."""
import json, time, urllib.request, urllib.parse, datetime as dt
TOKEN = open("/home/hermes/projets/vevor-7in1/.ha_token").read().strip()
P = "sensor.jardin_vevor_7_in_1_weather_station_"
def q(s): return urllib.parse.quote(s, safe="")
def get(u, essais=6):
    for k in range(essais):
        try:
            req = urllib.request.Request(u, headers={"Authorization": "Bearer " + TOKEN})
            with urllib.request.urlopen(req, timeout=120) as r:
                d = json.loads(r.read().decode()); return d if d else [[]]
        except Exception as ex:
            time.sleep(5)
    return [[]]
now = dt.datetime.now(dt.timezone.utc)
start = (now - dt.timedelta(minutes=35)).strftime("%Y-%m-%dT%H:%M:%SZ")
end = now.strftime("%Y-%m-%dT%H:%M:%SZ")
print("fenetre", start, "->", end)
for e in ("valid_frames", "rmt_captures", "last_raw_frame", "last_verdict", "outdoor_temperature", "esp32_weather_illuminance"):
    eid = e if e.startswith("esp32") else P + e
    h = get("http://192.168.2.104/api/history/period/" + start + "?filter_entity_id=" + q(eid) +
            "&end_time=" + q(end) + "&minimal_response&no_attributes")[0]
    print("%s :" % e)
    for s in h[-14:]:
        print("   ", s["last_changed"][11:19], s["state"][:40])
