#!/usr/bin/env python3
"""Check: the PREVIOUS night (03/10 22:00 -> 04/10 06:00 UTC) and the day of 04/10."""
import json, time, urllib.request, urllib.parse, datetime as dt, collections
TOKEN = open("/home/hermes/projets/vevor-7in1/.ha_token").read().strip()
P = "sensor.jardin_vevor_7_in_1_weather_station_"
def q(s): return urllib.parse.quote(s, safe="")
def get(u, essais=6):
    for k in range(essais):
        try:
            req = urllib.request.Request(u, headers={"Authorization": "Bearer " + TOKEN})
            with urllib.request.urlopen(req, timeout=120) as r:
                d = json.loads(r.read().decode())
                return d if d else [[]]
        except Exception as ex:
            time.sleep(5)
    print("   FAIL", u[:80]); return [[]]

def hist(eid, t0, t1):
    u = ("http://192.168.2.104/api/history/period/" + t0 + "?filter_entity_id=" + q(eid) +
         "&end_time=" + q(t1) + "&minimal_response&no_attributes")
    return get(u)[0]

def compte(eid, t0, t1):
    return [(s["last_changed"][:19], s["state"]) for s in hist(eid, t0, t1)]

print("== PREVIOUS NIGHT 03/10 22:00 -> 04/10 06:00 UTC ==")
h = compte(P + "last_raw_frame", "2026-10-03T22:00:00Z", "2026-10-04T06:00:00Z")
import re
frames = [t for t, s in h if re.match(r"^[0-9a-f]{2}( [0-9a-f]{2}){20}$", str(s))]
print("  raw frames: %d" % len(frames))
if frames: print("  first %s last %s" % (frames[0], frames[-1]))
vv = compte(P + "valid_frames", "2026-10-03T22:00:00Z", "2026-10-04T06:00:00Z")
print("  valid_frames : %s" % [(t[11:], s) for t, s in vv][:10])
rr = compte(P + "rmt_captures", "2026-10-03T22:00:00Z", "2026-10-04T06:00:00Z")
print("  captures: %s" % [(t[11:], s) for t, s in rr][:6], "...", [(t[11:], s) for t, s in rr][-3:])

print("\n== DAY 04/10 (2-h slices, raw frames) ==")
d0 = dt.datetime(2026, 10, 4, 0, 0)
for k in range(12):
    t0 = (d0 + dt.timedelta(hours=2*k)).strftime("%Y-%m-%dT%H:%M:%SZ")
    t1 = (d0 + dt.timedelta(hours=2*k+2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    n = len([1 for t, s in compte(P + "last_raw_frame", t0, t1)
             if re.match(r"^[0-9a-f]{2}( [0-9a-f]{2}){20}$", str(s))])
    print("  %s -> %s: %3d frames  (expected ~360 at 1/20 s)" % (t0[11:16], t1[11:16], n))
    time.sleep(0.3)
