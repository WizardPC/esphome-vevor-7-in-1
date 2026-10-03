#!/usr/bin/env python3
"""Qualifie les paquets reçus par le CC1101 : bruit de fond ou vraie station ?

Aucune conclusion non mesurée : tout est calculé à partir d'une capture de logs
série (`esphome logs --device /dev/ttyACM0`) et des constantes du protocole.

Usage: tools/analyze_noise.py logs/serial_*.log [--json logs/noise_analysis.json]

Critère principal : en mode packet, le CC1101 ne remplit la FIFO qu'après un
**verrou de syncword**. Un syncword de 16 bits se verrouille sur le bruit à la
cadence théorique   baud / 2^16   (soit ~0,18 /s à 11 505 bauds), alors qu'un
syncword de 32 bits donne ~2,7e-6 /s (négligeable). Donc :
  - cadence observée de l'ordre de baud/2^16  -> faux verrous sur le bruit ;
  - cadence observée << baud/2^16             -> vrais paquets d'un émetteur.
On y ajoute la structure de trame attendue (b[0]=0xAA, b[1]=0x00, checksum).
"""
import argparse
import json
import math
import re
import sys
from collections import Counter

RAW_RE = re.compile(
    r"V7IN1 RAW ((?:[0-9a-f]{2} )+[0-9a-f]{2}) rssi=(-?[\d.]+) "
    r"freq_offset=(-?[\d.]+) lqi=(\d+)")
TS_RE = re.compile(r"\[(\d\d):(\d\d):(\d\d)\.(\d+)\]")
REJ_RE = re.compile(r"V7IN1 REJ (\S+)")
OK_RE = re.compile(r"V7IN1 OK ")

FRAME_BYTES = 21
SYMBOL_RATE = 11505.0          # bauds effectifs (DRATE_E=8, DRATE_M=208)
SYNC_BITS = 16                 # sync_mode 16/16 -> 2 octets (CA 54)


def ts_to_s(ts):
    if not ts:
        return None
    h, m, s, frac = ts
    return int(h) * 3600 + int(m) * 60 + int(s) + int(frac) / (10 ** len(frac))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("logfile")
    ap.add_argument("--json", default="logs/noise_analysis.json")
    args = ap.parse_args()

    frames, rejects, oks = [], Counter(), 0
    for line in open(args.logfile, errors="replace"):
        m = RAW_RE.search(line)
        if m:
            ts = TS_RE.search(line)
            frames.append({
                "t": (":".join(ts.groups()[:3]) if ts else None),
                "t_s": ts_to_s(ts.groups()) if ts else None,
                "bytes": [int(b, 16) for b in m.group(1).split()],
                "rssi": float(m.group(2)),
                "freq_offset": float(m.group(3)),
                "lqi": int(m.group(4)),
            })
        r = REJ_RE.search(line)
        if r:
            rejects[r.group(1)] += 1
        if OK_RE.search(line):
            oks += 1

    n = len(frames)
    out = {
        "logfile": args.logfile,
        "nb_paquets_recus": n,
        "nb_trames_valides": oks,
        "motifs_rejet": dict(rejects),
        "tailles": sorted({len(f["bytes"]) for f in frames}),
        "rssi": {"min": min((f["rssi"] for f in frames), default=None),
                 "max": max((f["rssi"] for f in frames), default=None),
                 "moyenne": round(sum(f["rssi"] for f in frames) / n, 1) if n else None},
        "lqi_valeurs": sorted({f["lqi"] for f in frames}),
        "tetes": ["%02x %02x" % (f["bytes"][0], f["bytes"][1]) for f in frames],
    }

    # Cadence observée
    ts_list = [f["t_s"] for f in frames if f["t_s"] is not None]
    if len(ts_list) >= 2:
        span = ts_list[-1] - ts_list[0]
        gaps = [round(b - a, 3) for a, b in zip(ts_list, ts_list[1:])]
        out["fenetre_s"] = round(span, 3)
        out["cadence_paquets_par_s"] = round((len(ts_list) - 1) / span, 4)
        out["intervalles_s"] = gaps

    # Taux de faux verrou théorique
    out["faux_verrou_theorique_par_s"] = {
        "%d bits" % SYNC_BITS: round(SYMBOL_RATE / (2 ** SYNC_BITS), 4),
        "32 bits": round(SYMBOL_RATE / (2 ** 32), 9),
    }

    # Structure de trame attendue (protocole Vevor) + uniformité des octets
    allb = [b for f in frames for b in f["bytes"]]
    if allb:
        hist = Counter(allb)
        p = 1.0 / 256
        entropy = -sum((c / len(allb)) * math.log2(c / len(allb))
                       for c in hist.values())
        out["octets"] = {
            "total": len(allb),
            "valeurs_distinctes": len(hist),
            "entropie_bits": round(entropy, 3),
            "entropie_max_bits": 8.0,
            "fraction_octets_>=0x80": round(sum(1 for b in allb if b >= 0x80) / len(allb), 3),
        }
        out["trame_valide_possible"] = False  # tranché ci-dessous

    # Verdict
    verdict, raisons = "INDETERMINE", []
    if n == 0:
        verdict = "PAS_DE_PAQUET"
        raisons.append("aucun paquet reçu pendant la capture")
    else:
        entetes_ok = sum(1 for f in frames if f["bytes"][0] == 0xAA and f["bytes"][1] == 0x00)
        raisons.append("%d/%d paquets avec l'en-tête attendu AA 00" % (entetes_ok, n))
        raisons.append("%d trames valides (checksum+compteur OK)" % oks)
        rate = out.get("cadence_paquets_par_s")
        theo = out["faux_verrou_theorique_par_s"]["16 bits"]
        if rate is not None:
            raisons.append("cadence %.3f paquet/s vs faux verrou 16 bits %.3f/s (32 bits %.2e/s)"
                           % (rate, theo, out["faux_verrou_theorique_par_s"]["32 bits"]))
            if oks == 0 and entetes_ok == 0 and rate > theo / 4:
                verdict = "BRUIT_SEUL"
                raisons.append("cadence compatible avec des faux verrous de syncword sur le bruit "
                               "et aucune trame conforme -> aucun émetteur Vevor sur ce canal")
            elif oks > 0:
                verdict = "TRAMES_VALIDES"
            else:
                verdict = "A_QUALIFIER"
    out["verdict"] = verdict
    out["raisons"] = raisons

    with open(args.json, "w") as fh:
        json.dump(out, fh, indent=2, ensure_ascii=False)
    # Trace brute exigée par MISSION.md (append : jamais de réécriture de l'historique).
    if frames:
        with open("logs/raw_frames.jsonl", "a") as fh:
            for f in frames:
                fh.write(json.dumps({"source": args.logfile, **f}, ensure_ascii=False) + "\n")
        print("Trames brutes ajoutées à logs/raw_frames.jsonl (%d lignes)" % n)
    print(json.dumps(out, indent=2, ensure_ascii=False))
    print("\nRapport écrit dans", args.json)
    return 0 if verdict in ("TRAMES_VALIDES", "BRUIT_SEUL", "PAS_DE_PAQUET") else 1


if __name__ == "__main__":
    sys.exit(main())
