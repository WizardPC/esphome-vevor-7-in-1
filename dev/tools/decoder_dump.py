#!/usr/bin/env python3
"""Decode off-board the raw durations returned by the "Dump pulses" button.

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
error (unreadable file); 3 empty measurement: no capture (no "capture #"/"pulses" line).
"""

from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _common import (ANSI, RC_ERROR, RC_NULL_MEASUREMENT, RC_OK,  # noqa: E402
                     atomic_write_json)

import re

PERIODS = (90, 88, 89, 87)          # same candidates as the firmware
MAX_RUN_BITS = 64
FRAME_BYTES = 21

DUMP_RE = re.compile(r"pulses \[(\d+)-(\d+)\] of (\d+)\s*: (.+)$")
CAPTURE_RE = re.compile(r"capture #(\d+): (\d+) pulses, from (-?\d+) us to (-?\d+) us")


def read_dumps(path: pathlib.Path) -> list[list[int]]:
    """Return the list of captures, each a list of signed durations (µs)."""
    captures: list[list[int]] = []
    current: list[int] = []
    expected_total = None
    for line in ANSI.sub("", path.read_text(encoding="utf-8", errors="replace")).splitlines():
        m = CAPTURE_RE.search(line)
        if m:
            if current:
                captures.append(current)
            current, expected_total = [], None
            continue
        m = DUMP_RE.search(line)
        if not m:
            continue
        start, end, total, values = int(m.group(1)), int(m.group(2)), int(m.group(3)), m.group(4)
        n = len(values.split())
        if start == 0:
            expected_total = total
        if n != end - start + 1:
            print(f"  ! inconsistent slice [{start}-{end}]: {n} values", file=sys.stderr)
        if start != len(current):
            print(f"  ! slice [{start}-{end}] received while {len(current)} durations are already there",
                  file=sys.stderr)
        current.extend(int(x) for x in values.split())
        if expected_total is not None and len(current) >= expected_total:
            captures.append(current)
            current, expected_total = [], None
    if current:
        captures.append(current)
    return captures


def bits_from_durations(durations: list[int], period: int, invert: bool) -> str:
    half = period // 2
    bits = []
    for v in durations:
        level = 1 if v > 0 else 0
        duration = abs(v)
        ticks = (duration + half) // period
        ticks = max(1, ticks)
        if ticks > MAX_RUN_BITS:
            continue                      # gap between bursts, like the firmware
        bits.append(("1" if (1 - level) else "0") * ticks if invert else ("1" if level else "0") * ticks)
    return "".join(bits)


def plausibility_gate(b: bytes):
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
        return "humidity"
    temp_c = (((b[5] << 8) | b[6]) - 500) * 0.1
    if temp_c < -40.0 or temp_c > 60.0:
        return "temperature"
    return None


def frame_in_bits(bits: str):
    """Search for a conformant frame at any bit shift.

    Return (bytes, shift, position, refusal): `refusal` is None if the frame also passes the
    plausibility gate, else the refusal reason — the caller must NOT report it as valid.
    """
    for shift in range(min(8, len(bits))):
        usable = (len(bits) - shift) // 8 * 8
        bs = bytes(int(bits[shift + i: shift + i + 8], 2) for i in range(0, usable, 8))
        for i in range(len(bs) - FRAME_BYTES + 1):
            b = bs[i:i + FRAME_BYTES]
            if b[0] != 0xAA or b[1] != 0x00:
                continue
            if (sum(b[0:19]) & 0xFF) != b[19] or b[20] != ((b[18] + 1) & 0xFF):
                continue
            return b, shift, i, plausibility_gate(b)
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("dump", type=pathlib.Path)
    ap.add_argument("--json", default=None, help="JSON report (relative = project root)")
    args = ap.parse_args()

    if not args.dump.exists():
        print(f"# NULL MEASUREMENT — file missing: {args.dump}", file=sys.stderr)
        return RC_NULL_MEASUREMENT
    try:
        captures = read_dumps(args.dump)
    except OSError as exc:
        print(f"# ERROR reading {args.dump}: {exc}", file=sys.stderr)
        return RC_ERROR

    if not captures:
        print(f"# NULL MEASUREMENT — no capture in {args.dump}: nothing was measured "
              "(neither \"capture #\" nor \"pulses\")", file=sys.stderr)
        return RC_NULL_MEASUREMENT

    print(f"{len(captures)} capture(s) read in {args.dump}")
    report = []
    for nc, durations in enumerate(captures, 1):
        if durations:
            lo, hi = min(abs(x) for x in durations), max(abs(x) for x in durations)
            print(f"\ncapture {nc} : {len(durations)} durations, from {lo} to {hi} µs")
        else:
            print(f"\ncapture {nc} : 0 duration")
        found = None
        for period in PERIODS:
            for invert in (False, True):
                bits = bits_from_durations(durations, period, invert)
                if len(bits) < FRAME_BYTES * 8:
                    continue
                r = frame_in_bits(bits)
                if r:
                    b, shift, position, refusal = r
                    verdict = ("VALID FRAME" if refusal is None else
                               f"candidate conformant header+checksum+counter, REFUSED by the gate ({refusal})")
                    print(f"  >>> {verdict} : period {period} µs, "
                          f"{'inverted' if invert else 'normal'}, bit shift {shift}, "
                          f"byte position {position}")
                    print(f"      raw : {' '.join(f'{x:02x}' for x in b)}")
                    found = {"period": period, "inverted": invert, "bytes": list(b),
                             "refusal": refusal, "valid": refusal is None}
                    break
            if found:
                break
        if not found:
            # Nothing valid: show the best period's bytes for visual judgement.
            for period in PERIODS[:2]:
                bits = bits_from_durations(durations, period, False)
                bytes = bytes(int(bits[i:i + 8], 2) for i in range(0, len(bits) // 8 * 8, 8))[:12]
                print(f"  (period {period} µs, no inversion) first bytes: "
                      f"{' '.join(f'{x:02x}' for x in bytes)}")
        report.append({"capture": nc, "duration_count": len(durations), "frame": found})

    valid_count = sum(1 for r in report if r["frame"] and r["frame"].get("valid"))
    conformant = sum(1 for r in report if r["frame"] and not r["frame"].get("valid"))
    if args.json:
        print(f"\nreport written (atomic): {atomic_write_json(args.json, report)}")
    if conformant:
        print(f"{conformant} capture(s) carry a candidate conformant header+checksum+counter\n"
              f"but REFUSED by the plausibility gate: FALSE POSITIVE, not a reception")
    print(f"\n{valid_count} capture(s) out of {len(report)} carry a VALID frame")
    if valid_count == 0:
        print("# NO valid FRAME in the captures (measurement done) — negative result", file=sys.stderr)
    return RC_OK


if __name__ == "__main__":
    raise SystemExit(main())
