#!/usr/bin/env python3
"""Fetch the Home Assistant history (04/10 18:00 UTC -> now)."""
import json, os, sys, time, urllib.request, urllib.error, urllib.parse, datetime

BASE = "http://192.168.2.104"
TOKEN = open("/home/hermes/projets/vevor-7in1/.ha_token").read().strip()
OUT = "/home/hermes/projets/vevor-7in1/dev/state/nuit_20261005"
os.makedirs(OUT, exist_ok=True)
PREFIX = "sensor.jardin_vevor_7_in_1_weather_station_"
ENTS = ["last_raw_frame", "wind_speed", "wind_gust", "wind_direction",
        "outdoor_temperature", "outdoor_humidity", "rain_total", "uv_index",
        "station_id", "tx_counter", "valid_frames", "rejected_frames",
        "rmt_captures", "duplicates_ignored", "last_verdict",
        "sensor.esp32_weather_illuminance"]

def fetch(url):
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + TOKEN})
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read().decode())

start = sys.argv[1] if len(sys.argv) > 1 else "2026-10-04T18:00:00Z"
end = sys.argv[2] if len(sys.argv) > 2 else datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
for e in ENTS:
    eid = e if "." in e else PREFIX + e
    fn = os.path.join(OUT, eid.split(".")[-1] + ".json")
    url = (BASE + "/api/history/period/" + start + "?filter_entity_id=" +
           urllib.parse.quote(eid, safe="") + "&end_time=" + urllib.parse.quote(end, safe="") +
           "&minimal_response&no_attributes")
    for essai in range(4):
        try:
            data = fetch(url); break
        except Exception as ex:
            print("  attempt", essai, eid, ex); time.sleep(5); data = None
    if data is None:
        print("FAIL", eid); continue
    with open(fn, "w") as f:
        json.dump(data, f)
    print("ok", eid.split(".")[-1], len(data[0]) if data else 0, "states")
    time.sleep(0.2)
print("window", start, "->", end, "| files in", OUT)
