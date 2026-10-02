#!/usr/bin/env python3
"""Décode hors de la carte les durées brutes ramenées par le bouton « Dump impulsions ».

Pourquoi : quand la carte reçoit des impulsions (compteur de captures qui monte) mais ne publie
aucune trame, il faut savoir si le flux BRUT contient une trame valide — donc si le défaut est dans
l'assembleur du firmware, ou dans la réception elle-même.

Ce script rejoue exactement la quantification du firmware (voir `timings_to_bits` dans
`esphome/includes/vevor_protocol.h`) :

    niveau   = 1 si la durée est positive, 0 sinon      (la polarité GDO0 n'est pas présumée)
    nb ticks = arrondi(durée / période)                  (au moins 1, au plus MAX_RUN_BITS)
    chaque tick produit un bit de ce niveau

puis cherche, dans le flux de bits, une trame de 21 octets conforme : en-tête AA 00, somme de
contrôle rtl_433 et compteur cohérent — en essayant les 4 périodes candidates, les deux polarités
et les 8 décalages de bit.

Usage :
    tools/decoder_dump.py logs/dump_brut.log [--json logs/dump_decode.json]
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re as _re
import re
import sys

PERIODS = (90, 88, 89, 87)          # mêmes candidats que le firmware
MAX_RUN_BITS = 64
FRAME_BYTES = 21

DUMP_RE = re.compile(r"impulsions \[(\d+)-(\d+)\] sur (\d+) : (.+)$")
CAPTURE_RE = re.compile(r"capture #(\d+) : (\d+) impulsions, de (-?\d+) us à (-?\d+) us")


def lit_dumps(chemin: pathlib.Path) -> list[list[int]]:
    """Ramène la liste des captures, chacune étant la liste de ses durées signées (en µs)."""
    captures: list[list[int]] = []
    courant: list[int] = []
    total_attendu = None
    _ansi = _re.compile(r"\x1b\[[0-9;]*m")
    for ligne in _ansi.sub("", chemin.read_text(encoding="utf-8", errors="replace")).splitlines():
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
            continue                      # trou entre deux rafales, comme le firmware
        bits.append(("1" if (1 - niveau) else "0") * ticks if inverser else ("1" if niveau else "0") * ticks)
    return "".join(bits)


def trame_dans_bits(bits: str):
    """Cherche une trame valide à tout décalage de bit. Renvoie (octets, décalage) ou None."""
    for decalage in range(min(8, len(bits))):
        utilisable = (len(bits) - decalage) // 8 * 8
        octets = bytes(int(bits[decalage + i: decalage + i + 8], 2) for i in range(0, utilisable, 8))
        for i in range(len(octets) - FRAME_BYTES + 1):
            b = octets[i:i + FRAME_BYTES]
            if b[0] != 0xAA or b[1] != 0x00:
                continue
            if (sum(b[0:19]) & 0xFF) != b[19] or b[20] != ((b[18] + 1) & 0xFF):
                continue
            return b, decalage, i
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("dump", type=pathlib.Path)
    ap.add_argument("--json", type=pathlib.Path, default=None)
    args = ap.parse_args()

    captures = lit_dumps(args.dump)
    print(f"{len(captures)} capture(s) lue(s) dans {args.dump}")
    rapport = []
    for nc, durees in enumerate(captures, 1):
        print(f"\ncapture {nc} : {len(durees)} durées, "
              f"de {min(abs(x) for x in durees)} à {max(abs(x) for x in durees)} µs")
        trouve = None
        for periode in PERIODS:
            for inverser in (False, True):
                bits = bits_depuis_durees(durees, periode, inverser)
                if len(bits) < FRAME_BYTES * 8:
                    continue
                r = trame_dans_bits(bits)
                if r:
                    b, decalage, position = r
                    print(f"  >>> TRAME VALIDE : période {periode} µs, "
                          f"{'inversée' if inverser else 'normale'}, décalage bit {decalage}, "
                          f"position octet {position}")
                    print(f"      brut : {' '.join(f'{x:02x}' for x in b)}")
                    trouve = {"periode": periode, "inverse": inverser, "octets": list(b)}
                    break
            if trouve:
                break
        if not trouve:
            # Rien de valide : on montre ce que donnerait la meilleure période, pour juger de visu.
            for periode in PERIODS[:2]:
                bits = bits_depuis_durees(durees, periode, False)
                octets = bytes(int(bits[i:i + 8], 2) for i in range(0, len(bits) // 8 * 8, 8))[:12]
                print(f"  (période {periode} µs, sans inversion) premiers octets : "
                      f"{' '.join(f'{x:02x}' for x in octets)}")
        rapport.append({"capture": nc, "nb_durees": len(durees), "trame": trouve})

    if args.json:
        args.json.write_text(json.dumps(rapport, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nrapport écrit : {args.json}")
    valides = sum(1 for r in rapport if r["trame"])
    print(f"\n{valides} capture(s) sur {len(rapport)} portent une trame VALIDE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
