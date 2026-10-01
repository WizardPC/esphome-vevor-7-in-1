#!/usr/bin/env python3
"""Encodeur de trames Vevor 7-en-1 — indépendant du décodeur, pour les tests hors matériel.

C'est le pendant inverse de `esphome/includes/vevor_7in1.h` : il part de valeurs physiques et
produit les 21 octets bruts, en appliquant l'encodage de la spec (`references/PROTOCOL.md`,
elle-même issue de `rtl_433/src/devices/vevor_7in1.c`) : décalage +1 sur les octets
8, 9, 11, 12, 13, 14, 16, 17, checksum = somme(b[0..18]) & 0xFF, et b[20] = (b[18]+1) & 0xFF.

Il sert de **référence indépendante** : si l'encodeur Python et le décodeur C++ sont d'accord,
et que la trame d'exemple de rtl_433 est reproduite octet pour octet, on a la preuve que les
deux implémentations comprennent la même spec.

Usage :
    frames.py --selfcheck          # vérifie que l'encodeur reproduit la trame de rtl_433
    frames.py --vectors            # écrit tests/vectors.h pour le test C++
    frames.py --pulses             # écrit tests/pulses.h (scénarios d'impulsions, sans matériel)
"""
from __future__ import annotations

import argparse
import pathlib
import random
import sys

FRAME_BYTES = 21
SHIFTED = (8, 9, 11, 12, 13, 14, 16, 17)
# Trame d'exemple de la documentation rtl_433 (vevor_7in1.c), 21 octets utiles.
RTL433_SAMPLE = "aa 00 f8 f7 9d 02 e3 32 01 0e 03 02 0b 01 38 02 39 7a 86 e0 87"


def _u8(v: int) -> int:
    return v & 0xFF


def encode(
    *,
    sensor_id: int = 0x1A2B,
    channel: int = 0,
    battery_low: bool = False,
    temp_c: float = 18.4,
    humidity: int = 72,
    wind_kmh: float = 3.2,
    gust_kmh: float = 5.6,
    wind_dir_deg: int = 214,
    rain_mm: float = 12.6,
    uv: int = 2,
    lux: int = 18400,
    tx_counter: int = 0x40,
    corrupt_checksum: bool = False,
    bad_counter: bool = False,
    bad_header: bool = False,
) -> list[int]:
    """Construit une trame brute de 21 octets. Les options `bad_*` forment des trames invalides."""
    temp_raw = int(round(temp_c * 10)) + 500
    wind_raw = int(round(wind_kmh * 8.333))
    gust_raw = int(round(gust_kmh * 1.25))
    rain_raw = int(round(rain_mm / 0.233))
    uv_raw = uv + 1
    lux_raw = lux if lux < 0x8000 else (0x8000 | (lux // 10))

    # Bornes réelles de l'encodage : les champs portés par les octets décalés (+1) ne peuvent
    # pas dépasser 0xFEFE, sinon le +1 déborderait sur 0xFF. C'est exactement ce qui fixe la
    # pluie maximale à 65 278 ticks = 15 209,8 mm. Les champs non décalés (temp, rafale) vont
    # jusqu'à leur taille native.
    limits = (("temp", temp_raw, 0xFFFF), ("wind", wind_raw, 0xFEFE),
              ("rain", rain_raw, 0xFEFE), ("lux", lux_raw, 0xFEFE),
              ("gust", gust_raw, 0xFF), ("uv", uv_raw, 0x1F))
    for name, value, vmax in limits:
        if value < 0 or value > vmax:
            raise ValueError(
                f"{name}: valeur {value} hors de ce que la trame peut porter (max 0x{vmax:X})"
            )

    b = [0] * FRAME_BYTES
    b[0] = 0x00 if bad_header else 0xAA
    b[1] = (channel & 0x0F)  # nibble haut = type de capteur (0)
    b[2] = (sensor_id >> 8) & 0xFF
    b[3] = sensor_id & 0xFF
    b[4] = 0x9D if battery_low else 0x1D
    b[5] = (temp_raw >> 8) & 0xFF
    b[6] = temp_raw & 0xFF
    b[7] = humidity & 0xFF
    b[8] = _u8((wind_raw >> 8) + 1)
    b[9] = _u8((wind_raw & 0xFF) + 1)
    b[10] = gust_raw & 0xFF
    b[11] = _u8(((wind_dir_deg >> 8) & 0x0F) + 1)
    b[12] = _u8((wind_dir_deg & 0xFF) + 1)
    b[13] = _u8((rain_raw >> 8) + 1)
    b[14] = _u8((rain_raw & 0xFF) + 1)
    b[15] = uv_raw & 0x1F
    b[16] = _u8((lux_raw >> 8) + 1)
    b[17] = _u8((lux_raw & 0xFF) + 1)
    b[18] = tx_counter & 0xFF
    b[19] = sum(b[0:19]) & 0xFF
    b[20] = _u8((b[18] + 1) & 0xFF)

    if corrupt_checksum:
        b[19] = _u8(b[19] + 0x55)
    if bad_counter:
        b[20] = _u8(b[20] + 0x07)
    return b


def decode_reference(b: list[int]) -> dict:
    """Décodage de contrôle, indépendant, utilisé pour calculer les valeurs attendues."""
    d = list(b)
    for i in SHIFTED:
        d[i] = _u8(d[i] - 1)
    lux_raw = (d[16] << 8) | d[17]
    return {
        "id": (b[2] << 8) | b[3],
        "channel": b[1] & 0x0F,
        "battery_low": bool(b[4] & 0x80),
        "temp_c": round((((b[5] << 8) | b[6]) - 500) * 0.1, 1),
        "humidity": b[7],
        "wind_kmh": round(((d[8] << 8) | d[9]) / 8.333, 2),
        "gust_kmh": round(b[10] / 1.25, 2),
        "wind_dir_deg": ((d[11] & 0x0F) << 8) | d[12],
        "rain_mm": round(((d[13] << 8) | d[14]) * 0.233, 2),
        "uv": (b[15] & 0x1F) - 1,
        "lux": (lux_raw & 0x7FFF) * 10 if lux_raw & 0x8000 else lux_raw,
        "tx_counter": b[18],
    }


def _scenarios() -> list[tuple[str, list[int], bool]]:
    """(nom, trame brute, attendue valide)."""
    out: list[tuple[str, list[int], bool]] = []
    sample = [int(x, 16) for x in RTL433_SAMPLE.split()]
    out.append(("reference_rtl433", sample, True))
    out.append(("nominal", encode(), True))
    out.append(("temperatures_negatives", encode(temp_c=-12.3, humidity=91), True))
    out.append(("pluie_maximale_encodable", encode(rain_mm=15209.8), True))
    out.append(("lux_eleve_x10", encode(lux=98000, uv=11), True))
    out.append(("compteur_tx_ff", encode(tx_counter=0xFF), True))
    out.append(("batterie_faible", encode(battery_low=True), True))
    out.append(("vent_nul", encode(wind_kmh=0.0, gust_kmh=0.0, wind_dir_deg=0), True))
    # ATTENTION : le décodeur de rtl_433 — et donc le nôtre — exige `b[1] == 0` exactement.
    # Les stations de cette famille émettent type de capteur = 0 et canal = 0 ; exiger 0 est un
    # filtre à bruit volontaire. Une trame à canal non nul doit donc être REJETÉE, et ce
    # scénario verrouille ce comportement (il ne doit pas être « assoupli » par mégarde).
    out.append(("canal_non_nul_rejete", encode(channel=1, sensor_id=0x7C41), False))
    out.append(("checksum_corrompu", encode(corrupt_checksum=True), False))
    out.append(("compteur_incoherent", encode(bad_counter=True), False))
    out.append(("en_tete_invalide", encode(bad_header=True), False))
    return out


# ---------------------------------------------------------------------------------------
# Scénarios d'IMPULSIONS : la chaîne complète telle qu'elle tourne sur la carte
# (remote_receiver → durées signées → bits NRZ → trame), testée sans matériel.
# ---------------------------------------------------------------------------------------
# Motif d'accroche transmis avant les 21 octets utiles : le préambule se termine par CA CA 54.
PULSE_PREAMBLE = (0xAA, 0xAA, 0xCA, 0xCA, 0x54)
# Espace observé avant la rafale chez le montage témoin (x[0] ≈ -1300 µs).
PULSE_LEAD_GAP_US = -1300
# Durée d'un trou inter-rafales dans un scénario : bien au-delà de MAX_RUN_BITS (64) périodes.
PULSE_GAP_US = -8000


def bits_from_bytes(data) -> list[int]:
    """Octets → bits, MSB d'abord (ordre de transmission du protocole)."""
    out: list[int] = []
    for byte in data:
        for k in range(8):
            out.append((byte >> (7 - k)) & 1)
    return out


def timings_from_bits(bits: list[int], period_us: int, *, invert: bool = False,
                      lead_gap_us: int = PULSE_LEAD_GAP_US, gap_us=None) -> list[int]:
    """Bits NRZ → durées signées façon `remote_receiver` (positif = mark = 1).

    Chaque niveau tenu est fusionné en UNE impulsion de k périodes : c'est exactement ce que
    produit un signal NRZ démodulé, et ce que le décodeur doit reconstituer.
    `gap_us` insère un trou inter-rafales après l'espace d'attaque.
    """
    out: list[int] = [lead_gap_us]
    if gap_us is not None:
        out.append(gap_us)
    i = 0
    while i < len(bits):
        j = i
        while j < len(bits) and bits[j] == bits[i]:
            j += 1
        duration = (j - i) * period_us
        level = bits[i]
        if invert:
            level = 1 - level
        out.append(duration if level else -duration)
        i = j
    return out


def _biased(timings: list[int], bias_us: int) -> list[int]:
    """Ajoute un biais ABSOLU à toutes les impulsions (l'espace d'attaque n'est pas une mesure
    de bit : il est laissé tel quel)."""
    out = [timings[0]]
    for t in timings[1:]:
        magnitude = abs(t) + bias_us
        out.append(magnitude if t > 0 else -magnitude)
    return out


def _pulse_scenarios() -> list[tuple[str, list[int], bool, dict]]:
    """(nom, durées d'impulsions, attendu valide, valeurs de contrôle)."""
    frame = encode(sensor_id=0x84CB, temp_c=14.2, humidity=86, wind_kmh=11.2, gust_kmh=12.8,
                   wind_dir_deg=283, rain_mm=57.8, uv=0, lux=0, tx_counter=0x40)
    values = decode_reference(frame)
    bits = bits_from_bytes(list(PULSE_PREAMBLE) + frame)
    out: list[tuple[str, list[int], bool, dict]] = []

    out.append(("impulsions_nominales", timings_from_bits(bits, 90), True, values))
    out.append(("impulsions_polarite_inversee", timings_from_bits(bits, 90, invert=True), True, values))
    out.append(("impulsions_periode_88us", timings_from_bits(bits, 88), True, values))
    # Capture qui commence au MILIEU du préambule : cas courant, le RMT démarre quand la rafale a
    # déjà commencé. Le décodeur ne doit pas exiger le préambule entier pour autant.
    out.append(("impulsions_capture_tronquee", timings_from_bits(bits[13:], 90), True, values))
    # Trou inter-rafales dans la capture : à SAUTER, pas à considérer comme une capture perdue.
    out.append(("impulsions_trou_inter_rafales", timings_from_bits(bits, 90, gap_us=PULSE_GAP_US),
                True, values))
    # Gigue de ±2 % sur chaque impulsion : ce que produisent deux horloges indépendantes
    # (émetteur + RMT à 1 MHz). La tolérance de l'arrondi par impulsion est ABSOLUE (±45 µs,
    # soit une demi-période) : une erreur proportionnelle ne peut donc pas dépasser ~5 % sur la
    # plus longue série de bits de la trame (10 bits ici). Un scénario à ±8 % serait un test
    # impossible pour tout décodeur qui arrondit impulsion par impulsion (y compris le témoin) —
    # il ne serait pas un test, juste une envie.
    rnd = random.Random(20260930)
    jittered = [round(t * (1.0 + rnd.uniform(-0.02, 0.02)))
                for t in timings_from_bits(bits, 90)]
    out.append(("impulsions_gigue_2pct", jittered, True, values))
    # Biais ABSOLU sur toutes les impulsions (récepteur mal centré) : ±30 µs, dans la tolérance
    # d'une demi-période. C'est la forme d'erreur réellement observée sur ce montage (impulsions
    # mesurées à 86 et 267 µs au lieu de 90 et 270 → −4 et −3 µs), et celle que le projet de
    # référence corrige par une liste de décalages. Notre arrondi par impulsion l'absorbe
    # directement, sans liste de candidats.
    out.append(("impulsions_biais_bas_30us", _biased(timings_from_bits(bits, 90), -30), True,
                values))
    out.append(("impulsions_biais_haut_30us", _biased(timings_from_bits(bits, 90), 30), True,
                values))
    # Trop court pour porter une trame (seuil MIN_TIMINGS = 40 impulsions).
    out.append(("impulsions_trop_courtes", timings_from_bits(bits, 90)[:20], False, {}))
    # Accroche trouvée mais trame corrompue : le checksum doit refuser.
    bad = encode(sensor_id=0x84CB, temp_c=14.2, corrupt_checksum=True)
    out.append(("impulsions_checksum_invalide",
                timings_from_bits(bits_from_bytes(list(PULSE_PREAMBLE) + bad), 90), False, {}))
    # Bruit pur : aucune trame ne doit en sortir (le bruit ne fabrique pas un checksum valide).
    for seed in (1, 2, 3):
        noise = random.Random(seed)
        durations = [noise.randint(-600, 600) for _ in range(200)]
        durations[0] = PULSE_LEAD_GAP_US
        out.append((f"impulsions_bruit_{seed}", durations, False, {}))
    return out


def emit_pulses(path: pathlib.Path) -> int:
    lines = [
        "// GÉNÉRÉ par tests/frames.py — ne pas éditer à la main.",
        "#pragma once",
        "#include <cstdint>",
        "#include <cstddef>",
        "",
        "struct VevorPulseScenario {",
        "  const char *name;",
        "  const int32_t *timings;",
        "  size_t count;",
        "  bool valid;",
        "  uint16_t id;",
        "  float temp_c;",
        "  float rain_mm;",
        "};",
        "",
    ]
    rows = []
    for index, (name, timings, valid, values) in enumerate(_pulse_scenarios()):
        array = f"PULSE_{index}"
        body = ", ".join(str(int(t)) for t in timings)
        lines += [
            f"static const int32_t {array}[] = {{{body}}};",
            "",
        ]
        if valid:
            rows.append(
                f'  {{"{name}", {array}, {len(timings)}, true, {values["id"]}, '
                f'{values["temp_c"]}f, {values["rain_mm"]}f}},'
            )
        else:
            rows.append(f'  {{"{name}", {array}, {len(timings)}, false, 0, 0.0f, 0.0f}},')
    lines += [
        "static const VevorPulseScenario VEVOR_PULSE_VECTORS[] = {",
    ] + rows + [
        "};",
        "",
        f"static const int VEVOR_PULSE_COUNT = {len(rows)};",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    print(f"pulses.h écrit : {len(rows)} scénarios d'impulsions")
    return 0


def selfcheck() -> int:
    """L'encodeur doit reproduire la trame de référence rtl_433 octet pour octet."""
    expected = [int(x, 16) for x in RTL433_SAMPLE.split()]
    values = decode_reference(expected)
    produced = encode(
        sensor_id=values["id"], channel=values["channel"], battery_low=values["battery_low"],
        temp_c=values["temp_c"], humidity=values["humidity"], wind_kmh=values["wind_kmh"],
        gust_kmh=values["gust_kmh"], wind_dir_deg=values["wind_dir_deg"],
        rain_mm=values["rain_mm"], uv=values["uv"], lux=values["lux"],
        tx_counter=values["tx_counter"],
    )
    got = " ".join(f"{x:02x}" for x in produced)
    want = " ".join(f"{x:02x}" for x in expected)
    if got != want:
        print("SELFCHECK ÉCHEC — l'encodeur ne reproduit pas la trame de rtl_433")
        print(f"  attendu : {want}")
        print(f"  obtenu  : {got}")
        return 1
    print(f"SELFCHECK OK — trame de rtl_433 reproduite octet pour octet : {got}")
    return 0


def emit_vectors(path: pathlib.Path) -> int:
    lines = [
        "// GÉNÉRÉ par tests/frames.py — ne pas éditer à la main.",
        "#pragma once",
        "#include <cstdint>",
        "",
        "struct VevorVector {",
        "  const char *name;",
        "  uint8_t raw[21];",
        "  bool valid;",
        "  uint16_t id;",
        "  uint8_t channel;",
        "  bool battery_low;",
        "  float temp_c;",
        "  uint8_t humidity;",
        "  float wind_kmh;",
        "  float gust_kmh;",
        "  uint16_t wind_dir_deg;",
        "  float rain_mm;",
        "  int uv;",
        "  uint32_t lux;",
        "  uint8_t tx_counter;",
        "};",
        "",
        "static const VevorVector VEVOR_VECTORS[] = {",
    ]
    count = 0
    for name, raw, valid in _scenarios():
        values = decode_reference(raw) if valid else {}
        raw_txt = ", ".join(f"0x{x:02x}" for x in raw)
        if valid:
            row = (
                f'  {{"{name}", {{{raw_txt}}}, true, {values["id"]}, {values["channel"]}, '
                f'{"true" if values["battery_low"] else "false"}, {values["temp_c"]}f, '
                f'{values["humidity"]}, {values["wind_kmh"]}f, {values["gust_kmh"]}f, '
                f'{values["wind_dir_deg"]}, {values["rain_mm"]}f, {values["uv"]}, '
                f'{values["lux"]}, {values["tx_counter"]}}},'
            )
        else:
            row = f'  {{"{name}", {{{raw_txt}}}, false, 0, 0, false, 0, 0, 0, 0, 0, 0, 0, 0, 0}},'
        lines.append(row)
        count += 1
    lines += ["};", "", f"static const int VEVOR_VECTOR_COUNT = {count};", ""]
    path.write_text("\n".join(lines), encoding="utf-8")
    print(f"vectors.h écrit : {count} scénarios")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selfcheck", action="store_true")
    ap.add_argument("--vectors", action="store_true")
    ap.add_argument("--pulses", action="store_true")
    args = ap.parse_args()
    here = pathlib.Path(__file__).resolve().parent
    if args.selfcheck:
        return selfcheck()
    if args.vectors:
        return emit_vectors(here / "vectors.h")
    if args.pulses:
        return emit_pulses(here / "pulses.h")
    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main())
