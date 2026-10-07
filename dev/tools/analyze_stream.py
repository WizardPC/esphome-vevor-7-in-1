#!/usr/bin/env python3
"""Analyse a "demodulated stream" capture (CC1101 diagnostic mode without syncword).

With `sync_mode: None` + `carrier_sense_above_threshold: true`, the CC1101 starts a packet on an
energy threshold and fills the 21-byte FIFO, logging the demodulated bit stream without requiring
a syncword. This script searches it independently of polarity and bit alignment for:

  1. the preamble `AA AA CA CA 54` (and its bitwise complement `55 55 35 35 AB`);
  2. any candidate frame `b[0]==0xAA && b[1]==0x00` with a valid rtl_433 checksum
     (`sum(b[0..18]) & 0xFF == b[19]` and `b[20] == (b[18]+1) & 0xFF`).

Usage:
 dev/tools/analyze_stream.py logs/stream1.log [--json logs/stream_analysis.json]
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import statistics
import sys

RAW_RE = re.compile(r"V7IN1 RAW ((?:[0-9a-fA-F]{2} )+[0-9a-fA-F]{2})\s+rssi=(-?[\d.]+)")
TS_RE = re.compile(r"^\[(\d\d:\d\d:\d\d)\]")
PREAMBLE = bytes([0xAA, 0xAA, 0xCA, 0xCA, 0x54])


def ts_seconds(ts: str) -> int:
    h, m, s = (int(x) for x in ts.split(":"))
    return h * 3600 + m * 60 + s


def parse(path: pathlib.Path):
    """Return (packets, timestamps): list of byte payloads and list of seconds."""
    packets, stamps = [], []
    last_ts = None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = TS_RE.match(line.strip())
        if m:
            last_ts = m.group(1)
        m = RAW_RE.search(line)
        if not m:
            continue
        payload = bytes(int(b, 16) for b in m.group(1).split())
        packets.append((payload, float(m.group(2))))
        stamps.append(ts_seconds(last_ts) if last_ts else None)
    return packets, stamps


def shifted_views(bits: str, width: int = 8):
    """8 views of the stream, shifted by 0..7 bits.

    Byte alignment is arbitrary under carrier sense.
    """
    views = []
    for s in range(width):
        usable = (len(bits) - s) // 8 * 8
        views.append(bytes(int(bits[s + i : s + i + 8], 2) for i in range(0, usable, 8)))
    return views


def find_all(hay: bytes, needle: bytes):
    out, i = [], hay.find(needle)
    while i != -1:
        out.append(i)
        i = hay.find(needle, i + 1)
    return out


def decode_frame(b: bytes):
    """rtl_433 spec checks on 21 bytes."""
    if len(b) != 21:
        return None
    csum = sum(b[0:19]) & 0xFF
    return {
        "hex": " ".join(f"{x:02x}" for x in b),
        "entete_ok": b[0] == 0xAA and b[1] == 0x00,
        "checksum_ok": csum == b[19],
        "compteur_ok": b[20] == ((b[18] + 1) & 0xFF),
        "id": (b[2] << 8) | b[3],
        "tx_counter": b[18],
        "checksum_calcule": csum,
        "checksum_lu": b[19],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("log")
    ap.add_argument("--json", default=None)
    ap.add_argument("--min-rssi", type=float, default=-95.0)
    args = ap.parse_args()

    path = pathlib.Path(args.log)
    packets, stamps = parse(path)
    if not packets:
        print("NO V7IN1 RAW line in this file.")
        return 1

    rssis = [r for _, r in packets]
    window = None
    if stamps[0] is not None and stamps[-1] is not None:
        window = stamps[-1] - stamps[0]

    bits = "".join(f"{b:08b}" for b in b"".join(p for p, _ in packets))
    views = shifted_views(bits)

    # 1. search the preamble (and its complement) at every alignment
    pre_hits, inv_hits = [], []
    for s, view in enumerate(views):
        for pos in find_all(view, PREAMBLE):
            pre_hits.append({"shift": s, "offset": pos})
        for pos in find_all(view, bytes(x ^ 0xFF for x in PREAMBLE)):
            inv_hits.append({"shift": s, "offset": pos})

    # 2. search candidate AA 00 frames at every alignment + checksum
    candidates, valid = [], []
    for s, view in enumerate(views):
        for pos in find_all(view, bytes([0xAA, 0x00])):
            frame = view[pos : pos + 21]
            info = decode_frame(frame)
            if info is None:
                continue
            info = {"shift": s, "offset": pos, **info}
            candidates.append(info)
            if info["checksum_ok"] and info["compteur_ok"]:
                valid.append(info)

    strong = [(i, p, r) for i, (p, r) in enumerate(packets) if r >= args.min_rssi]
    strong_sorted = sorted(strong, key=lambda x: -x[2])[:10]

    report = {
        "fichier": str(path),
        "paquets_21o": len(packets),
        "fenetre_s": window,
        "cadence_paquet_par_s": round(len(packets) / window, 3) if window else None,
        "rssi_min": min(rssis),
        "rssi_max": max(rssis),
        "rssi_moyenne": round(statistics.fmean(rssis), 2),
        "paquets_forts": len(strong),
        "seuil_fort_dbm": args.min_rssi,
        "preambule_trouve": pre_hits[:20],
        "preambule_inverse_trouve": inv_hits[:20],
        "trames_candidates_aa00": len(candidates),
        "trames_valides": valid[:10],
        "top_rssi": [
            {"i": i, "hex": " ".join(f"{x:02x}" for x in packets[i][0]), "rssi": packets[i][1]}
            for i, _, _ in strong_sorted
        ],
    }

    print(f"packets 21 B : {len(packets)}  (window {window} s -> "
          f"{report['cadence_paquet_par_s']} packet/s)")
    print(f"RSSI         : min {report['rssi_min']} / mean {report['rssi_moyenne']} / "
          f"max {report['rssi_max']} dBm ; >= {args.min_rssi} dBm : {len(strong)}")
    print(f"preamble AA AA CA CA 54 : {len(pre_hits)} occurrence(s) ; "
          f"complement: {len(inv_hits)}")
    print(f"candidate frames AA 00  : {len(candidates)} ; valid (checksum+counter) : "
          f"{len(valid)}")
    for v in valid[:5]:
        print(f"  VALID shift={v['shift']} {" ".join(v['hex'].split()[:21])}")
    for t in report["top_rssi"][:5]:
        print(f"  strong {t['rssi']:>7.1f} dBm  {t['hex']}")

    if args.json:
        out = pathlib.Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"report written: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
