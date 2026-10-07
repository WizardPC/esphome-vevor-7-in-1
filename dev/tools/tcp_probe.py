#!/usr/bin/env python3
"""TCP link stability probe towards the ESP32 (ESPHome native API, port 6053).

Usage: tools/tcp_probe.py [--host <board-ip>] [--port 6053] [--seconds 60] [--interval 3]

Distinguishes "the board is absent" from "the Wi-Fi link is unstable" (low `output_power` or a
moving DHCP cause intermittent EHOSTUNREACH). Prints one line per attempt and a summary
(successes/failures, longest streak).
"""
from __future__ import annotations

import os
import argparse
import socket
import time


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default=os.environ.get("VEVOR_HOST"),
                    required="VEVOR_HOST" not in os.environ,
                    help="board IP address. Fallback: VEVOR_HOST environment variable, or dev/tools/find_esp32.py to discover it")
    ap.add_argument("--port", type=int, default=6053)
    ap.add_argument("--seconds", type=float, default=60.0)
    ap.add_argument("--interval", type=float, default=3.0)
    ap.add_argument("--timeout", type=float, default=2.5)
    args = ap.parse_args()

    t_end = time.monotonic() + args.seconds
    ok = fail = 0
    streak = best = 0
    results = []
    while time.monotonic() < t_end:
        t0 = time.monotonic()
        try:
            with socket.create_connection((args.host, args.port), timeout=args.timeout):
                dt = (time.monotonic() - t0) * 1000
                ok += 1
                streak += 1
                best = max(best, streak)
                print("[%s] OK   %s:%d  %.0f ms" % (time.strftime("%H:%M:%S"), args.host,
                                                    args.port, dt), flush=True)
                results.append("OK")
        except OSError as exc:
            fail += 1
            streak = 0
            print("[%s] ECHEC %s" % (time.strftime("%H:%M:%S"), exc), flush=True)
            results.append("ECHEC")
        time.sleep(max(0.0, args.interval - (time.monotonic() - t0)))

    total = ok + fail
    print("# bilan: %d/%d OK, %d echecs, longest serie OK=%d" % (ok, total, fail, best),
          flush=True)
    if fail and ok:
        print("# lien INSTABLE (joignable par intermittence)", flush=True)
    elif fail:
        print("# carte INJOIGNABLE sur toute la fenetre", flush=True)
    else:
        print("# lien STABLE sur toute la fenetre", flush=True)
    return 0 if ok and not fail else 2


if __name__ == "__main__":
    raise SystemExit(main())
