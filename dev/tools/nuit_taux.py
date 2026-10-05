#!/usr/bin/env python3
"""Taux de reception reel, mesure par le compteur TX de la station (39 ticks / 20 s = 1,95 tick/s)."""
import json, os, re, datetime as dt
D = "/home/hermes/projets/vevor-7in1/dev/state/nuit_20261005"
P = "jardin_vevor_7_in_1_weather_station_"
def load(n): return json.load(open(os.path.join(D, n + ".json")))[0]

raw = [(s["last_changed"][:19], s["state"]) for s in load(P + "last_raw_frame")]
raw = [(t, s) for t, s in raw if re.match(r"^[0-9a-f]{2}( [0-9a-f]{2}){20}$", str(s))]
FLASH = "2026-10-04T22:25:04"
post = [(t, s) for t, s in raw if t >= FLASH]
def T(s): return dt.datetime.strptime(s, "%Y-%m-%dT%H:%M:%S")

def wind3(s): return s.split()[8:11]

# --- taux global par le compteur TX (sur les trames post-flash) ---
tot_emis = tot_recu = 0
pertes = []
for i in range(1, len(post)):
    t0, s0 = post[i-1]; t1, s1 = post[i]
    tx0 = int(s0.split()[18], 16); tx1 = int(s1.split()[18], 16)
    d = (tx1 - tx0) & 0xFF
    sec = (T(t1) - T(t0)).total_seconds()
    attendu = sec * 1.95
    emis = d / 1.95
    tot_emis += emis; tot_recu += 1
    if abs(emis - attendu) > 2 or d > 60:
        pertes.append((t0, t1, round(sec), d, round(emis, 1), round(attendu, 1)))

print("== Depuis le reflash (%s) ==" % FLASH)
print("trames publiees : %d" % len(post))
print("duree couverte : %s -> %s" % (post[0][0], post[-1][0]))
# emission totale estimee par le compteur TX entre premiere et derniere trame
tx_a = int(post[0][1].split()[18], 16); tx_b = int(post[-1][1].split()[18], 16)
secs = (T(post[-1][0]) - T(post[0][0])).total_seconds()
nbr_emis_modele = sum(((int(post[i][1].split()[18], 16) - int(post[i-1][1].split()[18], 16)) & 0xFF)
                      for i in range(1, len(post))) / 1.95
print("emissions de la station estimees sur l'intervalle (compteur TX) : %.0f" % nbr_emis_modele)
print("taux de reception = %d / %.0f = %.1f %%" % (len(post)-1, nbr_emis_modele, 100*(len(post)-1)/nbr_emis_modele))
print("duree totale %.0f s = %.1f h ; emissions attendues a 20 s : %.0f" % (secs, secs/3600, secs/20))
print("\nIntervalles ou le compteur TX trahit des emissions manquees (>2 s d'ecart) : %d" % len(pertes))
for p in pertes[:12]:
    print("   %s -> %s  (%ss, dt_tx=%d => %.1f emissions, %.1f attendues)" % p)
print("   ... total %d" % len(pertes))

# --- vent/rafale apres le flash ---
print("\n== vent/rafale apres le reflash ==")
z = [t for t, s in post if wind3(s) == ["01", "01", "00"]]
print("trames a vent ET rafale nuls (01 01 00) : %d / %d" % (len(z), len(post)))
nz = [(t, s) for t, s in post if wind3(s) not in (["01", "01", "00"], ["01", "01", "01"])]
print("trames ou b[8..10] n'est ni 01 01 00 ni 01 01 01 : %d" % len(nz))
import collections
print("valeurs b[8..10] observees apres le reflash :", dict(collections.Counter(" ".join(wind3(s)) for _, s in post)))
