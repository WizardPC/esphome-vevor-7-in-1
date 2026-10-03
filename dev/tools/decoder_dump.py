#!/usr/bin/env python3
"""Décode hors de la carte les durées brutes ramenées par le bouton « Dump impulsions ».

Pourquoi : quand la carte reçoit des impulsions (compteur de captures qui monte) mais ne publie
aucune trame, il faut savoir si le flux BRUT contient une trame valide — donc si le défaut est dans
l'assembleur du firmware, ou dans la réception elle-même.

Ce script rejoue exactement la quantification du firmware (voir `timings_to_bits` dans
`esphome/components/vevor_7in1/vevor_protocol.h`) :

    niveau   = 1 si la durée est positive, 0 sinon      (la polarité GDO0 n'est pas présumée)
    nb ticks = arrondi(durée / période)                  (au moins 1, au plus MAX_RUN_BITS)
    chaque tick produit un bit de ce niveau

puis cherche, dans le flux de bits, une trame de 21 octets conforme : en-tête AA 00, somme de
contrôle rtl_433 et compteur cohérent — en essayant les 4 périodes candidates, les deux polarités
et les 8 décalages de bit.

Usage :
    tools/decoder_dump.py logs/dump_brut.log [--json logs/dump_decode.json]

Code retour :
    0  au moins une capture lue ; « 0 trame valide » est un RÉSULTAT négatif ;
    2  échec technique (fichier illisible) ;
    3  MESURE NULLE : aucune capture (aucune ligne « capture # »/« impulsions ») — rien n'a été mesuré.
"""

from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _common import (ANSI, RC_ERREUR, RC_MESURE_NULLE, RC_OK,  # noqa: E402
                     atomic_write_json)

import re

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
            continue                      # trou entre deux rafales, comme le firmware
        bits.append(("1" if (1 - niveau) else "0") * ticks if inverser else ("1" if niveau else "0") * ticks)
    return "".join(bits)


def porte_de_plausibilite(b: bytes):
    """Mêmes contrôles PHYSIQUES que le firmware (includes/vevor_protocol.h).

    Renvoie None si la trame est plausible, sinon le nom du refus. Sans cette porte, cet outil
    annonçait une trame « valide » pour des candidats que le firmware refuse : mesuré le 03/10,
    une trame satisfaisant en-tête + checksum + compteur donnait une direction de 3841° et une
    température de 3636 °C. Un tel candidat est un FAUX POSITIF, pas une réception — c'est
    exactement le piège documenté dans vevor_protocol.h.
    """
    x = bytearray(b)
    for i in (8, 9, 11, 12, 13, 14, 16, 17):   # décalage de 1 documenté sur ces octets
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
    """Cherche une trame conforme à tout décalage de bit.

    Renvoie (octets, décalage, position, refus) : `refus` vaut None si la trame passe aussi la
    porte de plausibilité, sinon la raison du refus — l'appelant ne doit PAS l'annoncer valide.
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
    ap.add_argument("--json", default=None, help="rapport JSON (relatif = racine du projet)")
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
            # Rien de valide : on montre ce que donnerait la meilleure période, pour juger de visu.
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
