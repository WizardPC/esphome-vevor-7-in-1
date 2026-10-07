#!/usr/bin/env python3
"""Evolution of the board counters during the long gaps (does the receiver hear anything?)."""
import json, os
D = "/home/hermes/projets/vevor-7in1/dev/state/nuit_20261005"
P = "jardin_vevor_7_in_1_weather_station_"
def load(n): return json.load(open(os.path.join(D, n + ".json")))[0]
def num(x):
    try: return float(x)
    except Exception: return None

def serie(n, t0, t1):
    h = [(s["last_changed"][:19], num(s.get("state"))) for s in load(P + n)]
    return [(t, v) for t, v in h if v is not None and t0 <= t <= t1]

def report(t0, t1, lab):
    r = dict(serie("rmt_captures", t0, t1))
    j = dict(serie("rejected_frames", t0, t1))
    v = dict(serie("valid_frames", t0, t1))
    ts = sorted(set(r) | set(j) | set(v))
    print("\n--- %s (%s -> %s) ---" % (lab, t0, t1))
    prev = None
    for t in ts:
        d = ""
        if prev:
            parts = []
            for nm, cur, old in (("rmt", r.get(t), prev.get("rmt")), ("rej", j.get(t), prev.get("rej")),
                                 ("val", v.get(t), prev.get("val"))):
                if cur is not None and old is not None:
                    parts.append("%s %+d" % (nm, cur - old))
            d = " | ".join(parts)
        print("  %s  rmt=%-6s rej=%-6s val=%-5s   %s" % (t, r.get(t), j.get(t), v.get(t), d))
        prev = {"rmt": r.get(t, prev.get("rmt") if prev else None),
                "rej": j.get(t, prev.get("rej") if prev else None),
                "val": v.get(t, prev.get("val") if prev else None)}

report("2026-10-05T02:38:00", "2026-10-05T03:00:30", "gap 02:40 -> 02:50")
report("2026-10-05T04:05:00", "2026-10-05T04:40:00", "after reboot 04:09")
report("2026-10-05T05:00:00", "2026-10-05T06:31:30", "end of night (reboot 05:15)")
