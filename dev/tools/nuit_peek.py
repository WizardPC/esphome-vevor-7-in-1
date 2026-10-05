#!/usr/bin/env python3
import json, os
D = "/home/hermes/projets/vevor-7in1/dev/state/nuit_20261005"
P = "jardin_vevor_7_in_1_weather_station_"
def load(n):
    return json.load(open(os.path.join(D, n + ".json")))[0]
for n in [P + "last_raw_frame", P + "valid_frames", P + "rejected_frames",
          P + "rmt_captures", P + "last_verdict", "esp32_weather_illuminance"]:
    h = load(n)
    print("==", n, len(h))
    for s in h[:3] + h[-3:]:
        print("   ", s.get("last_changed"), "|", repr(s.get("state"))[:130])
