#!/usr/bin/env python3
"""Find the ESP32's IP (ESPHome native API on 6053) — used by the autonomous loop.

Usage: find_esp32.py --subnets <prefixes>  (or VEVOR_SUBNETS in the environment)

Strategy: if state/DEVICE_IP exists and still answers, return it (fast); otherwise scan the /24
on port 6053 and remember the first hit in state/DEVICE_IP. Deterministic output: one IP, or
"none" — which lets the loop scheduler detect a state change without waking the agent.
"""
from __future__ import annotations

import os
import argparse
import ipaddress
import pathlib
import socket
import sys
from concurrent.futures import ThreadPoolExecutor

DEV = pathlib.Path(__file__).resolve().parent.parent   # dev/
ROOT = DEV.parent                                      # repo root
CACHE = DEV / "state" / "DEVICE_IP"


def open_port(ip: str, port: int, timeout: float) -> bool:
    with socket.socket() as s:
        s.settimeout(timeout)
        return s.connect_ex((ip, port)) == 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--subnets", default=os.environ.get("VEVOR_SUBNETS"),
                    required="VEVOR_SUBNETS" not in os.environ,
                    help="subnet prefixes to scan, comma-separated (e.g. "
                         "\"192.168.1,192.168.2\"). Scan EVERY subnet the board traffic may cross: "
                         "a single-subnet scan wrongly concludes the board is absent.")
    ap.add_argument("--port", type=int, default=6053)
    ap.add_argument("--timeout", type=float, default=1.0)
    ap.add_argument("--refresh", action="store_true", help="ignore the cache and rescan")
    args = ap.parse_args()

    if not args.refresh and CACHE.exists():
        cached = CACHE.read_text(encoding="utf-8").strip()
        if cached and open_port(cached, args.port, args.timeout):
            print(cached)
            return 0

    hosts: list[str] = []
    for subnet in args.subnets.split(","):
        subnet = subnet.strip()
        if not subnet:
            continue
        hosts += [str(h) for h in ipaddress.ip_network(f"{subnet}.0/24", strict=False).hosts()]
    with ThreadPoolExecutor(max_workers=128) as pool:
        results = pool.map(lambda ip: ip if open_port(ip, args.port, args.timeout) else None, hosts)
    found = [ip for ip in results if ip]

    if not found:
        if CACHE.exists():
            CACHE.unlink()
        # "none" output and code 0: this is a state check, not a failing action. A non-zero code
        # would trip callers' `|| echo none` fallbacks (with pipefail) and duplicate the output.
        print("none")
        return 0

    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(found[0], encoding="utf-8")
    print(found[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())
