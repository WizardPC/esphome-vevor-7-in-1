#!/usr/bin/env python3
"""Independently evaluate the Vevor 7-in-1 frames found in an ESPHome log.

The Python decoder here is a SECOND implementation of the spec (references/PROTOCOL.md, itself
from rtl_433/src/devices/vevor_7in1.c). It does not reuse the firmware's C++ code, which is what
makes the comparison meaningful for self-assessment.

Usage:
    eval_frames.py logs/capture_20260101.log [--json report.json] [--ref-temp 12.5]

Detects lines `... RAW aa 00 f8 ...` (21 hex bytes) and, when present, the `... OK {...}` line the
firmware produces, for frame-by-frame comparison.

The verdict is no longer a simple count: PASS requires enough valid frames, plausible values
(physical ranges + lux/UV consistency), a coherent TX counter sequence, a ~20 s cadence, and a
frame-by-frame AGREEMENT with the C++ firmware. A report with findings can no longer PASS.

Return code: 0 if verdict PASS, 1 otherwise.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
from collections import defaultdict

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _common import OK_RE, RAW_RE, TS_RE, atomic_write_json  # noqa: E402  (shared patterns)

# Station TX counter steps: MEASURED at ~+1.95/s (+39 over a 20 s burst) — an internal counter
# that advances with TIME, not with bursts, so the step varies with the real inter-burst interval.
# Comparing it to elapsed time is correct where a strict "gap = 1" or "= 39" was FALSE.
TX_TICKS_PER_S = 1.95
TX_TOLERANCE = 5      # ticks: margin for rounding and timestamp jitter
TX_MAX_STEPS = 5      # beyond this, assume an inconsistency, not missed bursts

# Lux/UV consistency: the UV index follows about 1 point per 2 500 lx. This rejects the ABSURD,
# with a deliberately wide factor-20 margin: zero lux with non-zero UV, or lux beyond 20x the
# range the announced UV allows.
LUX_PER_UV = 2500
LUX_SLACK = 20


def decode(b: list[int]) -> dict:
    """Decode 21 raw bytes. Never raises: also returns validity flags."""
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
    # Lux / UV consistency (the reference firmware rejects the same cases).
    if f["uv_index"] > 0 and f["lux"] == 0:
        problems.append(f"lux nul alors que l'UV vaut {f['uv_index']}")
    elif f["uv_index"] == 0 and f["lux"] > LUX_PER_UV * LUX_SLACK:
        problems.append(f"lux {f['lux']} invraisemblable pour un UV de 0")
    elif f["uv_index"] > 0 and f["lux"] > LUX_PER_UV * (f["uv_index"] + 1) * LUX_SLACK:
        problems.append(f"lux {f['lux']} hors de portée de l'UV {f['uv_index']}")
    return problems


# Fields compared frame by frame between the firmware C++ and the Python decoder.
COMPARE_FIELDS = ("id", "channel", "battery_low", "temp_c", "humidity", "wind_kmh", "gust_kmh",
                  "wind_dir_deg", "rain_mm", "uv_index", "lux", "tx_counter")


def compare_with_firmware(ours: list[dict], theirs: list[dict]) -> list[str]:
    """Compare, IN ORDER, the Python decoder frames and those published by the firmware.

    Both lists come from the same log: each firmware `RAW` is followed by its `OK`.
    """
    mismatches = []
    if len(ours) != len(theirs):
        mismatches.append(f"{len(ours)} trame(s) décodée(s) ici contre {len(theirs)} publiée(s) "
                          "par le firmware : les deux ne voient pas le même nombre de trames")
    for i, (a, b) in enumerate(zip(ours, theirs)):
        for field in COMPARE_FIELDS:
            if field not in b:
                mismatches.append(f"trame {i + 1} : champ « {field} » absent du JSON du firmware")
                continue
            va, vb = a.get(field), b.get(field)
            if isinstance(va, float) or isinstance(vb, float):
                if va is None or vb is None or abs(float(va) - float(vb)) > 0.06:
                    mismatches.append(f"trame {i + 1} : {field} — python {va} vs firmware {vb}")
            elif va != vb:
                mismatches.append(f"trame {i + 1} : {field} — python {va} vs firmware {vb}")
    return mismatches


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("logfile")
    ap.add_argument("--json", dest="json_out", default=None)
    ap.add_argument("--ref-temp", type=float, default=None,
                    help="reference temperature (degC) for cross-checking")
    ap.add_argument("--ref-hum", type=float, default=None, help="reference humidity (%%)")
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
        "reasons_fail": [],
    }

    by_id: dict[int, list[dict]] = defaultdict(list)
    for f in valid:
        by_id[f["id"]].append(f)

    if not frames:
        report["findings"].append(
            "Aucune trame RAW dans le log : rien n'a été capté. "
            "Vérifier SPI/alim, puis balayer la fréquence (867,8–868,6 MHz), puis déviation/bande passante."
        )

    sequence_breaks = 0
    for sid, fr in by_id.items():
        gaps, missed, duplicates = [], 0, 0
        for a, b in zip(fr, fr[1:]):
            dc = (b["tx_counter"] - a["tx_counter"]) & 0xFF
            if dc == 0:
                duplicates += 1                      # same burst delivered twice by the RMT
                continue
            ts_a, ts_b = a.get("ts"), b.get("ts")
            if ts_a and ts_b:
                ha, ma, sa = (int(x) for x in ts_a.split(":"))
                hb, mb, sb = (int(x) for x in ts_b.split(":"))
                dt = (hb * 3600 + mb * 60 + sb) - (ha * 3600 + ma * 60 + sa)
                dt = dt if dt >= 0 else dt + 86400
                expected = dt * TX_TICKS_PER_S
                if abs(dc - expected) <= TX_TOLERANCE:
                    continue                          # advance consistent with elapsed time
                for k in range(2, TX_MAX_STEPS + 2):  # k-1 missed bursts?
                    if abs(dc - k * expected) <= TX_TOLERANCE:
                        missed += k - 1
                        break
                else:
                    # Very short dt with a counter gap: signature of a DOUBLE publication (the
                    # station cannot emit two frames in the same second at 20 s cadence).
                    quoi = ("double publication dans la même seconde"
                            if dt <= 1 else f"pour {dt} s, soit {expected:.0f} attendus")
                    gaps.append(f"compteur TX {a['tx_counter']} → {b['tx_counter']} "
                                f"(écart {dc} {quoi})")
            elif dc > 60:
                gaps.append(f"compteur TX {a['tx_counter']} → {b['tx_counter']} (écart {dc})")
        sequence_breaks += len(gaps)
        if gaps:
            report["findings"].append(f"ID {sid}: {len(gaps)} incohérence(s) de compteur TX — "
                                      + "; ".join(gaps[:5]))
        else:
            report["findings"].append(
                f"ID {sid}: avance du compteur TX conforme au temps écoulé sur {len(fr)} trame(s) "
                f"(~{TX_TICKS_PER_S} tick/s ; {duplicates} duplicate(s) de livraison RMT, "
                f"{missed} rafale(s) manquée(s))")
        rain = [x["rain_mm"] for x in fr]
        if any(y < x for x, y in zip(rain, rain[1:])):
            report["findings"].append(f"ID {sid}: pluie décroissante {rain} → suspicion de mauvais mapping d'octets")
            report["reasons_fail"].append("pluie décroissante")
        else:
            report["findings"].append(f"ID {sid}: pluie monotone OK ({rain[0]} → {rain[-1]} mm)")
        bad = [x for x in fr if x["problems"]]
        if bad:
            report["findings"].append(
                f"ID {sid}: {len(bad)} trame(s) à valeurs implausibles — "
                + "; ".join(sorted({p for x in bad for p in x["problems"]})[:6])
            )
            report["reasons_fail"].append("valeurs implausibles (ou incohérence lux/UV)")
        else:
            report["findings"].append(f"ID {sid}: toutes les valeurs sont dans les plages physiques "
                                      "et la cohérence lux/UV est respectée")

    # Cadence: compare timestamps when they exist.
    cadence_ok = None
    stamps = [f["ts"] for f in valid if f.get("ts")]
    if len(stamps) >= 2:
        def sec(t: str) -> int:
            h, m, s = (int(x) for x in t.split(":"))
            return h * 3600 + m * 60 + s
        deltas = [b - a for a, b in zip(map(sec, stamps), map(sec, stamps[1:]))]
        deltas = [d if d >= 0 else d + 86400 for d in deltas]
        near20 = sum(1 for d in deltas if 15 <= d <= 25)
        report["ts_deltas_s"] = deltas
        # RMT delivery duplicates give 0 s intervals: not distinct emissions, so removed from the
        # denominator.
        significant = [d for d in deltas if d > 1]
        cadence_ok = bool(significant) and near20 >= max(1, int(0.6 * len(significant)))
        report["findings"].append(
            f"cadence: {near20}/{len(significant)} intervalles significatifs entre 15 et 25 s "
            f"— la station émet une rafale toutes les 20 s"
        )
        if not cadence_ok:
            report["reasons_fail"].append("cadence de la station non retrouvée (~20 s attendu)")

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

    # Frame-by-frame comparison with the values published by the firmware C++.
    mismatches: list[str] = []
    if firmware_frames and valid:
        mismatches = compare_with_firmware(valid, firmware_frames)
        report["firmware_mismatches"] = mismatches[:20]
        report["firmware_mismatch_count"] = len(mismatches)
        if mismatches:
            report["findings"].append(
                f"firmware: DÉSACCORD entre le C++ et le décodeur Python sur {len(mismatches)} champ(s) — "
                + "; ".join(mismatches[:5]))
            report["reasons_fail"].append("désaccord firmware / décodeur indépendant")
        else:
            report["findings"].append(
                f"firmware: les {len(firmware_frames)} trames publiées par le C++ concordent champ par champ "
                "avec le décodeur Python indépendant")
    elif firmware_frames and not valid:
        report["findings"].append(
            f"firmware: {len(firmware_frames)} trame(s) publiée(s) mais aucune ligne RAW exploitable — "
            "comparaison impossible")
        report["reasons_fail"].append("aucune trame RAW exploitable pour recouper le firmware")

    # VERDICT: everything must agree; one entry in reasons_fail is enough to refuse.
    if len(valid) < args.min_valid:
        report["reasons_fail"].append(f"moins de {args.min_valid} trames valides ({len(valid)})")
    if sequence_breaks:
        report["reasons_fail"].append(f"{sequence_breaks} incohérence(s) de compteur TX")
    if frames and not valid:
        report["reasons_fail"].append("aucune trame valide")
    report["verdict"] = "PASS" if not report["reasons_fail"] else "FAIL"

    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.json_out:
        atomic_write_json(args.json_out, report)

    print("\n=== RÉSUMÉ ===", file=sys.stderr)
    print(
        f"frames={len(frames)} valides={len(valid)} "
        f"(checksum KO={report['checksum_fail']}, compteur KO={report['counter_fail']}) "
        f"verdict={report['verdict']} (seuil {args.min_valid})",
        file=sys.stderr,
    )
    for f in report["findings"]:
        print(" - " + f, file=sys.stderr)
    if report["reasons_fail"]:
        print(" MOTIFS DE REFUS : " + "; ".join(report["reasons_fail"]), file=sys.stderr)
    return 0 if report["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
