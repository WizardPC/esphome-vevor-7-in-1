#!/usr/bin/env python3
"""Fetches a path from the witness firmware web server (unauthenticated, port 80) and saves it.

Useful for /logs: the witness server streams its log lines, including the boot dump_config
(frequency, deviation, bandwidth, AGC gain…). It is the only source to compare its radio config
to ours field by field while the board runs its firmware.

Usage: tools/witness_fetch.py --host <board-ip> --path /logs --seconds 20 --out logs/x.log
"""

from __future__ import annotations

import os
import argparse
import datetime as dt
import socket
import sys
import urllib.request
from pathlib import Path

DEV = Path(__file__).resolve().parent.parent   # dev/
ROOT = DEV.parent                               # repo root


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default=os.environ.get("VEVOR_HOST"),
                    required="VEVOR_HOST" not in os.environ,
                    help="board IP address. Fallback: VEVOR_HOST environment variable, or dev/tools/find_esp32.py to discover it")
    ap.add_argument("--path", default="/logs")
    ap.add_argument("--seconds", type=float, default=20.0)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    socket.setdefaulttimeout(10)
    out = Path(args.out)
    if not out.is_absolute():
        out = ROOT / out
    out.parent.mkdir(parents=True, exist_ok=True)

    lines = [
        f"# Witness — GET http://{args.host}{args.path} for {args.seconds:.0f} s",
        f"# {dt.datetime.now(dt.timezone.utc):%Y-%m-%dT%H:%M:%SZ}",
    ]
    deadline = dt.datetime.now().timestamp() + args.seconds
    try:
        with urllib.request.urlopen(f"http://{args.host}{args.path}", timeout=10) as resp:
            lines.append(f"# HTTP {resp.status} content-type={resp.headers.get('content-type')}")
            for raw in resp:
                lines.append(raw.decode("utf-8", "replace").rstrip("\r\n"))
                if dt.datetime.now().timestamp() >= deadline:
                    break
    except Exception as exc:  # noqa: BLE001 - a failure is a result, it is logged
        lines.append(f"# FAIL {type(exc).__name__}: {exc}")

    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"file: {out} ({len(lines)} lines)")
    for line in lines[:12]:
        print(" |", line[:200])
    return 0


if __name__ == "__main__":
    sys.exit(main())
