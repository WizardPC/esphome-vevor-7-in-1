#!/usr/bin/env python3
"""Summarizes a witness web server survey (logs/witness_probe_*.log).

Outputs: burst count, pulse-length distribution, internal gaps, decoded frames and intervals
between decodes. It is the control measurement "does the witness hear the station, and in what
state is the signal?", usable when the board runs the witness firmware.

Usage: tools/witness_summary.py logs/witness_probe_20260930_2032.log
"""

from __future__ import annotations

import re
import statistics
import sys
from pathlib import Path

BURST = re.compile(r"Salve RF recue\s*:\s*(\d+) pulses \((.*?)\)")
DECODE = re.compile(r"\[([0-9A-Fa-f]{4})\]\s*(.*)$")
CUT = re.compile(r"Trame coupee reconstruite avec succes \((\d+) \+ (\d+) pulses, extra=(-?\d+) us\)")


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    path = Path(sys.argv[1])
    text = path.read_text(encoding="utf-8", errors="replace")

    bursts = [(int(m.group(1)), m.group(2).strip()) for m in BURST.finditer(text)]
    decodes = [m.group(0).strip() for m in DECODE.finditer(text) if "[" in m.group(0)]
    cuts = [(int(m.group(1)), int(m.group(2)), int(m.group(3))) for m in CUT.finditer(text)]

    print(f"fichier            : {path}")
    print(f"rafales RF         : {len(bursts)}")
    if bursts:
        lengths = [b[0] for b in bursts]
        print(f"  pulses       : min={min(lengths)} max={max(lengths)} "
              f"med={statistics.median(lengths):.0f} (rafale utile mesurée le 30/09 à 18:41 : 166-174)")
        print(f"  premières rafales: ")
        for n, head in bursts[:6]:
            print(f"    {n:4d} imp — {head}")
    print(f"trames décodées    : {len(decodes)}")
    for d in decodes[-8:]:
        print(f"  {d}")
    # Witness log lines carry an internal pulse length in the form (x[0]=..).
    gaps = [m.group(1) for m in re.finditer(r"x\[0\]=(-?\d+)", text)]
    if gaps:
        g = sorted(int(v) for v in gaps)
        print(f"x[0] (1re durée)   : min={g[0]} us med={statistics.median(g):.0f} max={g[-1]} us "
              f"(témoin sain du 18:41 : +92 / −84 us)")
    print(f"trames recollées   : {len(cuts)} (témoin : capture coupée puis recollée)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
