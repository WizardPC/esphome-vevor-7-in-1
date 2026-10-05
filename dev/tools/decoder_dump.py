#!/usr/bin/env python3
"""Decode off-board the raw durations returned by the "Dump impulsions" button.

When the board receives pulses (capture counter rises) but publishes no frame, the question is
whether the RAW stream holds a valid frame — i.e. whether the fault is in the firmware assembler
or in reception itself.

It replays the firmware quantization (`timings_to_bits`, in
`esphome/components/vevor_7in1/vevor_protocol.h`):

    level   = 1 if the duration is positive, 0 otherwise   (GDO0 polarity is not assumed)
    n ticks = round(duration / period)                      (at least 1, at most MAX_RUN_BITS)
    each tick emits one bit of that level

then looks for a conformant 21-byte frame (header AA 00, rtl_433 checksum, coherent counter)
across the 4 candidate periods, both polarities and the 8 bit shifts.

Usage:
 dev/tools/decoder_dump.py logs/dump_brut.log [--json logs/dump_decode.json]

Return codes: 0 at least one capture read ("0 valid frame" is a negative result); 2 technical
error (unreadable file); 3 empty measurement: no capture (no "capture #"/"impulsions" line).
"""

from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _common import (ANSI, RC_ERREUR, RC_MESURE_NULLE, RC_OK,  # noqa: E402
                     atomic_write_json)

import re

PERIODS = (90, 88, 89, 87)          # same candidates as the firmware
MAX_RUN_BITS = 64
FRAME_BYTES = 21

DUMP_RE = re.compile(r"impulsions \[(\d+)-(\d+)\] sur (\d+) : (.+)$")
CAPTURE_RE = re.compile(r"capture #(\d+) : (\d+) impulsions, de (-?\d+) us à (-?\d+) us")


def lit_dumps(chemin: pathlib.Path) -> list[list[int]]:
    """Return the list of captures, each a list of signed durations (µs)."""
    captures: list[list[int]] = []
    courant: list[int] = []
    total_attendu = None
    for ligne in ANSI.sub("", chemin.read_text(encoding="utf-8", errors="replace")).splitlines():
        m = CAPTURE_RE.search(ligne)
        if m:
            if courant:
                captures.append(courant)
            courant, total_attendu = [], None
            continue
        m = DUMP_RE.search(ligne)
        if not m:
            continue
        debut, fin, total, valeurs = int(m.group(1)), int(m.group(2)), int(m.group(3)), m.group(4)
        n = len(valeurs.split())
        if debut == 0:
            total_attendu = total
        if n != fin - debut + 1:
            print(f"  ! tranche incohérente [{debut}-{fin}] : {n} valeurs", file=sys.stderr)
        if debut != len(courant):
            print(f"  ! tranche [{debut}-{fin}] reçue alors que {len(courant)} durées sont déjà là",
                  file=sys.stderr)
        courant.extend(int(x) for x in valeurs.split())
        if total_attendu is not None and len(courant) >= total_attendu:
            captures.append(courant)
            courant, total_attendu = [], None
    if courant:
        captures.append(courant)
    return captures


def bits_depuis_durees(durees: list[int], periode: int, inverser: bool) -> str:
    demi = periode // 2
    bits = []
    for v in durees:
        niveau = 1 if v > 0 else 0
        duree = abs(v)
        ticks = (duree + demi) // periode
        ticks = max(1, ticks)
        if ticks > MAX_RUN_BITS:
            continue                      # gap between bursts, like the firmware
        bits.append(("1" if (1 - niveau) else "0") * ticks if inverser else ("1" if niveau else "0") * ticks)
    return "".join(bits)


def porte_de_plausibilite(b: bytes):
    """Same PHYSICAL checks as the firmware (includes/vevor_protocol.h).

    Return None if the frame is plausible, else the name of the refusal. Without this gate the
    tool called a frame "valid" for candidates the firmware refuses: header + checksum + counter
    could still give a direction of 3841 deg and a temperature of 3636 degC — a FALSE POSITIVE.
    """
    x = bytearray(b)
    for i in (8, 9, 11, 12, 13, 14, 16, 17):   # documented -1 offset on these bytes
        x[i] = (x[i] - 1) & 0xFF
    if (((x[11] & 0x0F) << 8) | x[12]) > 359:
        return "direction"
    if b[7] > 100:
        return "humidite"
    temp_c = (((b[5] << 8) | b[6]) - 500) * 0.1
    if temp_c < -40.0 or temp_c > 60.0:
        return "temperature"
    return None


def trame_dans_bits(bits: str):
    """Search for a conformant frame at any bit shift.

    Return (bytes, shift, position, refusal): `refusal` is None if the frame also passes the
    plausibility gate, else the refusal reason — the caller must NOT report it as valid.
    """
    for decalage in range(min(8, len(bits))):
        utilisable = (len(bits) - decalage) // 8 * 8
        octets = bytes(int(bits[decalage + i: decalage + i + 8], 2) for i in range(0, utilisable, 8))
        for i in range(len(octets) - FRAME_BYTES + 1):
            b = octets[i:i + FRAME_BYTES]
            if b[0] != 0xAA or b[1] != 0x00:
                continue
            if (sum(b[0:19]) & 0xFF) != b[19] or b[20] != ((b[18] + 1) & 0xFF):
                continue
            return b, decalage, i, porte_de_plausibilite(b)
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("dump", type=pathlib.Path)
    ap.add_argument("--json", default=None, help="JSON report (relative = project root)")
    args = ap.parse_args()

    if not args.dump.exists():
        print(f"# MESURE NULLE — fichier absent : {args.dump}", file=sys.stderr)
        return RC_MESURE_NULLE
    try:
        captures = lit_dumps(args.dump)
    except OSError as exc:
        print(f"# ERREUR lecture {args.dump}: {exc}", file=sys.stderr)
        return RC_ERREUR

    if not captures:
        print(f"# MESURE NULLE — aucune capture dans {args.dump} : rien n'a été mesuré "
              "(ni « capture # », ni « impulsions »)", file=sys.stderr)
        return RC_MESURE_NULLE

    print(f"{len(captures)} capture(s) lue(s) dans {args.dump}")
    rapport = []
    for nc, durees in enumerate(captures, 1):
        if durees:
            lo, hi = min(abs(x) for x in durees), max(abs(x) for x in durees)
            print(f"\ncapture {nc} : {len(durees)} durées, de {lo} à {hi} µs")
        else:
            print(f"\ncapture {nc} : 0 durée")
        trouve = None
        for periode in PERIODS:
            for inverser in (False, True):
                bits = bits_depuis_durees(durees, periode, inverser)
                if len(bits) < FRAME_BYTES * 8:
                    continue
                r = trame_dans_bits(bits)
                if r:
                    b, decalage, position, refus = r
                    verdict = ("TRAME VALIDE" if refus is None else
                               f"candidat conforme en-tête+checksum+compteur, REFUSÉ par la porte ({refus})")
                    print(f"  >>> {verdict} : période {periode} µs, "
                          f"{'inversée' if inverser else 'normale'}, décalage bit {decalage}, "
                          f"position octet {position}")
                    print(f"      brut : {' '.join(f'{x:02x}' for x in b)}")
                    trouve = {"periode": periode, "inverse": inverser, "octets": list(b),
                              "refus": refus, "valide": refus is None}
                    break
            if trouve:
                break
        if not trouve:
            # Nothing valid: show the best period's bytes for visual judgement.
            for periode in PERIODS[:2]:
                bits = bits_depuis_durees(durees, periode, False)
                octets = bytes(int(bits[i:i + 8], 2) for i in range(0, len(bits) // 8 * 8, 8))[:12]
                print(f"  (période {periode} µs, sans inversion) premiers octets : "
                      f"{' '.join(f'{x:02x}' for x in octets)}")
        rapport.append({"capture": nc, "nb_durees": len(durees), "trame": trouve})

    valides = sum(1 for r in rapport if r["trame"] and r["trame"].get("valide"))
    conformes = sum(1 for r in rapport if r["trame"] and not r["trame"].get("valide"))
    if args.json:
        print(f"\nrapport écrit (atomique) : {atomic_write_json(args.json, rapport)}")
    if conformes:
        print(f"{conformes} capture(s) portent un candidat conforme en-tête+checksum+compteur\n"
              f"mais REFUSÉ par la porte de plausibilité : FAUX POSITIF, pas une réception")
    print(f"\n{valides} capture(s) sur {len(rapport)} portent une trame VALIDE")
    if valides == 0:
        print("# AUCUNE TRAME valide dans les captures (mesure faite) — résultat négatif", file=sys.stderr)
    return RC_OK


if __name__ == "__main__":
    raise SystemExit(main())
