#!/usr/bin/env python3
"""Résumé compact d'une fenêtre de capture : trames, cadence, trous, cohérence, VERDICT.

Complément de `eval_frames.py` (qui valide trame par trame) : ce résumé répond aux questions
d'une fenêtre longue — la station a-t-elle émis en continu, à quelle cadence, quels trous, les
valeurs sont-elles restées cohérentes, y a-t-il eu des rejets.

UN RÉSUMÉ NE DOIT JAMAIS CONTREDIRE SON RAPPORT. D'où deux changements de fond :
  * `--rapport <rapport.json>` (sortie d'`eval_frames.py`) REPREND le `verdict` et les
    `reasons_fail` du rapport indépendant : le résumé porte le MÊME verdict, et quand le
    rapport dit FAIL, le résumé cite les mêmes motifs et sort en code 1 ;
  * le champ « rejets » du firmware est renommé `rejets_firmware` (et
    `raisons_rejet_firmware`) : c'est un comptage des lignes `V7IN1 REJ` DU FIRMWARE, ce
    n'est PAS le verdict du décodeur indépendant. Les deux mesurent des choses différentes.
En complément, le résumé ajoute `wind_dir_deg` (plage des directions) et `valeurs_hors_plage`,
deux anomalies structurellement invisibles dans l'ancien format.

Usage :
    tools/summarize_window.py logs/capture.log [--rapport evidence/rapport.json]
                                 [--json evidence/resume.json] [--txt evidence/resume.txt]

Code retour :
    0  résumé écrit, verdict PASS (ou « aucune trame » sans rapport : résultat négatif) ;
    1  verdict FAIL (le rapport — ou les contrôles internes — dit FAIL) ;
    3  MESURE NULLE : fichier de log absent ou vide — rien n'a été mesuré.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import re
import statistics
import sys
from collections import Counter

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _common import (ANSI, ROOT, RC_MESURE_NULLE, RC_OK, TS_RE,  # noqa: E402
                     atomic_write_json, atomic_write_text)

# Motifs spécifiques au FLUX V7IN1 (ancrés en fin de ligne après nettoyage ANSI).
OK = re.compile(r"V7IN1 OK (\{.*\})$")
RAW = re.compile(r"V7IN1 RAW ([0-9a-f ]+)$")
REJ = re.compile(r"V7IN1 REJ ([^$]*)$")

# Vocabulaire IDENTIQUE à eval_frames.py (les deux doivent motiver pareil).
MOTIF_PLUIE = "pluie décroissante"
MOTIF_IMPLAUSIBLE = "valeurs implausibles (ou incohérence lux/UV)"


def plausibility_of(frame: dict) -> list[str]:
    """Réutilise la porte de plausibilité d'`eval_frames.py` (import tardif : évite toute
    dépendance circulaire) sur une trame publiée par le firmware."""
    try:
        from eval_frames import plausibility
        return plausibility(frame)
    except Exception:
        # Repli minimal : ne jamais laisser une exception masquer une anomalie évidente.
        probs = []
        d = frame.get("wind_dir_deg")
        if isinstance(d, (int, float)) and not 0 <= d <= 359:
            probs.append(f"direction hors plage: {d}°")
        r = frame.get("rain_mm")
        if isinstance(r, (int, float)) and r < 0:
            probs.append("pluie négative")
        return probs


def secs(h: str, m: str, s: str) -> int:
    return int(h) * 3600 + int(m) * 60 + int(s)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("logfile")
    ap.add_argument("--rapport", default=None,
                    help="rapport eval_frames.py apparié : son verdict et ses motifs sont repris")
    ap.add_argument("--json", default=None, help="résumé JSON (relatif = racine du projet)")
    ap.add_argument("--txt", default=None, help="résumé texte lisible (relatif = racine du projet)")
    args = ap.parse_args()

    path = pathlib.Path(args.logfile)
    if not path.is_absolute():
        path = ROOT / path
    if not path.exists():
        print(f"# MESURE NULLE — fichier absent : {path}", file=sys.stderr)
        return RC_MESURE_NULLE
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if not any(line.strip() for line in lines):
        print(f"# MESURE NULLE — fichier vide ({path}) : rien n'a été mesuré", file=sys.stderr)
        return RC_MESURE_NULLE

    frames, rejects, raw_count = [], [], 0
    for line in lines:
        line = ANSI.sub("", line).rstrip()
        m = TS_RE.match(line)
        if not m:
            continue
        t = secs(m.group(1)[:2], m.group(1)[3:5], m.group(1)[6:8])
        if (k := OK.search(line)):
            try:
                d = json.loads(k.group(1))
            except json.JSONDecodeError:
                continue
            d["_t"] = t
            frames.append(d)
        elif (k := REJ.search(line)):
            rejects.append({"t": t, "raison": k.group(1).strip()})
        elif RAW.search(line):
            raw_count += 1

    out_lines: list[str] = []

    def say(text: str = "") -> None:
        print(text)
        out_lines.append(text)

    # --- Rapport apparié (source du verdict) --------------------------------
    rapport = None
    if args.rapport:
        rp = pathlib.Path(args.rapport)
        if not rp.is_absolute():
            rp = ROOT / rp
        if not rp.exists():
            print(f"# ERREUR : rapport apparié absent : {rp}", file=sys.stderr)
            return 2
        rapport = json.loads(rp.read_text(encoding="utf-8", errors="replace"))

    if not frames:
        say(f"=== {path.name} ===")
        say(f"lignes lues : {len(lines)} | AUCUNE TRAME décodée | rejets firmware : {len(rejects)}")
        res = {
            "fichier": args.logfile,
            "lignes": len(lines),
            "trames_decodues": 0,
            "verdict": "AUCUNE TRAME",
            "motifs_fail": [],
        }
        if rapport:
            res["rapport"] = args.rapport
            res["rapport_logfile"] = rapport.get("logfile")
            res["rapport_verdict"] = rapport.get("verdict")
            res["verdict"] = rapport.get("verdict", res["verdict"])
            res["motifs_fail"] = list(rapport.get("reasons_fail") or [])
        if args.json:
            atomic_write_json(args.json, res)
            say(f"résumé JSON : {args.json}")
        if args.txt:
            atomic_write_text(args.txt, "\n".join(out_lines) + "\n")
        if res["verdict"] == "FAIL":
            print("# VERDICT : FAIL (repris du rapport) — " + "; ".join(res["motifs_fail"]),
                  file=sys.stderr)
            return 1
        print("# AUCUNE TRAME : mesure faite, résultat négatif (code 0)", file=sys.stderr)
        return RC_OK

    times = sorted({f["_t"] for f in frames})           # émissions distinctes (dédoublonnées)
    span = times[-1] - times[0]
    deltas = [b - a for a, b in zip(times, times[1:]) if b - a > 1]
    gaps = [d for d in deltas if d > 30]
    buckets = Counter(t // 600 for t in times)          # par tranche de 10 min

    def span_of(key):
        vals = [f[key] for f in frames if isinstance(f.get(key), (int, float))]
        return (min(vals), max(vals)) if vals else None

    # Anomalies propres au résumé (indépendantes du rapport) — vocabulaire d'eval_frames.
    rain = [f.get("rain_mm") for f in frames if isinstance(f.get("rain_mm"), (int, float))]
    pluie_decroissante = any(y < x for x, y in zip(rain, rain[1:]))
    hors: set[str] = set()
    for f in frames:
        for p in plausibility_of(f):
            hors.add(p)

    propres_fail: list[str] = []
    if pluie_decroissante:
        propres_fail.append(MOTIF_PLUIE)
    if hors:
        propres_fail.append(MOTIF_IMPLAUSIBLE)

    # Verdict : le rapport apparié prime ; sinon les anomalies internes décident.
    if rapport is not None:
        verdict = rapport.get("verdict", "FAIL")
        motifs = list(rapport.get("reasons_fail") or [])
    else:
        verdict = "FAIL" if propres_fail else "PASS"
        motifs = propres_fail

    res = {
        "fichier": args.logfile,
        "lignes": len(lines),
        "trames_decodues": len(frames),
        "emissions_distinctes": len(times),
        "debut": str(dt.timedelta(seconds=times[0])),
        "fin": str(dt.timedelta(seconds=times[-1])),
        "duree_couverte_s": span,
        "cadence_mediane_s": statistics.median(deltas) if deltas else None,
        "cadence_min_s": min(deltas) if deltas else None,
        "cadence_max_s": max(deltas) if deltas else None,
        "trous_sup_30s": sorted(gaps, reverse=True)[:10],
        # Renommé : comptage des rejets DU FIRMWARE. Ce n'est PAS le verdict du décodeur
        # indépendant (reasons_fail d'eval_frames) — ne pas confondre les deux mesures.
        "rejets_firmware": len(rejects),
        "raisons_rejet_firmware": Counter(r["raison"] for r in rejects).most_common(5),
        "ids": sorted({f.get("id") for f in frames}),
        "temperature_C": span_of("temp_c"),
        "humidite_pct": span_of("humidity"),
        "vent_kmh": span_of("wind_kmh"),
        "rafale_kmh": span_of("gust_kmh"),
        "wind_dir_deg": span_of("wind_dir_deg"),
        "pluie_mm": sorted({f.get("rain_mm") for f in frames}),
        "uv": sorted({f.get("uv_index") for f in frames}),
        "lux": span_of("lux"),
        "pluie_decroissante": pluie_decroissante,
        "valeurs_hors_plage": sorted(hors),
        "emissions_par_10min": {f"{k*10}-{k*10+10} min": v for k, v in sorted(buckets.items())},
        "verdict": verdict,
        "motifs_fail": motifs,
    }
    if rapport is not None:
        res["rapport"] = args.rapport
        res["rapport_logfile"] = rapport.get("logfile")
        res["rapport_verdict"] = rapport.get("verdict")
        # Un rapport d'une AUTRE fenêtre ne doit pas valider/condamner celle-ci.
        rl = rapport.get("logfile")
        if rl and pathlib.Path(str(rl)).name != path.name:
            print(f"# AVERTISSEMENT : le rapport porte sur {rl!r}, pas sur {path.name!r} — "
                  "les deux fichiers ne couvrent pas la même fenêtre", file=sys.stderr)
            res["rapport_logfile_mismatch"] = True

    say(f"=== {path.name} ===")
    say(f"lignes lues : {len(lines)} | trames décodées : {len(frames)} | "
        f"émissions distinctes : {len(times)}")
    say(f"fenêtre couverte : {res['debut']} → {res['fin']} ({span} s)")
    if deltas:
        say(f"cadence : médiane {res['cadence_mediane_s']:.1f} s "
            f"(min {res['cadence_min_s']}, max {res['cadence_max_s']})")
    say(f"trous > 30 s : {res['trous_sup_30s'] or 'aucun'}")
    say(f"rejets FIRMWARE : {len(rejects)} {res['raisons_rejet_firmware'] if rejects else ''} "
        f"(≠ verdict du décodeur indépendant)")
    say(f"station(s) : {[hex(i) for i in res['ids'] if i is not None]}")
    say(f"T {res['temperature_C']} °C | H {res['humidite_pct']} % | vent {res['vent_kmh']} | "
        f"rafale {res['rafale_kmh']} | direction {res['wind_dir_deg']} ° | pluie {res['pluie_mm']} mm "
        f"| UV {res['uv']} | lux {res['lux']}")
    say(f"valeurs hors plage : {res['valeurs_hors_plage'] or 'aucune'}")
    say("émissions par tranche de 10 min :")
    for k, v in res["emissions_par_10min"].items():
        say(f"   {k:>10s} : {'#' * min(v, 60)} {v}")
    say(f"VERDICT : {verdict}" + (f" — motifs : {'; '.join(motifs)}" if motifs else ""))

    if args.json:
        atomic_write_json(args.json, res)
        say(f"résumé JSON : {args.json}")
    if args.txt:
        atomic_write_text(args.txt, "\n".join(out_lines) + "\n")

    if verdict == "FAIL":
        # Garde-fou : jamais de résumé rassurant quand le rapport dit FAIL.
        print(f"# VERDICT : FAIL — {len(motifs)} motif(s) : " + "; ".join(motifs), file=sys.stderr)
        print("# Ce résumé NE PEUT PAS afficher « 0 rejet » sans qualification : "
              "`rejets_firmware` compte les lignes V7IN1 REJ du firmware, PAS le verdict "
              "du décodeur indépendant.", file=sys.stderr)
        return 1
    print("# VERDICT : PASS", file=sys.stderr)
    return RC_OK


if __name__ == "__main__":
    sys.exit(main())
