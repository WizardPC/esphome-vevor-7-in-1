#!/usr/bin/env python3
"""Anomalies de champ, apres le reflash (22:25:04 UTC)."""
import json, os, re
D = "/home/hermes/projets/vevor-7in1/dev/state/nuit_20261005"
P = "jardin_vevor_7_in_1_weather_station_"
def load(n): return json.load(open(os.path.join(D, n + ".json")))[0]
raw = [(s["last_changed"][:19], s["state"]) for s in load(P + "last_raw_frame")]
raw = [(t, s) for t, s in raw if re.match(r"^[0-9a-f]{2}( [0-9a-f]{2}){20}$", str(s))]
FLASH = "2026-10-04T22:25:04"
post = [(t, [int(x, 16) for x in s.split()]) for t, s in raw if t >= FLASH]

def dec(v):
    b = list(v)
    for i in (8, 9, 11, 12, 13, 14, 16, 17): b[i] = (b[i] - 1) & 0xFF
    return dict(id=(v[2] << 8) | v[3], temp=((v[5] << 8) | v[6]) - 500, hum=v[7],
                wind=((b[8] << 8) | b[9]) / 8.333, gust=v[10] / 1.25,
                dir=((b[11] & 0x0F) << 8) | b[12], rain=((b[13] << 8) | b[14]) * 0.233,
                uv=(v[15] & 0x1F) - 1, lux=((b[16] << 8) | b[17]), tx=v[18],
                cks=(sum(v[:19]) & 0xFF) == v[19], b4=v[4], b17=v[17], b10=v[10])

F = [(t, dec(v), v) for t, v in post]
print("== Apres le reflash : %d trames ==" % len(F))
print("periodes couvertes : %s -> %s" % (F[0][0], F[-1][0]))
flags = []
prev = None
for t, f, v in F:
    if not f["cks"]: flags.append((t, "somme invalide", f))
    if f["gust"] < f["wind"] - 0.5: flags.append((t, "rafale < vent (%.1f / %.1f)" % (f["wind"], f["gust"]), f))
    if f["hum"] > 100 or f["hum"] < 30: flags.append((t, "humidite %d" % f["hum"], f))
    if f["dir"] > 359: flags.append((t, "direction %d" % f["dir"], f))
    if f["uv"] < 0 or f["uv"] > 16: flags.append((t, "uv %d" % f["uv"], f))
    if f["lux"] == 0 and 8 <= int(t[11:13]) < 15: flags.append((t, "lux 0 en journee", f))
    if prev:
        if abs(f["temp"] - prev["temp"]) > 10: flags.append((t, "saut temperature %.1f -> %.1f" % (prev["temp"]/10, f["temp"]/10), f))
        if abs(f["hum"] - prev["hum"]) > 8: flags.append((t, "saut humidite %d -> %d" % (prev["hum"], f["hum"]), f))
        if f["rain"] < prev["rain"] - 0.01: flags.append((t, "pluie en baisse %.1f -> %.1f" % (prev["rain"], f["rain"]), f))
        if f["id"] != prev["id"]: flags.append((t, "id different %d -> %d" % (prev["id"], f["id"]), f))
        if f["uv"] != prev["uv"] and abs(f["uv"] - prev["uv"]) > 2: flags.append((t, "uv %d -> %d" % (prev["uv"], f["uv"]), f))
    prev = f
print("signalements : %d" % len(flags))
for t, m, f in flags[:40]: print("   %s  %s   [temp %.1f hum %d vent %.1f raf %.1f dir %d uv %d lux %d]" %
      (t, m, f["temp"]/10, f["hum"], f["wind"], f["gust"], f["dir"], f["uv"], f["lux"]))

print("\n== Etendues post-reflash ==")
for k in ("temp", "hum", "dir", "wind", "gust", "uv", "lux"):
    vals = [f[k] for _, f, _ in F]
    print("  %-5s min %.1f max %.1f" % (k, min(vals), max(vals)))
print("  pluie :", sorted(set(round(f["rain"], 3) for _, f, _ in F)))
print("  b[4] distincts :", sorted(set(f["b4"] for _, f, _ in F)))
print("  b[17] distincts :", sorted(set(f["b17"] for _, f, _ in F)))
print("\n== trame a vent>0 et rafale 0 (gust<wind) ==")
for t, f, v in F:
    if f["gust"] < 0.1 and f["wind"] > 1:
        print("  ", t, " ".join("%02x" % x for x in v))
