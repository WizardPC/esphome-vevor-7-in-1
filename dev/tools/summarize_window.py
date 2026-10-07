#!/usr/bin/env python3
"""Compact summary of a capture window: frames, cadence, gaps, coherence, VERDICT.

Complement of `eval_frames.py` (which validates frame by frame): this answers window-level
questions — did the station emit continuously, at what cadence, what gaps, were values
coherent, were there rejects.

A SUMMARY MUST NEVER CONTRADICT ITS REPORT:
  * `--rapport <rapport.json>` (output of `eval_frames.py`) reuses its `verdict` and
    `reasons_fail`: the summary carries the SAME verdict, and on FAIL cites the same reasons
    and exits with code 1;
  * the firmware "rejets" field is renamed `rejets_firmware` (and `raisons_rejet_firmware`):
    it counts the firmware `V7IN1 REJ` LINES, NOT the independent decoder verdict.
It also adds `wind_dir_deg` (direction range) and `valeurs_hors_plage`.

Usage:
 dev/tools/summarize_window.py logs/capture.log [--rapport evidence/rapport.json]
                                 [--json evidence/resume.json] [--txt evidence/resume.txt]

Return codes:
    0  summary written, verdict PASS (or "no frame" without a report: negative result);
    1  verdict FAIL (the report — or the internal checks — says FAIL);
    3  NULL MEASUREMENT: log file missing or empty — nothing was measured.
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

# Patterns specific to the V7IN1 STREAM (anchored at end of line after ANSI stripping).
OK = re.compile(r"V7IN1 OK (\{.*\})$")
RAW = re.compile(r"V7IN1 RAW ([0-9a-f ]+)$")
REJ = re.compile(r"V7IN1 REJ ([^$]*)$")

# Vocabulary IDENTICAL to eval_frames.py (both must justify the same way).
MOTIF_PLUIE = "decreasing rain"
MOTIF_IMPLAUSIBLE = "implausible values (or lux/UV incoherence)"


def plausibility_of(frame: dict) -> list[str]:
    """Reuses eval_frames.py's plausibility gate (late import: avoids any circular
    dependency) on a firmware-published frame."""
    try:
        from eval_frames import plausibility
        return plausibility(frame)
    except Exception:
        # Minimal fallback: never let an exception hide an obvious anomaly.
        probs = []
        d = frame.get("wind_dir_deg")
        if isinstance(d, (int, float)) and not 0 <= d <= 359:
            probs.append(f"direction out of range: {d}°")
        r = frame.get("rain_mm")
        if isinstance(r, (int, float)) and r < 0:
            probs.append("negative rain")
        return probs


def secs(h: str, m: str, s: str) -> int:
    return int(h) * 3600 + int(m) * 60 + int(s)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("logfile")
    ap.add_argument("--rapport", default=None,
                    help="paired eval_frames.py report: its verdict and reasons are reused")
    ap.add_argument("--json", default=None, help="JSON summary (relative = project root)")
    ap.add_argument("--txt", default=None, help="human-readable text summary (relative = project root)")
    args = ap.parse_args()

    path = pathlib.Path(args.logfile)
    if not path.is_absolute():
        path = ROOT / path
    if not path.exists():
        print(f"# NULL MEASUREMENT — file missing: {path}", file=sys.stderr)
        return RC_MESURE_NULLE
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if not any(line.strip() for line in lines):
        print(f"# NULL MEASUREMENT — empty file ({path}): nothing was measured", file=sys.stderr)
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

    # --- Paired report (verdict source) --------------------------------------
    rapport = None
    if args.rapport:
        rp = pathlib.Path(args.rapport)
        if not rp.is_absolute():
            rp = ROOT / rp
        if not rp.exists():
            print(f"# ERROR: paired report missing: {rp}", file=sys.stderr)
            return 2
        rapport = json.loads(rp.read_text(encoding="utf-8", errors="replace"))

    if not frames:
        say(f"=== {path.name} ===")
        say(f"lines read: {len(lines)} | NO decoded FRAME | firmware rejects: {len(rejects)}")
        res = {
            "fichier": args.logfile,
            "lignes": len(lines),
            "trames_decodues": 0,
            "verdict": "NO FRAME",
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
            say(f"JSON summary: {args.json}")
        if args.txt:
            atomic_write_text(args.txt, "\n".join(out_lines) + "\n")
        if res["verdict"] == "FAIL":
            print("# VERDICT: FAIL (reused from the report) — " + "; ".join(res["motifs_fail"]),
                  file=sys.stderr)
            return 1
        print("# NO FRAME: measurement done, negative result (code 0)", file=sys.stderr)
        return RC_OK

    times = sorted({f["_t"] for f in frames})           # distinct emissions (deduplicated)
    span = times[-1] - times[0]
    deltas = [b - a for a, b in zip(times, times[1:]) if b - a > 1]
    gaps = [d for d in deltas if d > 30]
    buckets = Counter(t // 600 for t in times)          # per 10-minute bucket

    def span_of(key):
        vals = [f[key] for f in frames if isinstance(f.get(key), (int, float))]
        return (min(vals), max(vals)) if vals else None

    # Summary-only anomalies (independent of the report) — eval_frames vocabulary.
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

    # Verdict: the paired report wins; otherwise internal anomalies decide.
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
        # Renamed: counts FIRMWARE rejects. Not the independent decoder verdict
        # (eval_frames reasons_fail) — do not confuse the two measurements.
        "rejets_firmware": len(rejects),
        "raisons_rejet_firmware": Counter(r["raison"] for r in rejects).most_common(5),
        "ids": sorted({f.get("id") for f in frames}),
        "temperature_C": span_of("temp_c"),
        "humidity_pct": span_of("humidity"),
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
        # A report from ANOTHER window must not validate/condemn this one.
        rl = rapport.get("logfile")
        if rl and pathlib.Path(str(rl)).name != path.name:
            print(f"# WARNING: the report is about {rl!r}, not {path.name!r} — "
                  "the two files do not cover the same window", file=sys.stderr)
            res["rapport_logfile_mismatch"] = True

    say(f"=== {path.name} ===")
    say(f"lines read: {len(lines)} | decoded frames: {len(frames)} | "
        f"distinct emissions: {len(times)}")
    say(f"window covered: {res['debut']} → {res['fin']} ({span} s)")
    if deltas:
        say(f"cadence: median {res['cadence_mediane_s']:.1f} s "
            f"(min {res['cadence_min_s']}, max {res['cadence_max_s']})")
    say(f"gaps > 30 s: {res['trous_sup_30s'] or 'none'}")
    say(f"FIRMWARE rejects: {len(rejects)} {res['raisons_rejet_firmware'] if rejects else ''} "
        f"(≠ independent decoder verdict)")
    say(f"station(s): {[hex(i) for i in res['ids'] if i is not None]}")
    say(f"T {res['temperature_C']} °C | H {res['humidity_pct']} % | wind {res['vent_kmh']} | "
        f"gust {res['rafale_kmh']} | direction {res['wind_dir_deg']} ° | rain {res['pluie_mm']} mm "
        f"| UV {res['uv']} | lux {res['lux']}")
    say(f"out-of-range values: {res['valeurs_hors_plage'] or 'none'}")
    say("emissions per 10-min bucket:")
    for k, v in res["emissions_par_10min"].items():
        say(f"   {k:>10s} : {'#' * min(v, 60)} {v}")
    say(f"VERDICT: {verdict}" + (f" — reasons: {'; '.join(motifs)}" if motifs else ""))

    if args.json:
        atomic_write_json(args.json, res)
        say(f"JSON summary: {args.json}")
    if args.txt:
        atomic_write_text(args.txt, "\n".join(out_lines) + "\n")

    if verdict == "FAIL":
        # Safety: never a reassuring summary when the report says FAIL.
        print(f"# VERDICT: FAIL — {len(motifs)} reason(s): " + "; ".join(motifs), file=sys.stderr)
        print("# This summary CANNOT display \"0 reject\" without qualification: "
              "`rejets_firmware` counts the firmware's V7IN1 REJ lines, NOT the verdict "
              "of the independent decoder.", file=sys.stderr)
        return 1
    print("# VERDICT: PASS", file=sys.stderr)
    return RC_OK


if __name__ == "__main__":
    sys.exit(main())
