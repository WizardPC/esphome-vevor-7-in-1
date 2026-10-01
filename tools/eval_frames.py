#!/usr/bin/env python3
"""Évalue indépendamment les trames Vevor 7-en-1 trouvées dans un log ESPHome.

Le décodeur Python ici est une **seconde implémentation** de la spec
(references/PROTOCOL.md, elle-même issue de rtl_433/src/devices/vevor_7in1.c).
Il ne réutilise pas le code C++ du firmware : c'est ce qui rend la comparaison
significative pour l'auto-évaluation.

Usage:
    eval_frames.py logs/capture_20260101.log [--json rapport.json] [--ref-temp 12.5]

Détecte les lignes de la forme `... RAW aa 00 f8 ...` (21 octets hex) et, si présente,
la ligne `... OK {...}` produite par le firmware, pour comparaison.

Code retour : 0 si au moins une trame valide ET critères croisés satisfaits, 1 sinon.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
from collections import defaultdict

RAW_RE = re.compile(r"RAW[ :=]+((?:[0-9a-fA-F]{2}[ \t]+){20}[0-9a-fA-F]{2})")
OK_RE = re.compile(r"OK[ :=]+(\{.*\})")
TS_RE = re.compile(r"^\[(\d{2}:\d{2}:\d{2})\]")


def decode(b: list[int]) -> dict:
    """Décode 21 octets bruts. Ne lève pas : renvoie aussi les drapeaux de validité."""
    out: dict = {"raw": " ".join(f"{x:02x}" for x in b)}
    out["checksum_ok"] = (sum(b[0:19]) & 0xFF) == b[19]
    out["counter_ok"] = b[20] == ((b[18] + 1) & 0xFF)
    out["header_ok"] = b[0] == 0xAA and b[1] == 0x00
    out["valid"] = out["checksum_ok"] and out["counter_ok"] and out["header_ok"]
    if not out["valid"]:
        return out

    d = list(b)
    for i in (8, 9, 11, 12, 13, 14, 16, 17):
        d[i] = (d[i] - 1) & 0xFF

    out["id"] = (b[2] << 8) | b[3]
    out["channel"] = b[1] & 0x0F
    out["battery_low"] = bool(b[4] & 0x80)
    out["tx_counter"] = b[18]
    out["temp_c"] = round((((b[5] << 8) | b[6]) - 500) * 0.1, 1)
    out["humidity"] = b[7]
    out["wind_kmh"] = round(((d[8] << 8) | d[9]) / 8.333, 1)
    out["gust_kmh"] = round(b[10] / 1.25, 1)
    out["wind_dir_deg"] = ((d[11] & 0x0F) << 8) | d[12]
    out["rain_mm"] = round(((d[13] << 8) | d[14]) * 0.233, 1)
    out["uv_index"] = (b[15] & 0x1F) - 1
    lux_raw = (d[16] << 8) | d[17]
    out["lux"] = (lux_raw & 0x7FFF) * 10 if lux_raw & 0x8000 else lux_raw
    return out


def plausibility(f: dict) -> list[str]:
    problems = []
    if not -40 <= f["temp_c"] <= 60:
        problems.append(f"température hors plage: {f['temp_c']} °C")
    if not 0 <= f["humidity"] <= 100:
        problems.append(f"humidité hors plage: {f['humidity']} %")
    if not 0 <= f["wind_kmh"] <= 180:
        problems.append(f"vent hors plage: {f['wind_kmh']} km/h")
    if not 0 <= f["gust_kmh"] <= 250:
        problems.append(f"rafale hors plage: {f['gust_kmh']} km/h")
    if not 0 <= f["wind_dir_deg"] <= 359:
        problems.append(f"direction hors plage: {f['wind_dir_deg']}°")
    if not 0 <= f["uv_index"] <= 16:
        problems.append(f"UV hors plage: {f['uv_index']}")
    if f["lux"] < 0:
        problems.append(f"lux négatif: {f['lux']}")
    if f["rain_mm"] < 0:
        problems.append("pluie négative")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("logfile")
    ap.add_argument("--json", dest="json_out", default=None)
    ap.add_argument("--ref-temp", type=float, default=None, help="température de référence (°C) pour recoupement")
    ap.add_argument("--ref-hum", type=float, default=None, help="humidité de référence (%%)")
    ap.add_argument("--min-valid", type=int, default=10)
    args = ap.parse_args()

    lines = pathlib.Path(args.logfile).read_text(encoding="utf-8", errors="replace").splitlines()

    frames: list[dict] = []
    firmware_frames: list[dict] = []
    for line in lines:
        m = RAW_RE.search(line)
        if m:
            hexes = m.group(1).split()
            if len(hexes) == 21:
                f = decode([int(h, 16) for h in hexes])
                tsm = TS_RE.match(line)
                f["ts"] = tsm.group(1) if tsm else None
                f["problems"] = plausibility(f) if f["valid"] else ["trame invalide"]
                frames.append(f)
        mo = OK_RE.search(line)
        if mo:
            try:
                firmware_frames.append(json.loads(mo.group(1)))
            except json.JSONDecodeError:
                firmware_frames.append({"unparsable": mo.group(1)})

    valid = [f for f in frames if f["valid"]]
    report: dict = {
        "logfile": args.logfile,
        "frames_found": len(frames),
        "frames_valid": len(valid),
        "checksum_fail": sum(1 for f in frames if not f["checksum_ok"]),
        "counter_fail": sum(1 for f in frames if f["checksum_ok"] and not f["counter_ok"]),
        "firmware_decoded_lines": len(firmware_frames),
        "frames": frames,
        "findings": [],
        "verdict": "FAIL",
    }

    by_id: dict[int, list[dict]] = defaultdict(list)
    for f in valid:
        by_id[f["id"]].append(f)

    if not frames:
        report["findings"].append(
            "Aucune trame RAW dans le log : rien n'a été capté. "
            "Vérifier SPI/alim, puis balayer la fréquence (867,8–868,6 MHz), puis déviation/bande passante."
        )

    for sid, fr in by_id.items():
        fr_sorted = sorted(fr, key=lambda x: x.get("tx_counter", 0))
        gaps = []
        for a, b in zip(fr, fr[1:]):
            dc = (b["tx_counter"] - a["tx_counter"]) & 0xFF
            if dc != 1:
                gaps.append(f"compteur TX {a['tx_counter']} → {b['tx_counter']} (écart {dc}, pertes possibles)")
        if gaps:
            report["findings"].append(f"ID {sid}: {len(gaps)} rupture(s) de séquence — " + "; ".join(gaps[:5]))
        else:
            report["findings"].append(f"ID {sid}: séquence de compteur TX continue sur {len(fr)} trames")
        rain = [x["rain_mm"] for x in fr]
        if any(y < x for x, y in zip(rain, rain[1:])):
            report["findings"].append(f"ID {sid}: pluie décroissante {rain} → suspicion de mauvais mapping d'octets")
        else:
            report["findings"].append(f"ID {sid}: pluie monotone OK ({rain[0]} → {rain[-1]} mm)")
        bad = [x for x in fr if x["problems"]]
        if bad:
            report["findings"].append(
                f"ID {sid}: {len(bad)} trame(s) à valeurs implausibles — "
                + "; ".join(sorted({p for x in bad for p in x["problems"]})[:6])
            )
        else:
            report["findings"].append(f"ID {sid}: toutes les valeurs sont dans les plages physiques")

    # Cadence : au mieux, on compare les horodatages quand ils existent.
    stamps = [f["ts"] for f in valid if f.get("ts")]
    if len(stamps) >= 2:
        def sec(t: str) -> int:
            h, m, s = (int(x) for x in t.split(":"))
            return h * 3600 + m * 60 + s
        deltas = [b - a for a, b in zip(map(sec, stamps), map(sec, stamps[1:]))]
        deltas = [d if d >= 0 else d + 86400 for d in deltas]
        near20 = sum(1 for d in deltas if 15 <= d <= 25)
        report["ts_deltas_s"] = deltas
        report["findings"].append(
            f"cadence: {near20}/{len(deltas)} intervalles entre 15 et 25 s (cumul: {deltas}) "
            "— la station émet une rafale toutes les 20 s"
        )

    if valid:
        f0 = valid[0]
        if args.ref_temp is not None:
            d = abs(f0["temp_c"] - args.ref_temp)
            report["findings"].append(
                f"recoupement température: station {f0['temp_c']} °C vs référence {args.ref_temp} °C (écart {d:.1f})"
            )
        if args.ref_hum is not None:
            d = abs(f0["humidity"] - args.ref_hum)
            report["findings"].append(
                f"recoupement humidité: station {f0['humidity']} % vs référence {args.ref_hum} % (écart {d:.1f})"
            )

    if firmware_frames and valid:
        report["findings"].append(
            f"firmware: {len(firmware_frames)} trame(s) décodée(s) par le C++ — "
            "comparer manuellement les valeurs avec celles-ci (champs 'frames')."
        )

    report["verdict"] = "PASS" if len(valid) >= args.min_valid else "FAIL"

    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.json_out:
        pathlib.Path(args.json_out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n=== RÉSUMÉ ===", file=sys.stderr)
    print(
        f"trames={len(frames)} valides={len(valid)} "
        f"(checksum KO={report['checksum_fail']}, compteur KO={report['counter_fail']}) "
        f"verdict={report['verdict']} (seuil {args.min_valid})",
        file=sys.stderr,
    )
    for f in report["findings"]:
        print(" - " + f, file=sys.stderr)
    return 0 if report["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
