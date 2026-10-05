#!/usr/bin/env python3
"""Details des trames post-flash suspectes : octets theoriquement constants, compagnons +0x80."""
import json, os, re, collections
D = "/home/hermes/projets/vevor-7in1/dev/state/nuit_20261005"
P = "jardin_vevor_7_in_1_weather_station_"
def load(n): return json.load(open(os.path.join(D, n + ".json")))[0]
raw = [(s["last_changed"][:19], s["state"]) for s in load(P + "last_raw_frame")]
raw = [(t, s) for t, s in raw if re.match(r"^[0-9a-f]{2}( [0-9a-f]{2}){20}$", str(s))]
FLASH = "2026-10-04T22:25:04"
post = [(t, [int(x, 16) for x in s.split()]) for t, s in raw if t >= FLASH]
print("valeurs distinctes par position (post-flash) :")
for i in range(21):
    c = collections.Counter(v[i] for _, v in post)
    if len(c) > 1:
        print("  b[%2d] : %s" % (i, dict(sorted(c.items()))))
print("\ntrames ou in[15] != 0x01 :")
for t, v in post:
    if v[15] != 1:
        print("  %s  %s" % (t, " ".join("%02x" % x for x in v)))
print("\ncontexte 22:25 -> 22:35 :")
for t, v in post:
    if "2026-10-04T22:25" <= t <= "2026-10-04T23:11":
        b = list(v)
        for i in (8, 9, 11, 12, 13, 14, 16, 17): b[i] = (b[i]-1) & 0xFF
        print("  %s  %s | vent %.1f rafale %.1f dir %d uv %d lux %d cks %s" % (
            t, " ".join("%02x" % x for x in v), ((b[8] << 8) | b[9]) / 8.333, v[10] / 1.25,
            ((b[11] & 0x0F) << 8) | b[12], (v[15] & 0x1F) - 1, (b[16] << 8) | b[17],
            (sum(v[:19]) & 0xFF) == v[19]))
print("\ntrames post-flash ou une somme de deux octets fait +0x80/+0x80 :")
for t, v in post:
    ref = [0xAA, 0x00, 0x84, 0xCB, 0x16, None, None, None, 0x01, 0x01, 0x00, 0x01, None, 0x01, 0xFF, 0x01, 0x01, 0x01, None, None, None]
    ecarts = [(i, v[i] - ref[i]) for i in range(21) if ref[i] is not None and v[i] != ref[i]]
    if ecarts and len(ecarts) <= 4:
        print("  %s  ecarts=%s  %s" % (t, ecarts, " ".join("%02x" % x for x in v)))
