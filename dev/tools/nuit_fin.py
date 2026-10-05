#!/usr/bin/env python3
"""Fin de nuit : que s'est-il passe entre 05:00 et 06:31 UTC ?"""
import json, os
D = "/home/hermes/projets/vevor-7in1/dev/state/nuit_20261005"
P = "jardin_vevor_7_in_1_weather_station_"
def load(n): return json.load(open(os.path.join(D, n + ".json")))[0]
def num(x):
    try: return float(x)
    except Exception: return None
cols = {}
FIC = {"valid_frames": P + "valid_frames", "rejected_frames": P + "rejected_frames",
       "rmt_captures": P + "rmt_captures", "duplicates_ignored": P + "duplicates_ignored",
       "last_raw_frame": P + "last_raw_frame", "last_verdict": P + "last_verdict",
       "outdoor_temperature": P + "outdoor_temperature", "esp32_weather_illuminance": "esp32_weather_illuminance"}
for n, f in FIC.items():
    for s in load(f):
        t = s["last_changed"][:19]
        if "2026-10-05T05:00:00" <= t <= "2026-10-05T06:35:00":
            cols.setdefault(t, {})[n] = str(s.get("state"))[:26]
for t in sorted(cols):
    d = cols[t]
    print("%s  val=%-8s rej=%-8s rmt=%-7s dup=%-6s raw=%-26s verdict=%-10s T=%-6s lux=%s" % (
        t, d.get("valid_frames", "-"), d.get("rejected_frames", "-"), d.get("rmt_captures", "-"),
        d.get("duplicates_ignored", "-"), d.get("last_raw_frame", "-"), d.get("last_verdict", "-"),
        d.get("outdoor_temperature", "-"), d.get("esp32_weather_illuminance", "-")))
