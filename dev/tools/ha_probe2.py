#!/usr/bin/env python3
import json, urllib.request, urllib.error
TOKEN = open("/home/hermes/projets/vevor-7in1/.ha_token").read().strip()
def raw(url):
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + TOKEN})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:300]

tests = [
 "http://192.168.2.104/api/history/period/2026-10-04T20:00:00Z?filter_entity_id=sensor.jardin_vevor_7_in_1_weather_station_rmt_captures&minimal_response&no_attributes",
 "http://192.168.2.104/api/history/period/2026-10-04T20:00:00Z?filter_entity_id=sensor.jardin_vevor_7_in_1_weather_station_rmt_captures&end_time=2026-10-05T06:40:00Z&minimal_response&no_attributes",
 "http://192.168.2.104/api/history/period/2026-10-05T00:00:00Z?filter_entity_id=sensor.jardin_vevor_7_in_1_weather_station_rmt_captures&minimal_response",
 "http://192.168.2.104/api/history/period/2026-10-05T00:00:00+00:00?filter_entity_id=sensor.jardin_vevor_7_in_1_weather_station_rmt_captures&minimal_response",
 "http://192.168.2.104/api/history/period/2026-10-05T00:00:00Z?filter_entity_id=sensor.jardin_vevor_7_in_1_weather_station_valid_frames",
]
for u in tests:
    st, body = raw(u)
    print(u.split("/period/")[1][:70], "->", st, body[:200].replace("\n", " "))
    print()
