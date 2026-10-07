#!/usr/bin/env python3
"""Vevor 7-in-1 frame encoder — independent of the decoder, for host-side tests.

Inverse of `esphome/components/vevor_7in1/vevor_7in1.h`: from physical values to the 21 raw bytes
per the spec (references/PROTOCOL.md): +1 offset on bytes 8, 9, 11-14, 16, 17, checksum =
sum(b[0..18]) & 0xFF, b[20] = (b[18]+1) & 0xFF. Independent reference: byte-level agreement with
the C++ decoder and the rtl_433 sample frame proves both read the same spec.

Usage:
    frames.py --selfcheck          # checks the encoder reproduces the rtl_433 frame
    frames.py --vectors            # writes tests/vectors.h for the C++ test
    frames.py --pulses             # writes tests/pulses.h (pulse scenarios, no hardware)
"""
from __future__ import annotations

import argparse
import pathlib
import random
import sys

FRAME_BYTES = 21
SHIFTED = (8, 9, 11, 12, 13, 14, 16, 17)
# Sample frame from the rtl_433 documentation (vevor_7in1.c), 21 usable bytes.
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
    """Build a 21-byte raw frame. The `bad_*` options produce invalid frames."""
    temp_raw = int(round(temp_c * 10)) + 500
    wind_raw = int(round(wind_kmh * 8.333))
    gust_raw = int(round(gust_kmh * 1.25))
    rain_raw = int(round(rain_mm / 0.233))
    uv_raw = uv + 1
    lux_raw = lux if lux < 0x8000 else (0x8000 | (lux // 10))

    # Real encoding bounds: fields on shifted bytes (+1) cannot exceed 0xFEFE, or the +1 would
    # overflow to 0xFF — this fixes max rain at 65 278 ticks = 15 209.8 mm. Unshifted fields
    # (temp, gust) go up to their native width.
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
    b[1] = (channel & 0x0F)  # high nibble = sensor type (0)
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
    """Independent check decode, used to compute the expected values."""
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


def _scenarios() -> list[tuple[str, list[int], bool, str]]:
    """(name, raw frame, expected valid, expected reject reason — "" if the frame is valid)."""
    out: list[tuple[str, list[int], bool, str]] = []
    sample = [int(x, 16) for x in RTL433_SAMPLE.split()]
    out.append(("reference_rtl433", sample, True, ""))
    out.append(("nominal", encode(), True, ""))
    out.append(("temperatures_negatives", encode(temp_c=-12.3, humidity=91), True, ""))
    out.append(("pluie_maximale_encodable", encode(rain_mm=15209.8), True, ""))
    out.append(("lux_eleve_x10", encode(lux=98000, uv=11), True, ""))
    out.append(("tx_counter_ff", encode(tx_counter=0xFF), True, ""))
    out.append(("batterie_faible", encode(battery_low=True), True, ""))
    out.append(("vent_nul", encode(wind_kmh=0.0, gust_kmh=0.0, wind_dir_deg=0), True, ""))
    # HIGH bounds of the plausibility gate, ACCEPTED: it guards against bit-shifted frames, not
    # normal values, so no PHYSICALLY possible value may be rejected. The wind bound (1500 ticks
    # / 8.333 = 180.007) now allows a rounding margin (vevor_protocol.h, WIND_LIMIT_MARGE_KMH).
    out.append(("vent_180_accepte", encode(wind_kmh=180.0), True, ""))
    out.append(("rafale_180_acceptee", encode(gust_kmh=180.0), True, ""))
    out.append(("humidity_100_acceptee", encode(humidity=100), True, ""))
    out.append(("uv_16_accepte", encode(uv=16), True, ""))
    out.append(("direction_359_acceptee", encode(wind_dir_deg=359), True, ""))
    out.append(("temperature_60_acceptee", encode(temp_c=60.0), True, ""))
    out.append(("temperature_moins40_acceptee", encode(temp_c=-40.0), True, ""))
    # Each BRANCH of the gate, exercised by a test frame: well formed (header + checksum +
    # counter) but physically impossible → rejected WITH the matching reason. Previously only
    # the "direction" branch had a frame (review round 2, §4).
    out.append(("humidity_101_rejetee", encode(humidity=101), False, "humidity"))
    out.append(("temperature_70_rejetee", encode(temp_c=70.0), False, "temperature"))
    out.append(("temperature_moins45_rejetee", encode(temp_c=-45.0), False, "temperature"))
    out.append(("vent_200_rejete", encode(wind_kmh=200.0), False, "wind"))
    # Smallest encodable step above the bound: 1501 ticks / 8.333 = 180.13 > 180.01 (bound +
    # margin) → rejected. Tight counter-check of the false rejection fixed above.
    out.append(("vent_premier_cran_au_dessus_rejete", encode(wind_kmh=180.13), False, "wind"))
    out.append(("rafale_200_rejetee", encode(gust_kmh=200.0), False, "wind"))
    out.append(("uv_20_rejete", encode(uv=20), False, "uv"))
    out.append(("uv_negatif_rejete", encode(uv=-1), False, "uv"))
    # WARNING: the rtl_433 decoder — and ours — requires `b[1] == 0` exactly. Stations of this
    # family emit sensor type = 0 and channel = 0, so requiring 0 is a deliberate noise filter.
    # A non-zero-channel frame must be REJECTED; this scenario locks that in, not to be relaxed.
    out.append(("canal_non_nul_rejete", encode(channel=1, sensor_id=0x7C41), False, "header"))
    out.append(("checksum_corrompu", encode(corrupt_checksum=True), False, "checksum"))
    out.append(("compteur_incoherent", encode(bad_counter=True), False, "tx_counter"))
    out.append(("en_tete_invalide", encode(bad_header=True), False, "header"))
    return out


# ---------------------------------------------------------------------------------------
# PULSE scenarios: the full on-board chain (remote_receiver → signed durations → NRZ bits →
# frame), tested without hardware.

# Sync pattern sent before the 21 usable bytes: the preamble ends with CA CA 54.
PULSE_PREAMBLE = (0xAA, 0xAA, 0xCA, 0xCA, 0x54)
# Gap observed before the burst on the reference rig (x[0] ≈ -1300 µs).
PULSE_LEAD_GAP_US = -1300
# Inter-burst hole in a scenario: well beyond MAX_RUN_BITS (64) periods.
PULSE_GAP_US = -8000


def bits_from_bytes(data) -> list[int]:
    """Bytes → bits, MSB first (the protocol's transmission order)."""
    out: list[int] = []
    for byte in data:
        for k in range(8):
            out.append((byte >> (7 - k)) & 1)
    return out


def timings_from_bits(bits: list[int], period_us: int, *, invert: bool = False,
                      lead_gap_us: int = PULSE_LEAD_GAP_US, gap_us=None) -> list[int]:
    """NRZ bits → `remote_receiver`-style signed durations (positive = mark = 1).

    Each held level is merged into ONE pulse of k periods, exactly what a demodulated NRZ signal
    produces and what the decoder must reconstruct. `gap_us` inserts an inter-burst hole after
    the lead gap.
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
    """Add an ABSOLUTE bias to all pulses (the lead gap is not a bit measurement: it is left
    as is)."""
    out = [timings[0]]
    for t in timings[1:]:
        magnitude = abs(t) + bias_us
        out.append(magnitude if t > 0 else -magnitude)
    return out


def _pulse_scenarios() -> list[tuple[str, list[int], bool, dict, int]]:
    """(name, pulse durations, expected valid, reference values, emission period)."""
    frame = encode(sensor_id=0x84CB, temp_c=14.2, humidity=86, wind_kmh=11.2, gust_kmh=12.8,
                   wind_dir_deg=283, rain_mm=57.8, uv=0, lux=0, tx_counter=0x40)
    values = decode_reference(frame)
    bits = bits_from_bytes(list(PULSE_PREAMBLE) + frame)
    out: list[tuple[str, list[int], bool, dict, int]] = []

    out.append(("pulses_nominales", timings_from_bits(bits, 90), True, values, 90))
    out.append(("pulses_polarite_inversee", timings_from_bits(bits, 90, invert=True), True,
                values, 90))
    # Each CANDIDATE period gets a burst at ITS period: the decoder must decode it as the only
    # candidate (real run at 88, 89 AND 87 — see test_period_selection). One 88 µs burst was not
    # enough: the decoder fell back to 90 and "== 90" only tested list order.
    out.append(("pulses_periode_88us", timings_from_bits(bits, 88), True, values, 88))
    out.append(("pulses_periode_89us", timings_from_bits(bits, 89), True, values, 89))
    out.append(("pulses_periode_87us", timings_from_bits(bits, 87), True, values, 87))
    # Capture starting MID-preamble: common case, RMT starts after the burst has begun. The
    # decoder must not require the whole preamble.
    out.append(("pulses_capture_tronquee", timings_from_bits(bits[13:], 90), True, values, 90))
    # Inter-burst hole in the capture: SKIP it, do not treat it as a lost capture.
    out.append(("pulses_trou_inter_rafales", timings_from_bits(bits, 90, gap_us=PULSE_GAP_US),
                True, values, 90))
    # ±2 % jitter per pulse: two independent clocks (transmitter + 1 MHz RMT). Per-pulse rounding
    # tolerance is ABSOLUTE (±45 µs = half a period), so a proportional error stays under ~5 %
    # over the longest bit run (10 bits); ±8 % is untestable (dev/docs/bit-jitter-analysis.md).
    rnd = random.Random(20260930)
    jittered = [round(t * (1.0 + rnd.uniform(-0.02, 0.02)))
                for t in timings_from_bits(bits, 90)]
    out.append(("pulses_gigue_2pct", jittered, True, values, 90))
    # ABSOLUTE bias on all pulses (off-centre receiver): ±30 µs, within half a period. The
    # observed error on this rig (pulses at 86 and 267 µs instead of 90 and 270 → −4 and −3 µs),
    # which the reference project fixes with a shift list; per-pulse rounding absorbs it directly.
    out.append(("pulses_biais_bas_30us", _biased(timings_from_bits(bits, 90), -30), True,
                values, 90))
    out.append(("pulses_biais_haut_30us", _biased(timings_from_bits(bits, 90), 30), True,
                values, 90))
    # Frame with a LONG run of identical bits (id = 0, negative temp, zero humidity → 28 bits):
    # the only PERIOD-SENSITIVE shape (a short run decodes the same at 87-90 µs). Proves candidate
    # scanning CONTINUES after a failure (test_period_selection): at 88 µs no decode, at 90 µs yes.
    longue = encode(sensor_id=0x0000, temp_c=-30.0, humidity=0, wind_kmh=0.0, gust_kmh=0.0,
                    wind_dir_deg=0, rain_mm=0.0, uv=0, lux=0, tx_counter=0)
    out.append(("pulses_trame_longue",
                timings_from_bits(bits_from_bytes(list(PULSE_PREAMBLE) + longue), 90), True,
                decode_reference(longue), 90))
    # Too short to carry a frame (MIN_TIMINGS threshold = 40 pulses).
    out.append(("pulses_trop_courtes", timings_from_bits(bits, 90)[:20], False, {}, 0))
    # Sync found but frame corrupted: the checksum must reject.
    bad = encode(sensor_id=0x84CB, temp_c=14.2, corrupt_checksum=True)
    out.append(("pulses_checksum_invalide",
                timings_from_bits(bits_from_bytes(list(PULSE_PREAMBLE) + bad), 90), False, {}, 0))
    # Pure noise: no frame must come out (noise does not fabricate a valid checksum).
    for seed in (1, 2, 3):
        noise = random.Random(seed)
        durations = [noise.randint(-600, 600) for _ in range(200)]
        durations[0] = PULSE_LEAD_GAP_US
        out.append((f"pulses_bruit_{seed}", durations, False, {}, 0))
    return out


def emit_captures(path: pathlib.Path, source: pathlib.Path) -> int:
    """Write tests/captures.h: the REAL bursts recorded from the station, replayed by the C++ test
    as regression vectors. They carry the project's acceptance criterion (5 of 6 decodable) and
    alone prove the decoder on real signal; synthetic scenarios only describe what was thought of.
    """
    captures: list[list[int]] = []
    for line in source.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        captures.append([int(v) for v in line.split()])
    lines = [
        "// GÉNÉRÉ par tests/frames.py --captures — ne pas éditer à la main.",
        "// Source : tests/data/captures_reelles.txt (rafales réelles du 03/10).",
        "#pragma once",
        "#include <cstdint>",
        "#include <cstddef>",
        "",
    ]
    for index, capture in enumerate(captures):
        body = ", ".join(str(v) for v in capture)
        lines += [f"static const int32_t CAPTURE_{index}[] = {{{body}}};", ""]
    lines += [
        "struct VevorRealCapture {",
        "  const char *name;",
        "  const int32_t *timings;",
        "  size_t count;",
        "};",
        "",
        "static const VevorRealCapture VEVOR_REAL_CAPTURES[] = {",
    ]
    lines += [f'  {{"capture_reelle_{i}", CAPTURE_{i}, {len(c)}}},' for i, c in enumerate(captures)]
    lines += [
        "};",
        "",
        f"static const int VEVOR_REAL_CAPTURE_COUNT = {len(captures)};",
        "// Les rafales décodables portent la MÊME mesure (même station, même température, même",
        "// humidité, même direction) : leur préfixe est identique. Le compteur TX et la somme",
        "// diffèrent d'une rafale à l'autre — c'est normal, elles viennent d'émissions différentes.",
        "static const uint8_t VEVOR_CAPTURE_PREFIX[11] = {0xAA, 0x00, 0x84, 0xCB, 0x16,",
        "                                                0x02, 0x90, 0x50, 0x01, 0x01, 0x00};",
        "static const int VEVOR_CAPTURE_PREFIX_LEN = 11;",
        "// 2 des 6 rafales ne sont pas décodables — et ne doivent PAS l'être : la seule solution",
        "// que trouvait l'ancienne repairation par insertion était une FABRICATION. Pour la rafale 3",
        "// (mesurée le 04/10) elle publiait pluie 536,4 mm contre 59,2 mm dans les rafales voisines,",
        "// avec un bit inséré au niveau opposé à l'impulsion — physiquement impossible ; le garde-fou",
        "// de pluie la refusait, elle n'est jamais arrivée dans Home Assistant.",
        "// Voir docs/zero-wind-fabrication.md. Critère : 4 rafales décodables sur 6.",
        "static const int VEVOR_CAPTURE_ATTENDUES = 4;",
        "static const int VEVOR_CAPTURE_CONTRE_EXEMPLES[] = {2, 3};",
        "static const int VEVOR_CAPTURE_CONTRE_EXEMPLE_COUNT = 2;",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    print(f"captures.h écrit : {len(captures)} rafales réelles")
    return len(captures)


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
        "  int32_t period_us;",
        "};",
        "",
    ]
    rows = []
    for index, (name, timings, valid, values, period) in enumerate(_pulse_scenarios()):
        array = f"PULSE_{index}"
        body = ", ".join(str(int(t)) for t in timings)
        lines += [
            f"static const int32_t {array}[] = {{{body}}};",
            "",
        ]
        if valid:
            rows.append(
                f'  {{"{name}", {array}, {len(timings)}, true, {values["id"]}, '
                f'{values["temp_c"]}f, {values["rain_mm"]}f, {period}}},'
            )
        else:
            rows.append(f'  {{"{name}", {array}, {len(timings)}, false, 0, 0.0f, 0.0f, 0}},')
    lines += [
        "static const VevorPulseScenario VEVOR_PULSE_VECTORS[] = {",
    ] + rows + [
        "};",
        "",
        f"static const int VEVOR_PULSE_COUNT = {len(rows)};",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    print(f"pulses.h écrit : {len(rows)} scénarios d'pulses")
    return 0


def selfcheck() -> int:
    """The encoder must reproduce the rtl_433 reference frame byte for byte."""
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
        "  const char *reject_reason;",
        "};",
        "",
        "static const VevorVector VEVOR_VECTORS[] = {",
    ]
    count = 0
    for name, raw, valid, reason in _scenarios():
        values = decode_reference(raw) if valid else {}
        raw_txt = ", ".join(f"0x{x:02x}" for x in raw)
        if valid:
            row = (
                f'  {{"{name}", {{{raw_txt}}}, true, {values["id"]}, {values["channel"]}, '
                f'{"true" if values["battery_low"] else "false"}, {values["temp_c"]}f, '
                f'{values["humidity"]}, {values["wind_kmh"]}f, {values["gust_kmh"]}f, '
                f'{values["wind_dir_deg"]}, {values["rain_mm"]}f, {values["uv"]}, '
                f'{values["lux"]}, {values["tx_counter"]}, ""}},'
            )
        else:
            row = (f'  {{"{name}", {{{raw_txt}}}, false, 0, 0, false, 0, 0, 0, 0, 0, 0, 0, 0, 0, '
                   f'"{reason}"}},')
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
    ap.add_argument("--captures", action="store_true")
    args = ap.parse_args()
    here = pathlib.Path(__file__).resolve().parent
    if args.selfcheck:
        return selfcheck()
    if args.vectors:
        return emit_vectors(here / "vectors.h")
    if args.pulses:
        return emit_pulses(here / "pulses.h")
    if args.captures:
        emit_captures(here / "captures.h", here / "data" / "captures_reelles.txt")
        return 0
    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main())
